//! Thread sizes, tolerance classes and the diameters a thread is cut at.
//!
//! Pure maths, no SolidCraft calls, so `cargo test` covers all of it. It follows the Python
//! generator (`sc_live.py`, `threadgen_gui.py`) so a thread made by the plugin matches one
//! made by the standalone window.

/// The pitches of the 3D-printed metric standard, after CustomThreads
/// (github.com/BalzGuenat/CustomThreads, MIT), with the smallest diameter each one is offered on.
pub const PRINTED_PITCHES: [(f64, f64); 5] = [(1.0, 4.0), (2.0, 4.0), (2.5, 6.0), (3.5, 8.0), (5.0, 8.0)];

/// ISO metric coarse: name, major diameter, pitch (mm).
pub const ISO_COARSE: [(&str, f64, f64); 21] = [
    ("M1", 1.0, 0.25), ("M1.2", 1.2, 0.25), ("M1.4", 1.4, 0.3), ("M1.6", 1.6, 0.35),
    ("M2", 2.0, 0.4), ("M2.5", 2.5, 0.45), ("M3", 3.0, 0.5), ("M4", 4.0, 0.7),
    ("M5", 5.0, 0.8), ("M6", 6.0, 1.0), ("M8", 8.0, 1.25), ("M10", 10.0, 1.5),
    ("M12", 12.0, 1.75), ("M14", 14.0, 2.0), ("M16", 16.0, 2.0),
    ("M20", 20.0, 2.5), ("M24", 24.0, 3.0), ("M30", 30.0, 3.5),
    ("M36", 36.0, 4.0), ("M42", 42.0, 4.5), ("M48", 48.0, 5.0),
];

/// UNC: name, major diameter (mm), threads per inch.
pub const UNC: [(&str, f64, f64); 11] = [
    ("#4-40", 2.845, 40.0), ("#6-32", 3.505, 32.0), ("#8-32", 4.166, 32.0), ("#10-24", 4.826, 24.0),
    ("1/4-20", 6.35, 20.0), ("5/16-18", 7.938, 18.0), ("3/8-16", 9.525, 16.0), ("1/2-13", 12.7, 13.0),
    ("5/8-11", 15.875, 11.0), ("3/4-10", 19.05, 10.0), ("1-8", 25.4, 8.0),
];

/// The ISO basic thread height (5H/8, radial) as a fraction of the pitch. SolidCraft cuts an
/// external thread's root this deep below its major diameter; an internal thread's teeth reach
/// in as far as the hole lets them.
pub const ISO_HEIGHT: f64 = 0.54127;

/// The choices of the dialog's fields, as the manifest lists them.
pub const PITCH_CHOICES: [&str; 6] = ["1 mm", "2 mm", "2.5 mm", "3.5 mm", "5 mm", "ISO standard"];
pub const TOLERANCE_CHOICES: [&str; 6] = ["O.0", "O.1", "O.15", "O.2", "O.4", "O.8"];
pub const HEIGHT_CHOICES: [&str; 7] = ["100%", "95%", "90%", "85%", "80%", "75%", "70%"];

/// The Pitch field: one of the printed pitches, or the ISO standard pitch for the diameter.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Pitch {
    Printed(f64),
    Iso,
}

/// The Size field.
#[derive(Clone, Debug, PartialEq)]
pub enum Size {
    /// Fit the selected face.
    Auto,
    /// A diameter with no pitch (`M10`): the pitch comes from the Pitch field.
    Diameter(f64),
    /// Diameter and pitch (`M8x1`, or a UNC size).
    Full(f64, f64),
}

/// A number written with up to `decimals` decimals and no trailing zeros: 8 -> "8", 1.25 -> "1.25".
pub fn fmt(x: f64, decimals: usize) -> String {
    let s = format!("{:.*}", decimals, x);
    let s = if s.contains('.') { s.trim_end_matches('0').trim_end_matches('.').to_string() } else { s };
    if s == "-0" { "0".into() } else { s }
}

fn number(s: &str) -> Option<f64> {
    let s = s.trim().replace(',', ".");
    if s.is_empty() || !s.chars().all(|c| c.is_ascii_digit() || c == '.') {
        return None;
    }
    s.parse::<f64>().ok().filter(|x| x.is_finite())
}

