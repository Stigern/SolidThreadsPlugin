//! Thread Generator for SolidCraft: cuts a 3D-printable thread into the selected face.
//!
//! One entry, `add-thread`. It reads the cylindrical face selected in SolidCraft, asks SolidCraft
//! whether it is a shaft or a hole (a cosmetic thread inside a checkpoint, then back), picks the
//! size, and cuts a modeled thread looser by the chosen tolerance class. With a height below 100%
//! the face is first offset so the teeth come out lower with flat tops. Every step is an ordinary
//! SolidCraft command, so the thread is a normal, editable feature in the timeline, and the whole
//! run is one undo step.
//!
//! A plugin run stops at the first command SolidCraft refuses, so every command here is one that
//! must succeed; nothing is tried and ignored.

pub mod sizes;

use serde_json::{json, Value};
use sizes::Probe;

/// What a step needs from the host: run one command with JSON args, get the JSON reply.
pub trait Runner {
    fn run(&mut self, command: &str, args: Value) -> Result<Value, String>;
    fn log(&mut self, _message: &str) {}
}

/// A problem with the input or the selection, reported against a field of the dialog.
#[derive(Debug, PartialEq)]
pub enum Error {
    Input { field: String, reason: String },
    Command(String),
}

impl Error {
    fn input(field: &str, reason: impl Into<String>) -> Self {
        Error::Input { field: field.into(), reason: reason.into() }
    }
}

impl From<String> for Error {
    fn from(s: String) -> Self {
        Error::Command(s)
    }
}

/// The dialog's values, checked.
#[derive(Clone, Debug, PartialEq)]
pub struct Params {
    pub size: sizes::Size,
    pub pitch: sizes::Pitch,
    pub tolerance: f64,
    pub height: f64,
    /// Thread length along the face (mm); `None` threads the whole face.
    pub length: Option<f64>,
}

pub fn parse_params(v: &Value) -> Result<Params, Error> {
    let text = |k: &str, d: &str| v.get(k).and_then(Value::as_str).unwrap_or(d).to_string();
    let size = sizes::parse_size(&text("size", "Auto")).map_err(|e| Error::input("size", e))?;
    let pitch = sizes::parse_pitch(&text("pitch", "1 mm")).map_err(|e| Error::input("pitch", e))?;
    let tolerance = match v.get("tolerance") {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.15),
        _ => sizes::parse_tolerance(&text("tolerance", "O.15")).map_err(|e| Error::input("tolerance", e))?,
    };
    if !(0.0..=2.0).contains(&tolerance) {
        return Err(Error::input("tolerance", "tolerance must be between 0 and 2 mm"));
    }
    let height = sizes::parse_height(&text("height", "85%")).map_err(|e| Error::input("height", e))?;
    let length = match v.get("length") {
        None | Some(Value::Null) => None,
        Some(x) => match x.as_f64() {
            Some(l) if l == 0.0 => None,
            Some(l) if l > 0.0 && l.is_finite() => Some(l),
            _ => return Err(Error::input("length", "length must be a positive number of mm, or empty for the whole face")),
        },
    };
    Ok(Params { size, pitch, tolerance, height, length })
}

/// The selected face: where it was picked, and its axis.
#[derive(Clone, Debug, PartialEq)]
pub struct Face {
    pub body: String,
    pub point: [f64; 3],
    pub origin: [f64; 3],
    pub axis: [f64; 3],
    pub diameter: f64,
}

fn vec3(v: &Value) -> Option<[f64; 3]> {
    let a = v.as_array()?;
    if a.len() != 3 {
        return None;
    }
    Some([a[0].as_f64()?, a[1].as_f64()?, a[2].as_f64()?])
}

