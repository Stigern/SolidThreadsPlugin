"""Talks to a running SolidCraft through its local control channel.

SolidCraft (0.22+) listens on 127.0.0.1 and writes the port and a token to
%LOCALAPPDATA%\\SolidCraft\\control (docs/control-protocol.md). Requests are one
JSON line each: {"id", "method", "params", "token"?}; replies are one line.
"""

from __future__ import annotations

import json
import os
import socket
import sys


def control_dir() -> str | None:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return os.path.join(base, "SolidCraft", "control") if base else None
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/SolidCraft/control")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "solidcraft", "control")


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def candidate_ports() -> list[int]:
    """Ports of SolidCraft windows that have a token file, the current one first."""
    d = control_dir()
    if not d or not os.path.isdir(d):
        return []
    ports = []
    current = _read(os.path.join(d, "current.port"))
    if current and current.isdigit():
        ports.append(int(current))
    tokens = [f for f in os.listdir(d) if f.endswith(".token") and f[:-6].isdigit()]
    tokens.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
    for f in tokens:
        p = int(f[:-6])
        if p not in ports:
            ports.append(p)
    return ports


class NotRunning(RuntimeError):
    pass


class Client:
    def __init__(self, port: int | None = None, token: str | None = None, timeout: float = 120):
        self.sock = None
        errors = []
        ports = [port] if port else candidate_ports()
        for p in ports:
            tok = token or os.environ.get("SOLIDCRAFT_CONTROL_TOKEN") or \
                _read(os.path.join(control_dir() or "", f"{p}.token"))
            if not tok:
                continue
            try:
                self.sock = socket.create_connection(("127.0.0.1", p), timeout=3)
            except OSError as e:
                errors.append(f"{p}: {e}")
                continue
            self.sock.settimeout(timeout)
            self.file = self.sock.makefile("r", encoding="utf-8")
            self.port, self.token, self.n, self.authed = p, tok, 0, False
            try:
                self.call("ui.inspect")
                break
            except RuntimeError as e:
                errors.append(f"{p}: {e}")
                self.close()
        if not self.sock:
            raise NotRunning("SolidCraft is not running (or its control channel is closed). "
                             "Open SolidCraft and try again.")

    def call(self, method: str, params: dict | None = None):
        self.n += 1
        req = {"id": self.n, "method": method, "params": params or {}}
        if not self.authed:
            req["token"] = self.token
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        line = self.file.readline()
        if not line:
            raise RuntimeError("SolidCraft closed the connection")
        rep = json.loads(line)
        if not rep.get("ok"):
            raise RuntimeError(rep.get("error") or "request failed")
        self.authed = True
        return rep.get("result")

    def execute(self, command: str, params: dict | None = None):
        return self.call("engine.execute", {"command": command, "params": params or {}})

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------
# Threads on the selected face
# --------------------------------------------------------------------------

def selected_face(c: Client) -> dict:
    """The face selected in SolidCraft: {body, index, point}."""
    sel = c.call("ui.selection") or {}
    faces = [s for s in sel.get("selection") or [] if s.get("type") == "face"]
    if not faces:
        raise RuntimeError("Select a cylindrical face (a shaft or the inside of a hole) "
                           "in SolidCraft first.")
    f = faces[0]
    return {"body": f.get("body"), "index": f.get("index"), "point": f["point"]}


def probe_face(c: Client, face: dict) -> dict:
    """Ask SolidCraft what thread fits the face, leaving the design untouched.

    Adds a cosmetic thread inside a checkpoint and goes back to it, undo history
    included. Returns SolidCraft's thread info: internal, designation,
    major_diameter, pitch, start, end, body."""
    cp = c.execute("edit.checkpoint")["checkpoint"]
    try:
        res = c.execute("solid.thread", {"face": face["point"]})
    except RuntimeError as e:
        raise RuntimeError(f"That face can't take a thread: {e}") from None
    finally:
        c.execute("edit.restore_checkpoint", {"checkpoint": cp})
        # going back clears the selection: select the face again
        if face.get("body") is not None and face.get("index") is not None:
            try:
                c.execute("select.set", {"items": [{"type": "face", "body": face["body"],
                                                    "index": face["index"], "point": face["point"]}]})
            except RuntimeError:
                pass
    info = (res or {}).get("thread")
    if not info:
        raise RuntimeError("SolidCraft found no thread size for that face.")
    info["face_diameter"] = face_diameter(c, face)
    return info


def face_diameter(c: Client, face: dict) -> float | None:
    """The diameter of the selected cylindrical face, or None if it can't be read."""
    if face.get("body") is None or face.get("index") is None:
        return None
    try:
        faces = c.execute("model.faces", {"body": face["body"]})["faces"]
    except (RuntimeError, KeyError, TypeError):
        return None
    for f in faces:
        if f.get("index") == face["index"] and f.get("cylinder"):
            return 2 * f["cylinder"]["radius"]
    return None


def designation(diameter: float, pitch: float) -> str:
    return f"M{round(diameter, 3):g}x{round(pitch, 4):g}"


def tolerance_class(offset: float) -> str:
    """CustomThreads' name for a diameter offset: 0.2 -> "O.2"."""
    return f"O.{round(offset * 10, 2):g}" if offset < 1 else f"O+{offset:g}"