pub fn parse_pitch(s: &str) -> Result<Pitch, String> {
    let t = s.trim();
    if t.eq_ignore_ascii_case("iso standard") || t.eq_ignore_ascii_case("iso") {
        return Ok(Pitch::Iso);
    }
    let n = number(t.trim_end_matches("mm")).ok_or_else(|| format!("unknown pitch {t:?}"))?;
    if PRINTED_PITCHES.iter().any(|(p, _)| *p == n) {
        Ok(Pitch::Printed(n))
    } else {
        Err(format!("pitch {t:?} is not one of 1, 2, 2.5, 3.5 or 5 mm; type the size as M8x{} instead", fmt(n, 4)))
    }
}

/// "M8x1", "m 8 x 1", "8x1.25", "M10", "1/4-20", "Auto" or empty.
pub fn parse_size(s: &str) -> Result<Size, String> {
    let t = s.trim();
    if t.is_empty() || t.eq_ignore_ascii_case("auto") {
        return Ok(Size::Auto);
    }
    if let Some((_, d, tpi)) = UNC.iter().find(|(n, _, _)| n.eq_ignore_ascii_case(t)) {
        return Ok(Size::Full(*d, 25.4 / tpi));
    }
    let bad = || format!("size {t:?} isn't one I can read: type it like M8x1, M10 or 1/4-20, or Auto");
    let body = t.strip_prefix(['M', 'm']).unwrap_or(t);
    let parts: Vec<&str> = body.split(['x', 'X', '×', '*']).collect();
    let (d, p) = match parts.as_slice() {
        [d] => (number(d).ok_or_else(bad)?, None),
        [d, p] => (number(d).ok_or_else(bad)?, Some(number(p).ok_or_else(bad)?)),
        _ => return Err(bad()),
    };
    if d <= 0.0 {
        return Err(bad());
    }
    match p {
        None => Ok(Size::Diameter(d)),
        Some(p) if p <= 0.0 || p >= d => Err(format!("size {t:?} needs a diameter larger than the pitch, like M9x1.5")),
        Some(p) => Ok(Size::Full(d, p)),
    }
}

/// "O.15" -> 0.15 mm off each diameter of this part. A plain number is millimetres.
pub fn parse_tolerance(s: &str) -> Result<f64, String> {
    let t = s.trim();
    let n = match t.strip_prefix(['O', 'o']) {
        Some(rest) => number(&format!("0{rest}")),
        None => number(t),
    };
    n.ok_or_else(|| format!("tolerance {t:?} must be a class like O.2 or a number in mm"))
}

/// "85%" -> 0.85, between 50% and 100%.
pub fn parse_height(s: &str) -> Result<f64, String> {
    let t = s.trim();
    let n = number(t.trim_end_matches('%')).ok_or_else(|| format!("height {t:?} must be a percentage, like 80%"))?;
    if !(50.0..=100.0).contains(&n) {
        return Err(format!("height {t:?} must be between 50% and 100%"));
    }
    Ok(n / 100.0)
}

/// The name CustomThreads gives a diameter offset: 0.2 -> "O.2", 0.15 -> "O.15", 0 -> "O.0".
pub fn tolerance_class(offset: f64) -> String {
    let s = fmt(offset, 3);
    if s == "0" {
        "O.0".into()
    } else if let Some(rest) = s.strip_prefix("0.") {
        format!("O.{rest}")
    } else {
        format!("O+{s}")
    }
}

pub fn designation(diameter: f64, pitch: f64) -> String {
    format!("M{}x{}", fmt(diameter, 3), fmt(pitch, 4))
}

/// What SolidCraft says about the face: from a cosmetic `solid.thread` with no size.
#[derive(Clone, Debug, PartialEq)]
pub struct Probe {
    pub internal: bool,
    /// SolidCraft's own ISO fit for the face.
    pub major_diameter: f64,
    pub pitch: f64,
    /// The cylinder's diameter.
    pub face_diameter: f64,
    /// Where the face lies along its axis, when SolidCraft says.
    pub span: Option<Span>,
}