/// The one cylindrical face in a `selection.get` reply.
pub fn selected_face(selection: &Value) -> Result<Face, Error> {
    let pick = "Select a cylindrical face in SolidCraft first: the outside of a shaft or the inside of a hole.";
    let items = selection.get("items").and_then(Value::as_array).cloned().unwrap_or_default();
    let faces: Vec<&Value> = items.iter().filter(|i| i.get("kind").or_else(|| i.get("type")) == Some(&json!("face"))).collect();
    if faces.is_empty() {
        return Err(Error::input("selection", pick));
    }
    let round: Vec<&&Value> = faces.iter().filter(|f| f.pointer("/surface/type") == Some(&json!("cylinder"))).collect();
    match round.as_slice() {
        [] => Err(Error::input("selection", format!("The selected face isn't cylindrical. {pick}"))),
        [f] => {
            let s = &f["surface"];
            let face = (|| {
                Some(Face {
                    body: f.get("body")?.as_str()?.to_string(),
                    point: vec3(f.get("point")?)?,
                    origin: vec3(s.get("origin")?)?,
                    axis: vec3(s.get("axis")?)?,
                    diameter: 2.0 * s.get("radius")?.as_f64()?,
                })
            })();
            face.ok_or_else(|| Error::Command("SolidCraft didn't describe the selected face".into()))
        }
        _ => Err(Error::input("selection", "Select only one cylindrical face: each thread is cut on its own.")),
    }
}

/// Ask SolidCraft what kind of thread fits the face, leaving the design as it was: a cosmetic
/// thread inside a checkpoint, then back to the checkpoint.
pub fn probe<R: Runner>(r: &mut R, face: &Face) -> Result<Probe, Error> {
    let cp = r.run("edit.checkpoint", json!({}))?;
    let cp = cp.get("checkpoint").cloned().ok_or_else(|| Error::Command("edit.checkpoint gave no checkpoint".into()))?;
    let res = r.run("solid.thread", json!({"face": face.point}))?;
    r.run("edit.restore_checkpoint", json!({"checkpoint": cp}))?;
    let t = res.get("thread").filter(|t| t.is_object()).ok_or_else(|| Error::Command("SolidCraft found no thread for that face".into()))?;
    let num = |k: &str| t.get(k).and_then(Value::as_f64);
    let span = (|| {
        Some(sizes::Span { origin: vec3(t.get("axis_point")?)?, axis: vec3(t.get("axis")?)?, start: num("start")?, end: num("end")? })
    })();
    Ok(Probe {
        internal: t.get("internal").and_then(Value::as_bool).unwrap_or(false),
        major_diameter: num("major_diameter").unwrap_or(face.diameter),
        pitch: num("pitch").unwrap_or(1.0),
        face_diameter: face.diameter,
        span,
    })
}

fn taken_names<R: Runner>(r: &mut R) -> Result<Vec<String>, Error> {
    let doc = r.run("document.inspect", json!({"timeline": "summary", "bodies": false}))?;
    Ok(doc
        .get("timeline")
        .and_then(Value::as_array)
        .map(|t| t.iter().filter_map(|f| f.get("name").and_then(Value::as_str).map(String::from)).collect())
        .unwrap_or_default())
}