# The ISO basic thread height (5H/8, radial) as a fraction of the pitch. SolidCraft
# cuts an external thread's root this deep below its major diameter; an internal
# thread's teeth reach in as far as the hole lets them.
ISO_HEIGHT = 0.54127


def thread_geometry(diameter: float, pitch: float, offset: float, internal: bool,
                    height: float = 1.0) -> dict:
    """The diameters a thread is cut at.

    `designation`: what SolidCraft cuts (the nominal diameter, `offset` looser).
    `surface`: the diameter the shaft or hole is set to first so the teeth come out
    `height` (0-1] of the full ISO height, or None to leave the face as it is.
    A lower thread flattens the tops of the teeth only, on both parts, so the
    flanks stay where a full thread has them and a bolt and nut of the same
    height still fit; they engage over less depth."""
    h0 = ISO_HEIGHT * pitch
    trim = (1.0 - height) * h0
    if internal:
        d = diameter + offset
        surface = d - 2 * h0 + 2 * trim if height < 1.0 else None  # the hole
    else:
        d = diameter - offset
        surface = d - 2 * trim if height < 1.0 else None  # the shaft
    return {"designation": designation(d, pitch), "surface": surface,
            "tooth": height * h0}


def _point_at_radius(info: dict, point, radius: float):
    """The selected point moved radially (from the thread axis) to `radius`."""
    a = info["axis"]
    o = info["axis_point"]
    n = sum(x * x for x in a) ** 0.5 or 1.0
    a = [x / n for x in a]
    v = [p - q for p, q in zip(point, o)]
    along = sum(x * y for x, y in zip(v, a))
    foot = [q + along * x for q, x in zip(o, a)]
    r = [p - f for p, f in zip(point, foot)]
    rn = sum(x * x for x in r) ** 0.5 or 1.0
    return [f + radius * x / rn for f, x in zip(foot, r)]


def _unique_name(c: Client, base: str) -> str:
    try:
        taken = {t.get("name") for t in c.call("document.inspect").get("timeline") or []}
    except RuntimeError:
        taken = set()
    label, k = base, 2
    while label in taken:
        label = f"{base} ({k})"
        k += 1
    return label


def add_thread(c: Client, face: dict, diameter: float, pitch: float, offset: float,
               internal: bool, length: float | None = None, height: float = 1.0,
               info: dict | None = None, modeled: bool = True) -> dict:
    """Cut a thread into the face, looser by `offset` mm on the diameter.

    As in CustomThreads' tolerance classes (O.0, O.1, O.2, O.4, O.8): an external
    thread's major, pitch and minor diameters get `offset` smaller, an internal
    thread's `offset` larger; the pitch stays. With `height` below 1 the face is
    first offset (a shaft thinner, a hole wider, see thread_geometry) so the
    teeth come out lower with flat tops. `info` is probe_face's result for the
    face. Each step is undoable in SolidCraft; the steps are named and, when
    there are two, grouped in the timeline."""
    geo = thread_geometry(diameter, pitch, offset, internal, height)
    point = face["point"]
    nominal = f"M{diameter:g}x{pitch:g}"
    kind = "Internal" if internal else "External"
    tag = f"{kind} {nominal} {tolerance_class(offset)}" + \
        (f" {round(height * 100):g}%" if height < 1.0 else "")
    features = []
    if geo["surface"] is not None:
        if not info or not info.get("face_diameter") or not info.get("axis"):
            raise RuntimeError("Can't read the face's size, so a lower thread can't be made.")
        now = info["face_diameter"]
        # positive moves the face out of the material: a shaft thicker, a hole narrower
        dist = (geo["surface"] - now) / 2 * (-1 if internal else 1)
        if abs(dist) > 1e-4:
            res = c.execute("solid.offset_face", {"faces": [point], "distance": f"{dist:.4f} mm"})
            f = (res or {}).get("feature")
            if f is not None:
                features.append(f)
                try:
                    c.execute("timeline.rename", {"feature": f, "name": _unique_name(
                        c, f"{'Hole' if internal else 'Shaft'} Ø{geo['surface']:.3g} for {tag}")})
                except RuntimeError:
                    pass
            point = _point_at_radius(info, point, geo["surface"] / 2)
    params = {"face": point, "designation": geo["designation"], "modeled": modeled}
    if length:
        params["length"] = f"{length:g} mm"
    res = c.execute("solid.thread", params)
    label = tag
    feature = (res or {}).get("feature")
    if feature is not None:
        features.append(feature)
        label = _unique_name(c, tag)
        try:
            c.execute("timeline.rename", {"feature": feature, "name": label})
        except RuntimeError:
            label = (res or {}).get("name") or label  # the thread is in; the name is a convenience
        if len(features) > 1:
            try:
                c.execute("timeline.group", {"name": _unique_name(c, f"Thread {label}"),
                                             "features": features})
            except RuntimeError:
                pass
    return {"feature": feature, "name": label, "designation": geo["designation"],
            "surface": geo["surface"], "tooth": geo["tooth"], "steps": len(features),
            "thread": (res or {}).get("thread")}