/// The nominal size (diameter, pitch) to cut, from the dialog's Size and Pitch and the face.
///
/// Auto with a printed pitch keeps that pitch. A shaft gets its own diameter. A hole of a whole
/// millimetre does too (a Ø14 hole is M14, so it takes a bolt made from a Ø14 shaft); any other
/// hole is a tap drill and gets the diameter whose tap drill (diameter - pitch) it is: Ø6.8 -> M8.
/// So does a whole-millimetre hole too small for the pitch: Ø3 -> M4x1. Auto with ISO takes
/// SolidCraft's fit.
pub fn choose_size(size: &Size, pitch: Pitch, face: &Probe) -> Result<(f64, f64), String> {
    let (d, p) = match (size, pitch) {
        (Size::Full(d, p), _) => (*d, *p),
        (Size::Diameter(d), Pitch::Printed(p)) => (*d, p),
        (Size::Diameter(d), Pitch::Iso) => match ISO_COARSE.iter().find(|(_, d0, _)| (d0 - d).abs() < 1e-9) {
            Some((_, d0, p0)) => (*d0, *p0),
            None => return Err(format!("M{} has no ISO coarse pitch: pick a pitch, or type the size like M{}x1.5", fmt(*d, 3), fmt(*d, 3))),
        },
        (Size::Auto, Pitch::Iso) => (face.major_diameter, face.pitch),
        (Size::Auto, Pitch::Printed(p)) => {
            let smallest = PRINTED_PITCHES.iter().find(|(q, _)| *q == p).map(|(_, from)| *from).unwrap_or(4.0);
            let own = face.face_diameter.round();
            let nominal = !face.internal || ((face.face_diameter - own).abs() < 0.05 && own >= smallest);
            let d = if nominal { own } else { (face.face_diameter + p).round() };
            if d < smallest {
                let kind = if face.internal { "hole" } else { "shaft" };
                return Err(format!(
                    "this Ø{} mm {kind} is too small for a {} mm pitch (M{} and up); pick a smaller pitch",
                    fmt(face.face_diameter, 3),
                    fmt(p, 1),
                    fmt(smallest, 0)
                ));
            }
            (d, p)
        }
    };
    if p >= d {
        return Err(format!("M{}x{} needs a diameter larger than the pitch", fmt(d, 3), fmt(p, 4)));
    }
    Ok((d, p))
}

/// The diameters a thread is cut at.
#[derive(Clone, Debug, PartialEq)]
pub struct Geometry {
    /// What SolidCraft cuts: the nominal diameter, `offset` looser.
    pub designation: String,
    /// The diameter the shaft or hole is set to first, or `None` to leave the face as it is.
    /// A shaft is always set to the thread's (looser) major diameter, less the trimmed tips:
    /// SolidCraft refuses a modeled thread on a shaft thicker than the thread. A hole is opened
    /// up only for lower teeth; at full height the teeth reach in as far as the hole lets them.
    pub surface: Option<f64>,
    /// The radial height of the teeth (mm).
    pub tooth: f64,
}

/// As in CustomThreads' tolerance classes: an external thread's diameters get `offset` smaller,
/// an internal thread's `offset` larger; the pitch stays. A lower thread (`height` < 1) flattens
/// the tops of the teeth only, on both parts, so the flanks stay where a full thread has them and
/// a bolt and nut of the same height still fit; they engage over less depth.
pub fn geometry(diameter: f64, pitch: f64, offset: f64, internal: bool, height: f64) -> Geometry {
    let h0 = ISO_HEIGHT * pitch;
    let trim = (1.0 - height) * h0;
    let low = height < 1.0;
    let (d, surface) = if internal {
        let d = diameter + offset;
        (d, low.then(|| d - 2.0 * h0 + 2.0 * trim))
    } else {
        let d = diameter - offset;
        (d, Some(d - 2.0 * trim))
    };
    Geometry { designation: designation(d, pitch), surface, tooth: height * h0 }
}

/// At full height a hole is left as drilled, unless it is narrower than the thread's minor
/// diameter: SolidCraft refuses to cut teeth that would fill the hole, so it is opened up to the
/// minor diameter first. `have` is the hole's diameter; returns the diameter to open it to.
pub fn open_narrow_hole(internal: bool, have: f64, diameter: f64, pitch: f64, offset: f64) -> Option<f64> {
    let minor = diameter + offset - 2.0 * ISO_HEIGHT * pitch;
    (internal && have < minor - 1e-3).then_some(minor)
}