/// Cut the thread into the selected face; returns what was made.
pub fn add_thread<R: Runner>(r: &mut R, p: &Params) -> Result<Value, Error> {
    let face = selected_face(&r.run("selection.get", json!({"detail": true}))?)?;
    let info = probe(r, &face)?;
    let (d, pitch) = sizes::choose_size(&p.size, p.pitch, &info).map_err(|e| Error::input("size", e))?;
    if p.tolerance > pitch / 2.0 {
        return Err(Error::input("tolerance", format!("tolerance can be at most {} mm for a {} mm pitch", sizes::fmt(pitch / 2.0, 4), sizes::fmt(pitch, 4))));
    }
    let mut geo = sizes::geometry(d, pitch, p.tolerance, info.internal, p.height);
    if geo.surface.is_none() {
        geo.surface = sizes::open_narrow_hole(info.internal, face.diameter, d, pitch, p.tolerance);
    }
    let tag = sizes::label(info.internal, d, pitch, p.tolerance, p.height);
    let kind = if info.internal { "hole" } else { "shaft" };
    r.log(&format!("{} on {}: Ø{} mm, cutting {} as {}", kind, face.body, sizes::fmt(face.diameter, 3), tag, geo.designation));

    let mut taken = taken_names(r)?;
    let mut features = Vec::new();
    let mut point = face.point;
    if let Some(surface) = geo.surface {
        // positive moves the face out of the material: a shaft thicker, a hole narrower
        let dist = (surface - face.diameter) / 2.0 * if info.internal { -1.0 } else { 1.0 };
        if dist.abs() > 1e-4 {
            let res = r.run("solid.offset_face", json!({"faces": [face.point], "distance": format!("{dist:.4} mm")}))?;
            if let Some(f) = res.get("feature").filter(|f| !f.is_null()).cloned() {
                let what = if info.internal { "Hole" } else { "Shaft" };
                let name = sizes::unique_name(&format!("{what} Ø{} for {tag}", sizes::fmt(surface, 3)), &taken);
                r.run("timeline.rename", json!({"feature": f, "name": name}))?;
                taken.push(name);
                features.push(f);
            }
            point = sizes::point_at_radius(face.point, face.origin, face.axis, surface / 2.0);
        }
    }

    let mut args = json!({"face": point, "designation": geo.designation, "modeled": true});
    // A length as long as the face or longer threads the whole face.
    let face_length = info.span.as_ref().map(|s| (s.end - s.start).abs());
    if let Some(l) = p.length.filter(|l| face_length.is_none_or(|f| *l < f - 1e-6)) {
        args["length"] = json!(format!("{} mm", sizes::fmt(l, 4)));
        if let Some(from) = info.span.as_ref().and_then(|s| sizes::start_from(s, point)) {
            args["from"] = json!(from);
        }
    }
    let res = r.run("solid.thread", args)?;
    let mut name = res.get("name").and_then(Value::as_str).unwrap_or_default().to_string();
    if let Some(f) = res.get("feature").filter(|f| !f.is_null()).cloned() {
        name = sizes::unique_name(&tag, &taken);
        r.run("timeline.rename", json!({"feature": f, "name": name}))?;
        taken.push(name.clone());
        features.push(f);
    }
    if features.len() > 1 {
        let group = sizes::unique_name(&format!("Thread {name}"), &taken);
        r.run("timeline.group", json!({"name": group, "features": features}))?;
    }

    // Below full height the hole was set to its diameter above, whatever it was drilled at.
    let hint = if geo.surface.is_none() { sizes::drill_hint(&info, d, pitch) } else { None };
    if let Some(h) = &hint {
        r.log(&format!("Tip: {h}"));
    }
    Ok(json!({
        "name": name,
        "kind": kind,
        "body": face.body,
        "size": format!("M{}x{}", sizes::fmt(d, 3), sizes::fmt(pitch, 4)),
        "tolerance": sizes::tolerance_class(p.tolerance),
        "height_percent": (p.height * 100.0 * 10.0).round() / 10.0,
        "designation": geo.designation,
        "face_diameter": face.diameter,
        "surface_diameter": geo.surface,
        "tooth_height": geo.tooth,
        "iso_fit": sizes::designation(info.major_diameter, info.pitch),
        "steps": features.len(),
        "hint": hint,
    }))
}

#[cfg(target_arch = "wasm32")]
mod guest {
    wit_bindgen::generate!({ path: "wit", world: "command-plugin" });

    use super::*;
    use craft::plugin::{
        commands, log,
        types::{CommandFailure, FieldFailure, PluginError},
    };

    struct Host;
    impl Runner for Host {
        fn run(&mut self, command: &str, args: Value) -> Result<Value, String> {
            match commands::run(command, &args.to_string()) {
                Ok(s) => Ok(serde_json::from_str(&s).unwrap_or(Value::Null)),
                Err(PluginError::CommandFailed(f)) => Err(format!("{}: {}", f.command, f.reason)),
                Err(e) => Err(format!("{command}: {e:?}")),
            }
        }
        fn log(&mut self, message: &str) {
            log::log(log::Level::Info, message);
        }
    }

    fn plugin_error(e: Error) -> PluginError {
        match e {
            Error::Input { field, reason } => PluginError::InvalidInput(FieldFailure { field, reason }),
            Error::Command(reason) => PluginError::CommandFailed(CommandFailure { command: "add-thread".into(), reason }),
        }
    }