/// The timeline name of a thread: "External M8x1 O.15 85%".
pub fn label(internal: bool, diameter: f64, pitch: f64, offset: f64, height: f64) -> String {
    let kind = if internal { "Internal" } else { "External" };
    let mut s = format!("{kind} M{}x{} {}", fmt(diameter, 3), fmt(pitch, 4), tolerance_class(offset));
    if height < 1.0 {
        s.push_str(&format!(" {}%", fmt(height * 100.0, 1)));
    }
    s
}

/// `base`, or `base (2)`, `base (3)` … whichever is not taken yet.
pub fn unique_name(base: &str, taken: &[String]) -> String {
    let mut name = base.to_string();
    let mut k = 2;
    while taken.iter().any(|t| *t == name) {
        name = format!("{base} ({k})");
        k += 1;
    }
    name
}

/// `point` moved away from the axis (through `origin` along `axis`) to `radius`.
pub fn point_at_radius(point: [f64; 3], origin: [f64; 3], axis: [f64; 3], radius: f64) -> [f64; 3] {
    let n = (axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2]).sqrt().max(1e-300);
    let a = [axis[0] / n, axis[1] / n, axis[2] / n];
    let v = [point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]];
    let along = v[0] * a[0] + v[1] * a[1] + v[2] * a[2];
    let foot = [origin[0] + along * a[0], origin[1] + along * a[1], origin[2] + along * a[2]];
    let r = [point[0] - foot[0], point[1] - foot[1], point[2] - foot[2]];
    let rn = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt().max(1e-300);
    [foot[0] + radius * r[0] / rn, foot[1] + radius * r[1] / rn, foot[2] + radius * r[2] / rn]
}

/// Where a face lies along its axis: from `start` to `end` (mm along the unit `axis`, from `origin`),
/// as SolidCraft's thread reply gives it.
#[derive(Clone, Debug, PartialEq)]
pub struct Span {
    pub origin: [f64; 3],
    pub axis: [f64; 3],
    pub start: f64,
    pub end: f64,
}

/// The end a partial-length thread starts from, for `solid.thread`'s `from`, or `None` to leave it
/// to SolidCraft. SolidCraft starts from the face's only free end, or else from the end the pick
/// lies within a third of the face of, and refuses a pick in the middle of a face free at both
/// ends. So for a pick in the middle third this names the end nearer the pick.
pub fn start_from(span: &Span, pick: [f64; 3]) -> Option<[f64; 3]> {
    let n = (span.axis.iter().map(|a| a * a).sum::<f64>()).sqrt();
    let length = span.end - span.start;
    if n < 1e-12 || length.abs() < 1e-9 {
        return None;
    }
    let a = span.axis.map(|x| x / n);
    let t = (0..3).map(|i| (pick[i] - span.origin[i]) * a[i]).sum::<f64>();
    let share = (t - span.start) / length;
    if !(1.0 / 3.0..=2.0 / 3.0).contains(&share) {
        return None;
    }
    let to = if share <= 0.5 { span.start } else { span.end };
    Some([0, 1, 2].map(|i| pick[i] + (to - t) * a[i]))
}

/// For a hole left as it is (full height): a note when it is far from the tap drill
/// (diameter - pitch) the thread wants. None for a hole at the nominal diameter, which SolidCraft
/// narrows to the thread itself.
pub fn drill_hint(face: &Probe, diameter: f64, pitch: f64) -> Option<String> {
    if !face.internal {
        return None;
    }
    let want = diameter - pitch;
    let have = face.face_diameter;
    if (have - want).abs() < 0.3 || (have - diameter).abs() < 0.3 {
        return None;
    }
    let tail = if have > want { ", so the thread is shallow" } else { "" };
    Some(format!(
        "for M{}x{} the hole should be about Ø{} mm; it is Ø{} mm{tail}",
        fmt(diameter, 3),
        fmt(pitch, 4),
        fmt(want, 2),
        fmt(have, 3)
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shaft(d: f64) -> Probe {
        Probe { internal: false, major_diameter: d, pitch: 1.25, face_diameter: d, span: None }
    }
    fn hole(d: f64) -> Probe {
        Probe { internal: true, major_diameter: 8.0, pitch: 1.25, face_diameter: d, span: None }
    }

    #[test]
    fn numbers_print_like_python_g() {
        assert_eq!(fmt(8.0, 3), "8");
        assert_eq!(fmt(1.25, 4), "1.25");
        assert_eq!(fmt(7.85, 3), "7.85");
        assert_eq!(fmt(0.0, 3), "0");
        assert_eq!(designation(7.85, 1.0), "M7.85x1");
    }

    #[test]
    fn sizes() {
        assert_eq!(parse_size("Auto"), Ok(Size::Auto));
        assert_eq!(parse_size(" "), Ok(Size::Auto));
        assert_eq!(parse_size("M8x1"), Ok(Size::Full(8.0, 1.0)));
        assert_eq!(parse_size("m 9 x 1,5"), Ok(Size::Full(9.0, 1.5)));
        assert_eq!(parse_size("10x1.25"), Ok(Size::Full(10.0, 1.25)));
        assert_eq!(parse_size("M10"), Ok(Size::Diameter(10.0)));
        assert_eq!(parse_size("1/4-20"), Ok(Size::Full(6.35, 25.4 / 20.0)));
        assert!(parse_size("M2x3").is_err());
        assert!(parse_size("bolt").is_err());
        assert!(parse_size("M8x").is_err());
    }

    #[test]
    fn fields() {
        assert_eq!(parse_pitch("2.5 mm"), Ok(Pitch::Printed(2.5)));
        assert_eq!(parse_pitch("ISO standard"), Ok(Pitch::Iso));
        assert!(parse_pitch("1.5 mm").is_err());
        assert_eq!(parse_tolerance("O.15"), Ok(0.15));
        assert_eq!(parse_tolerance("O.0"), Ok(0.0));
        assert_eq!(parse_tolerance("0.3"), Ok(0.3));
        assert_eq!(parse_height("85%"), Ok(0.85));
        assert!(parse_height("40%").is_err());
        for c in PITCH_CHOICES {
            parse_pitch(c).unwrap();
        }
        for c in TOLERANCE_CHOICES {
            assert_eq!(tolerance_class(parse_tolerance(c).unwrap()), c);
        }
        for c in HEIGHT_CHOICES {
            parse_height(c).unwrap();
        }
    }

    #[test]
    fn auto_keeps_the_printed_pitch() {
        // a shaft gets its own diameter, a hole the size whose tap drill it is
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &shaft(8.0)), Ok((8.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &shaft(7.9)), Ok((8.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &hole(6.8)), Ok((8.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(3.5), &hole(16.5)), Ok((20.0, 3.5)));
        // a whole-millimetre hole is its own size, as a shaft is: a Ø14 shaft and a Ø14 hole mate
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &hole(14.0)), Ok((14.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &shaft(14.0)), Ok((14.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &hole(13.999)), Ok((14.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(2.0), &hole(8.0)), Ok((8.0, 2.0)));
        // unless it is too small for the pitch: then it is a tap drill
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(1.0), &hole(3.0)), Ok((4.0, 1.0)));
        assert_eq!(choose_size(&Size::Auto, Pitch::Printed(5.0), &hole(5.0)), Ok((10.0, 5.0)));
        assert!(choose_size(&Size::Auto, Pitch::Printed(3.5), &shaft(6.0)).is_err());
        assert_eq!(choose_size(&Size::Auto, Pitch::Iso, &shaft(8.0)), Ok((8.0, 1.25)));
    }

    #[test]
    fn typed_sizes() {
        assert_eq!(choose_size(&Size::Full(9.0, 1.5), Pitch::Printed(1.0), &shaft(8.0)), Ok((9.0, 1.5)));
        assert_eq!(choose_size(&Size::Diameter(10.0), Pitch::Printed(2.0), &shaft(8.0)), Ok((10.0, 2.0)));
        assert_eq!(choose_size(&Size::Diameter(10.0), Pitch::Iso, &shaft(8.0)), Ok((10.0, 1.5)));
        assert!(choose_size(&Size::Diameter(9.0), Pitch::Iso, &shaft(8.0)).is_err());
    }

    #[test]
    fn geometry_matches_the_python_generator() {
        // sc_live.thread_geometry(8, 1, 0.15, False, 0.85)
        let g = geometry(8.0, 1.0, 0.15, false, 0.85);
        assert_eq!(g.designation, "M7.85x1");
        assert!((g.surface.unwrap() - (7.85 - 2.0 * 0.15 * ISO_HEIGHT)).abs() < 1e-12);
        assert!((g.tooth - 0.85 * ISO_HEIGHT).abs() < 1e-12);
        // a hole: wider by the offset, its surface opened up to leave 85% teeth
        let g = geometry(8.0, 1.0, 0.15, true, 0.85);
        assert_eq!(g.designation, "M8.15x1");
        let h0 = ISO_HEIGHT;
        assert!((g.surface.unwrap() - (8.15 - 2.0 * h0 + 2.0 * 0.15 * h0)).abs() < 1e-12);
        // at full height a shaft still goes to the looser diameter; a hole is left alone
        assert_eq!(geometry(8.0, 1.0, 0.2, false, 1.0).surface, Some(7.8));
        assert_eq!(geometry(8.0, 1.0, 0.2, true, 1.0).surface, None);
    }

    #[test]
    fn opens_only_holes_too_narrow_for_the_teeth() {
        let minor = 8.2 - 2.0 * ISO_HEIGHT;
        assert_eq!(open_narrow_hole(true, 6.8, 8.0, 1.0, 0.2), Some(minor));
        assert_eq!(open_narrow_hole(true, 7.2, 8.0, 1.0, 0.2), None);
        assert_eq!(open_narrow_hole(true, 8.0, 8.0, 1.0, 0.2), None);
        assert_eq!(open_narrow_hole(false, 6.8, 8.0, 1.0, 0.2), None);
    }

    #[test]
    fn names() {
        assert_eq!(label(false, 8.0, 1.0, 0.15, 0.85), "External M8x1 O.15 85%");
        assert_eq!(label(true, 10.0, 1.5, 0.0, 1.0), "Internal M10x1.5 O.0");
        let taken = vec!["A".to_string(), "A (2)".to_string()];
        assert_eq!(unique_name("A", &taken), "A (3)");
        assert_eq!(unique_name("B", &taken), "B");
    }

    #[test]
    fn moves_points_radially() {
        let p = point_at_radius([4.0, 0.0, 10.0], [0.0, 0.0, 0.0], [0.0, 0.0, 2.0], 3.5);
        assert!((p[0] - 3.5).abs() < 1e-12 && p[1].abs() < 1e-12 && (p[2] - 10.0).abs() < 1e-12);
    }

    #[test]
    fn starts_from_the_nearer_end_only_for_a_middle_pick() {
        let span = Span { origin: [40.0, 0.0, 0.0], axis: [0.0, 1.0, 0.0], start: -20.0, end: 0.0 };
        // near an end: SolidCraft decides
        assert_eq!(start_from(&span, [44.0, -2.0, 0.0]), None);
        assert_eq!(start_from(&span, [44.0, -18.0, 0.0]), None);
        // in the middle: the nearer end, on the face
        assert_eq!(start_from(&span, [44.0, -9.0, 0.0]), Some([44.0, 0.0, 0.0]));
        assert_eq!(start_from(&span, [44.0, -11.0, 0.0]), Some([44.0, -20.0, 0.0]));
    }

    #[test]
    fn hints_for_holes_only() {
        assert_eq!(drill_hint(&shaft(8.0), 8.0, 1.0), None);
        assert_eq!(drill_hint(&hole(7.0), 8.0, 1.0), None);
        assert!(drill_hint(&hole(6.0), 8.0, 1.0).unwrap().contains("Ø7 mm"));
        assert!(drill_hint(&hole(7.6), 8.0, 1.0).unwrap().contains("shallow"));
        // a hole at the nominal size: SolidCraft narrows it
        assert_eq!(drill_hint(&hole(14.0), 14.0, 1.0), None);
    }
}