    struct ThreadGenerator;
    impl exports::craft::plugin::entry::Guest for ThreadGenerator {
        fn execute(entry: String, params: String) -> Result<String, PluginError> {
            match entry.as_str() {
                "add-thread" => {
                    let v: Value = serde_json::from_str(&params).unwrap_or(json!({}));
                    let p = parse_params(&v).map_err(plugin_error)?;
                    add_thread(&mut Host, &p).map(|v| v.to_string()).map_err(plugin_error)
                }
                other => Err(PluginError::InvalidInput(FieldFailure { field: "entry".into(), reason: format!("unknown entry {other}") })),
            }
        }
    }
    export!(ThreadGenerator);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Plays SolidCraft: a selected shaft or hole, and a record of the commands.
    struct Fake {
        selection: Value,
        internal: bool,
        calls: Vec<(String, Value)>,
    }
    impl Runner for Fake {
        fn run(&mut self, command: &str, args: Value) -> Result<Value, String> {
            self.calls.push((command.to_string(), args.clone()));
            Ok(match command {
                "selection.get" => self.selection.clone(),
                "edit.checkpoint" => json!({"checkpoint": 7}),
                "solid.thread" if args.get("designation").is_none() => json!({"feature": 9, "name": "Thread1", "thread": {
                    "internal": self.internal, "major_diameter": 8.0, "pitch": 1.25, "designation": "M8",
                    "axis": [0.0, 0.0, 1.0], "axis_point": [0.0, 0.0, 0.0], "start": 0.0, "end": 20.0}}),
                "solid.thread" => json!({"feature": 3, "name": "Thread1", "thread": null}),
                "solid.offset_face" => json!({"feature": 2, "name": "OffsetFace1"}),
                "document.inspect" => json!({"timeline": [{"id": 1, "name": "Cylinder1"}, {"id": 5, "name": "External M8x1 O.15 85%"}]}),
                _ => json!({}),
            })
        }
    }

    fn face(radius: f64) -> Value {
        json!({"count": 1, "items": [{"kind": "face", "type": "face", "body": "Body1", "index": 0, "point": [radius, 0.0, 10.0],
            "surface": {"type": "cylinder", "origin": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "radius": radius}}]})
    }

    fn defaults() -> Params {
        parse_params(&json!({"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "85%"})).unwrap()
    }

    fn commands(f: &Fake) -> Vec<&str> {
        f.calls.iter().map(|(c, _)| c.as_str()).collect()
    }

    #[test]
    fn threads_a_shaft_lower_and_looser() {
        let mut f = Fake { selection: face(4.0), internal: false, calls: vec![] };
        let out = add_thread(&mut f, &defaults()).unwrap();
        assert_eq!(
            commands(&f),
            [
                "selection.get", "edit.checkpoint", "solid.thread", "edit.restore_checkpoint", "document.inspect",
                "solid.offset_face", "timeline.rename", "solid.thread", "timeline.rename", "timeline.group"
            ]
        );
        assert_eq!(f.calls[3].1, json!({"checkpoint": 7}));
        // the shaft is made thinner first: 7.85 less the trimmed tips, on the radius
        let surface = 7.85 - 2.0 * 0.15 * sizes::ISO_HEIGHT;
        let dist = (surface - 8.0) / 2.0;
        assert_eq!(f.calls[5].1["distance"], json!(format!("{dist:.4} mm")));
        let cut = &f.calls[7].1;
        assert_eq!(cut["designation"], "M7.85x1");
        assert_eq!(cut["modeled"], true);
        assert!((cut["face"][0].as_f64().unwrap() - surface / 2.0).abs() < 1e-9);
        // an existing thread already has this name
        assert_eq!(out["name"], "External M8x1 O.15 85% (2)");
        assert_eq!(f.calls[9].1["features"], json!([2, 3]));
        assert_eq!(out["steps"], 2);
    }

    #[test]
    fn full_height_hole_is_one_step() {
        let mut f = Fake { selection: face(3.6), internal: true, calls: vec![] };
        let p = parse_params(&json!({"size": "Auto", "pitch": "1 mm", "tolerance": "O.2", "height": "100%", "length": 6})).unwrap();
        let out = add_thread(&mut f, &p).unwrap();
        assert!(!commands(&f).contains(&"solid.offset_face"));
        assert!(!commands(&f).contains(&"timeline.group"));
        let cut = &f.calls[5].1;
        assert_eq!(cut["designation"], "M8.2x1");
        assert_eq!(cut["length"], "6 mm");
        // picked halfway along a face free at both ends: start from the nearer end
        assert_eq!(cut["from"], json!([3.6, 0.0, 0.0]));
        assert_eq!(out["name"], "Internal M8x1 O.2");
        assert_eq!(out["hint"], Value::Null);
    }

    #[test]
    fn a_length_past_the_face_threads_all_of_it() {
        let mut f = Fake { selection: face(4.0), internal: false, calls: vec![] };
        let p = parse_params(&json!({"tolerance": "O.0", "height": "100%", "length": 25})).unwrap();
        add_thread(&mut f, &p).unwrap();
        let cut = &f.calls.iter().find(|(c, a)| c == "solid.thread" && a.get("designation").is_some()).unwrap().1;
        assert!(cut.get("length").is_none() && cut.get("from").is_none());
    }

    #[test]
    fn needs_one_cylindrical_face() {
        let mut f = Fake { selection: json!({"count": 0, "items": []}), internal: false, calls: vec![] };
        assert!(matches!(add_thread(&mut f, &defaults()), Err(Error::Input { field, .. }) if field == "selection"));
        let plane = json!({"items": [{"kind": "face", "surface": {"type": "plane"}}]});
        assert!(selected_face(&plane).is_err());
        let mut two = face(4.0);
        let again = two["items"][0].clone();
        two["items"].as_array_mut().unwrap().push(again);
        assert!(selected_face(&two).is_err());
    }

    #[test]
    fn checks_the_tolerance_against_the_pitch() {
        let mut f = Fake { selection: face(4.0), internal: false, calls: vec![] };
        let p = parse_params(&json!({"pitch": "1 mm", "tolerance": "O.8"})).unwrap();
        assert!(matches!(add_thread(&mut f, &p), Err(Error::Input { field, .. }) if field == "tolerance"));
        // nothing was cut
        assert_eq!(f.calls.iter().filter(|(c, a)| c == "solid.thread" && a.get("designation").is_some()).count(), 0);
    }

    #[test]
    fn manifest_matches_the_code() {
        let m: Value = serde_json::from_str(include_str!("../plugin.json")).unwrap();
        let version = m["version"].as_str().unwrap();
        assert_eq!(version, env!("CARGO_PKG_VERSION"));
        let entry = &m["runtime"]["entries"][0];
        assert_eq!(entry["name"], "add-thread");
        let props = &entry["input_schema"]["properties"];
        let choices = |k: &str| props[k]["enum"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect::<Vec<_>>();
        assert_eq!(choices("pitch"), sizes::PITCH_CHOICES);
        assert_eq!(choices("tolerance"), sizes::TOLERANCE_CHOICES);
        assert_eq!(choices("height"), sizes::HEIGHT_CHOICES);
        // every default in the dialog parses
        let shown: serde_json::Map<String, Value> =
            props.as_object().unwrap().iter().filter_map(|(k, v)| v.get("default").map(|d| (k.clone(), d.clone()))).collect();
        assert_eq!(parse_params(&Value::Object(shown)).unwrap(), defaults());
        // and the commands it may call are the ones the code calls
        let listed: Vec<&str> = m["runtime"]["commands"].as_array().unwrap().iter().map(|c| c.as_str().unwrap()).collect();
        let mut f = Fake { selection: face(4.0), internal: false, calls: vec![] };
        add_thread(&mut f, &defaults()).unwrap();
        for c in commands(&f) {
            assert!(listed.contains(&c), "{c} is not in plugin.json's commands");
        }
    }
}
