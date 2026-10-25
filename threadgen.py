"""3D-printable thread generator for SolidCraft.

Builds bolts, threaded rods, nuts and thread cutters as watertight triangle
meshes (binary STL) and can hand them to SolidCraft. Pure standard library.

Geometry model: a thread is a "basic profile" r_b(z) over one pitch: the line
between bolt material and nut material at zero clearance. An external thread
is that region eroded by the clearance (a true normal offset, so the gap is
the same on the flanks as on crest and root); an internal thread is the
region dilated by it. A printed bolt and a printed nut therefore have a gap of
twice the clearance between them, and each still fits a nominal metal part.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict

__version__ = "1.7.0"

# SolidCraft plugin manifest (Preferences > Plugins). SolidCraft accepts exactly these four
# fields: id (must match the folder name), name, version and description (<= 240 chars).
PLUGIN_ID = "thread-generator"
PLUGIN_NAME = "Thread Generator"
PLUGIN_DESCRIPTION = "Cut threads with print clearance into a selected face, or make bolts, nuts and rods as STL."

# --------------------------------------------------------------------------
# Standard sizes
# --------------------------------------------------------------------------

# name -> (major diameter mm, pitch mm)
ISO_COARSE = {
    "M1": (1.0, 0.25), "M1.2": (1.2, 0.25), "M1.4": (1.4, 0.3), "M1.6": (1.6, 0.35),
    "M2": (2.0, 0.4), "M2.5": (2.5, 0.45), "M3": (3.0, 0.5), "M4": (4.0, 0.7),
    "M5": (5.0, 0.8), "M6": (6.0, 1.0), "M8": (8.0, 1.25), "M10": (10.0, 1.5),
    "M12": (12.0, 1.75), "M14": (14.0, 2.0), "M16": (16.0, 2.0),
    "M20": (20.0, 2.5), "M24": (24.0, 3.0), "M30": (30.0, 3.5),
    "M36": (36.0, 4.0), "M42": (42.0, 4.5), "M48": (48.0, 5.0),
}
ISO_FINE = {
    "M8x1": (8.0, 1.0), "M10x1": (10.0, 1.0), "M10x1.25": (10.0, 1.25),
    "M12x1.25": (12.0, 1.25), "M12x1.5": (12.0, 1.5), "M14x1.5": (14.0, 1.5),
    "M16x1.5": (16.0, 1.5), "M20x1.5": (20.0, 1.5), "M24x2": (24.0, 2.0),
    "M30x2": (30.0, 2.0), "M36x3": (36.0, 3.0),
}
UNC = {  # diameter in mm, pitch = 25.4 / TPI
    "#4-40": (2.845, 25.4 / 40), "#6-32": (3.505, 25.4 / 32),
    "#8-32": (4.166, 25.4 / 32), "#10-24": (4.826, 25.4 / 24),
    "1/4-20": (6.35, 25.4 / 20), "5/16-18": (7.938, 25.4 / 18),
    "3/8-16": (9.525, 25.4 / 16), "1/2-13": (12.7, 25.4 / 13),
    "5/8-11": (15.875, 25.4 / 11), "3/4-10": (19.05, 25.4 / 10),
    "1-8": (25.4, 25.4 / 8),
}
TRAPEZOIDAL = {
    "Tr8x1.5": (8.0, 1.5), "Tr8x2": (8.0, 2.0), "Tr10x2": (10.0, 2.0),
    "Tr12x3": (12.0, 3.0), "Tr16x4": (16.0, 4.0), "Tr20x4": (20.0, 4.0),
    "Tr24x5": (24.0, 5.0), "Tr30x6": (30.0, 6.0), "Tr40x7": (40.0, 7.0),
}
# Coarse threads that suit printed jars, lids and containers.
PRINT_FRIENDLY = {
    "Jar 40x4": (40.0, 4.0), "Jar 50x4": (50.0, 4.0), "Jar 60x5": (60.0, 5.0),
    "Jar 80x5": (80.0, 5.0), "Jar 100x6": (100.0, 6.0),
}

# Coarse 60° metric threads for FDM printing, after CustomThreads
# (github.com/BalzGuenat/CustomThreads, MIT): ISO profile, 3.5 or 5 mm pitch at
# any diameter, so the thread is deep enough to survive 0.2-0.3 mm layers.
# A 2.5 mm pitch is added for smaller parts (from M6), where 3.5 is very coarse,
# and an experimental 2 mm pitch from M4 (on M4-M5 the core is thin: about half
# the diameter).
PRINTED_PITCHES = (2.0, 2.5, 3.5, 5.0)
_PRINTED_FROM = {2.0: 4, 2.5: 6, 3.5: 8, 5.0: 8}  # smallest diameter per pitch
PRINTED_METRIC = {f"M{d}x{p:g}": (float(d), p) for d in range(4, 51)
                  for p in PRINTED_PITCHES if d >= _PRINTED_FROM[p]}
PRINTED = "3D-printed metric (2/2.5/3.5/5 mm pitch)"


def printed_pitch(diameter: float) -> float:
    """The suggested printed pitch for a diameter: 2 below M6 (experimental),
    2.5 up to M16, 3.5 up to M30, then 5."""
    return 2.0 if diameter < 6 else 2.5 if diameter <= 16 else 3.5 if diameter <= 30 else 5.0

STANDARDS = {
    PRINTED: (PRINTED_METRIC, "iso"),
    "ISO metric coarse": (ISO_COARSE, "iso"),
    "ISO metric fine": (ISO_FINE, "iso"),
    "UNC (inch)": (UNC, "iso"),
    "Trapezoidal (Tr)": (TRAPEZOIDAL, "trapezoidal"),
    "Large / jar (printable)": (PRINT_FRIENDLY, "trapezoidal"),
}

# profile -> (lower flank half-angle, upper flank half-angle, depth as a
# fraction of pitch, crest share of the flats)
PROFILES = {
    "iso": (30.0, 30.0, 0.54127, 1 / 3),          # 60 deg V, ISO 68-1 basic
    "trapezoidal": (15.0, 15.0, 0.5, 0.5),        # 30 deg, ISO 2904
    "acme": (14.5, 14.5, 0.5, 0.5),               # 29 deg
    "square": (2.0, 2.0, 0.5, 0.5),               # near-square, prints cleanly
    "buttress": (45.0, 7.0, 0.6, 0.35),           # load on the 7 deg flank
}
PROFILE_LABELS = {
    "iso": "60° V (ISO / UNC)",
    "trapezoidal": "30° trapezoidal",
    "acme": "29° ACME",
    "square": "Square",
    "buttress": "Buttress 45°/7°",
}

QUALITY = {  # (target edge length around the circumference mm, rows per pitch)
    "draft": (0.6, 12),
    "normal": (0.3, 24),
    "fine": (0.15, 40),
}


def iso_hex_across_flats(d: float) -> float:
    """Approximate ISO 4032 / 4014 across-flats width for diameter d."""
    table = {2: 4, 2.5: 5, 3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18,
             14: 21, 16: 24, 20: 30, 24: 36, 30: 46, 36: 55, 42: 65, 48: 75}
    if d in table:
        return float(table[d])
    return round(1.5 * d + 1.0, 1)


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

PART_TYPES = ("bolt", "rod", "nut", "pair", "cutter")
PART_LABELS = {
    "bolt": "Bolt (hex head)",
    "rod": "Threaded rod",
    "nut": "Nut",
    "pair": "Bolt + matching nut",
    "cutter": "Thread cutter (negative part in slicer)",
}


@dataclass
class ThreadSpec:
    part: str = "bolt"
    diameter: float = 10.0          # nominal major diameter, mm
    pitch: float = 1.5              # axial distance between thread crests, mm
    profile: str = "iso"
    starts: int = 1                 # multi-start threads advance starts*pitch per turn
    left_hand: bool = False
    depth: float | None = None      # thread depth mm; None = standard for profile
    clearance: float = 0.15         # per part, mm, normal to the surface
    length: float = 20.0            # threaded length (bolt/rod/cutter), mm
    shank: float = 0.0              # unthreaded length under a bolt head, mm
    head_height: float | None = None
    head_flats: float | None = None
    head_shape: str = "hex"         # hex | round | square
    nut_height: float | None = None
    nut_flats: float | None = None
    nut_shape: str = "hex"          # hex | round | square
    chamfer: float | None = None    # lead-in chamfer, mm (radial)
    quality: str = "normal"
    name: str = ""
    size: str = ""                  # standard size name, used in file names

    # derived ---------------------------------------------------------------
    def resolved(self) -> "ThreadSpec":
        s = ThreadSpec(**asdict(self))
        if s.part not in PART_TYPES:
            raise ValueError(f"unknown part {s.part!r}")
        if s.profile not in PROFILES:
            raise ValueError(f"unknown profile {s.profile!r}")
        if s.diameter <= 0 or s.pitch <= 0:
            raise ValueError("diameter and pitch must be positive")
        if s.starts < 1:
            raise ValueError("starts must be at least 1")
        if s.depth is None:
            s.depth = PROFILES[s.profile][2] * s.pitch
        if s.depth <= 0 or s.depth >= s.diameter / 2:
            raise ValueError("thread depth must be between 0 and the radius")
        if s.clearance < 0 or s.clearance > s.pitch / 3:
            raise ValueError(f"clearance must be between 0 and {s.pitch / 3:.2f} mm (a third of the pitch)")
        if s.chamfer is None:
            s.chamfer = min(s.depth, s.diameter * 0.08 + 0.2)
        if s.head_flats is None:
            s.head_flats = iso_hex_across_flats(s.diameter)
        if s.head_height is None:
            s.head_height = round(0.64 * s.diameter + 0.3, 2)
        if s.nut_flats is None:
            s.nut_flats = iso_hex_across_flats(s.diameter)
        if s.nut_height is None:
            s.nut_height = round(0.8 * s.diameter + 0.5, 2)
        if s.head_flats <= s.diameter or s.nut_flats <= s.diameter:
            raise ValueError("head and nut must be wider than the thread")
        if s.length <= 0:
            raise ValueError("length must be positive")
        if s.quality not in QUALITY:
            raise ValueError(f"quality must be one of {', '.join(QUALITY)}")
        return s

    def label(self) -> str:
        if self.name:
            return self.name
        d = f"{self.diameter:g}"
        p = f"{self.pitch:g}"
        hand = "LH" if self.left_hand else ""
        st = f"_{self.starts}start" if self.starts > 1 else ""
        base = {"bolt": "bolt", "rod": "rod", "nut": "nut", "pair": "pair",
                "cutter": "cutter"}[self.part]
        if self.size:
            size = self.size.replace("/", "-").replace("#", "No").replace(" ", "")
        else:
            size = f"M{d}x{p}" if self.profile == "iso" else f"{self.profile}{d}x{p}"
        extra = f"x{self.length:g}" if self.part in ("bolt", "rod", "cutter", "pair") else ""
        return f"{base}_{size}{extra}{hand}{st}_c{self.clearance:g}"


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

class Profile:
    """Periodic radius table r(u), u in [0, 1) of one pitch, for one side."""

    SAMPLES = 1536

    def __init__(self, spec: ThreadSpec, side: str):
        a1, a2, _, crest_share = PROFILES[spec.profile]
        P, h = spec.pitch, spec.depth
        R = spec.diameter / 2
        f1 = h * math.tan(math.radians(a1))
        f2 = h * math.tan(math.radians(a2))
        flats = P - f1 - f2
        if flats <= 0:
            raise ValueError("thread too deep for this pitch and profile")
        crest = flats * crest_share
        root = flats - crest
        # one period, starting in the middle of the root
        zs = [0, root / 2, root / 2 + f1, root / 2 + f1 + crest,
              root / 2 + f1 + crest + f2, P]
        rs = [R - h, R - h, R, R, R - h, R - h]
        self.P, self.R, self.h = P, R, h

        n = self.SAMPLES
        basic = [self._interp(zs, rs, i * P / n) for i in range(n)]
        c = spec.clearance
        if c <= 1e-9:
            table = basic
        else:
            # morphological erosion (external) / dilation (internal) by a disc
            # of radius c in the (z, r) plane: a true normal offset
            k = max(1, int(math.ceil(c / (P / n))))
            offs = []
            for j in range(-k, k + 1):
                dz = j * P / n
                if abs(dz) <= c:
                    offs.append((j, math.sqrt(c * c - dz * dz)))
            table = []
            if side == "external":
                for i in range(n):
                    table.append(min(basic[(i + j) % n] - s for j, s in offs))
            else:
                for i in range(n):
                    table.append(max(basic[(i + j) % n] + s for j, s in offs))
        self.table = table
        self.r_max = max(table)
        self.r_min = min(table)

    @staticmethod
    def _interp(zs, rs, z):
        for i in range(len(zs) - 1):
            if zs[i] <= z <= zs[i + 1]:
                if zs[i + 1] == zs[i]:
                    return rs[i + 1]
                t = (z - zs[i]) / (zs[i + 1] - zs[i])
                return rs[i] + t * (rs[i + 1] - rs[i])
        return rs[-1]

    def at(self, u: float) -> float:
        n = self.SAMPLES
        x = (u % 1.0) * n
        i = int(x)
        t = x - i
        a = self.table[i % n]
        b = self.table[(i + 1) % n]
        return a + t * (b - a)


# --------------------------------------------------------------------------
# Mesh building
# --------------------------------------------------------------------------

class Mesh:
    def __init__(self):
        self.v: list[tuple[float, float, float]] = []
        self.f: list[tuple[int, int, int]] = []

    def add(self, x, y, z) -> int:
        self.v.append((x, y, z))
        return len(self.v) - 1

    def tri(self, a, b, c):
        if a != b and b != c and a != c:
            self.f.append((a, b, c))

    def quad(self, a, b, c, d):
        """a-b-c-d counter-clockwise seen from outside."""
        self.tri(a, b, c)
        self.tri(a, c, d)

    def merge(self, other: "Mesh", dx=0.0, dy=0.0, dz=0.0):
        base = len(self.v)
        self.v.extend((x + dx, y + dy, z + dz) for x, y, z in other.v)
        self.f.extend((a + base, b + base, c + base) for a, b, c in other.f)

    def check_closed(self) -> tuple[bool, str]:
        edges: dict[tuple[int, int], int] = {}
        for a, b, c in self.f:
            for e in ((a, b), (b, c), (c, a)):
                edges[e] = edges.get(e, 0) + 1
        bad = 0
        for (a, b), n in edges.items():
            if n != 1 or edges.get((b, a), 0) != 1:
                bad += 1
        if bad:
            return False, f"{bad} open or non-manifold edges"
        return True, "watertight"

    def volume(self) -> float:
        vol = 0.0
        v = self.v
        for a, b, c in self.f:
            ax, ay, az = v[a]
            bx, by, bz = v[b]
            cx, cy, cz = v[c]
            vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
                    + az * (bx * cy - by * cx))
        return vol / 6.0

    def bbox(self):
        xs = [p[0] for p in self.v]
        ys = [p[1] for p in self.v]
        zs = [p[2] for p in self.v]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def write_stl(self, path: str, name: str = "thread"):
        v = self.v
        with open(path, "wb") as fh:
            header = f"SolidCraft thread generator: {name}".encode()[:80]
            fh.write(header.ljust(80, b" "))
            fh.write(struct.pack("<I", len(self.f)))
            pack = struct.Struct("<12fH").pack
            for a, b, c in self.f:
                ax, ay, az = v[a]
                bx, by, bz = v[b]
                cx, cy, cz = v[c]
                ux, uy, uz = bx - ax, by - ay, bz - az
                wx, wy, wz = cx - ax, cy - ay, cz - az
                nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
                ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                fh.write(pack(nx / ln, ny / ln, nz / ln, ax, ay, az,
                              bx, by, bz, cx, cy, cz, 0))


def _segments(spec: ThreadSpec, radius: float) -> int:
    edge, _ = QUALITY[spec.quality]
    n = int(math.ceil(2 * math.pi * radius / edge))
    n = max(48, min(n, 720))
    return int(math.ceil(n / 12.0) * 12)  # multiple of 12: hex/square corners land on samples


def _polygon_radius(shape: str, size: float, theta: float) -> float:
    """Distance from the centre to the outline at angle theta.

    size is the across-flats width (hex, square) or the diameter (round)."""
    if shape == "round":
        return size / 2
    sides = 6 if shape == "hex" else 4
    seg = 2 * math.pi / sides
    # corners at theta = k*seg, flat centres in between
    local = (theta % seg) - seg / 2
    return (size / 2) / math.cos(local)


class _ThreadSurface:
    """r(theta, z) of a threaded cylinder, with optional end envelopes."""

    def __init__(self, spec: ThreadSpec, prof: Profile):
        self.spec = spec
        self.prof = prof
        self.lead = spec.pitch * spec.starts
        self.sign = -1.0 if spec.left_hand else 1.0

    def r(self, theta: float, z: float) -> float:
        # u is the position within one pitch measured along the helix
        u = (z - self.sign * self.lead * theta / (2 * math.pi)) / self.spec.pitch
        return self.prof.at(u)


def _z_rows(z0: float, z1: float, pitch: float, rows_per_pitch: int, extra=()):
    n = max(2, int(math.ceil((z1 - z0) / pitch * rows_per_pitch)))
    zs = {round(z0 + (z1 - z0) * i / n, 9) for i in range(n + 1)}
    for z in extra:
        if z0 < z < z1:
            zs.add(round(z, 9))
    return sorted(zs)


def _ring(mesh: Mesh, thetas, z, radii):
    return [mesh.add(r * math.cos(t), r * math.sin(t), z) for t, r in zip(thetas, radii)]


def _strip(mesh: Mesh, lower, upper, outward: bool):
    """Join two closed rings of equal length; lower is below upper."""
    n = len(lower)
    for j in range(n):
        a, b = lower[j], lower[(j + 1) % n]
        c, d = upper[(j + 1) % n], upper[j]
        if outward:
            mesh.quad(a, b, c, d)
        else:
            mesh.quad(a, d, c, b)


def _fan(mesh: Mesh, ring, z, up: bool):
    centre = mesh.add(0.0, 0.0, z)
    n = len(ring)
    for j in range(n):
        if up:
            mesh.tri(centre, ring[j], ring[(j + 1) % n])
        else:
            mesh.tri(centre, ring[(j + 1) % n], ring[j])


def _annulus(mesh: Mesh, inner, outer, up: bool):
    n = len(inner)
    for j in range(n):
        i0, i1 = inner[j], inner[(j + 1) % n]
        o0, o1 = outer[j], outer[(j + 1) % n]
        if up:
            mesh.quad(i0, o0, o1, i1)
        else:
            mesh.quad(i0, i1, o1, o0)


def build_external(spec: ThreadSpec, head: bool, chamfer_bottom: bool,
                   chamfer_top: bool, side: str = "external") -> Mesh:
    """A threaded shaft from z=0 to z=length, optionally with a head below z=0."""
    prof = Profile(spec, side)
    surf = _ThreadSurface(spec, prof)
    edge, rpp = QUALITY[spec.quality]
    n = _segments(spec, spec.diameter / 2)
    thetas = [2 * math.pi * j / n for j in range(n)]
    L = spec.length
    shank = min(spec.shank, L) if head else 0.0
    ch = spec.chamfer
    r_out = prof.r_max
    r_core = prof.r_min

    def radius(t, z):
        if z < shank - 1e-9:
            return r_out
        r = surf.r(t, z)
        if chamfer_bottom and not head:
            r = min(r, r_out - ch + z)
        if chamfer_top:
            r = min(r, r_out - ch + (L - z))
        return max(r, min(r_core, 0.3 * r_out) * 0.5)

    zs = _z_rows(0.0, L, spec.pitch, rpp, extra=(shank,) if shank > 0 else ())
    mesh = Mesh()
    rings = [_ring(mesh, thetas, z, [radius(t, z) for t in thetas]) for z in zs]
    for lo, hi in zip(rings, rings[1:]):
        _strip(mesh, lo, hi, outward=True)
    _fan(mesh, rings[-1], L, up=True)

    if not head:
        _fan(mesh, rings[0], 0.0, up=False)
        return mesh

    # head: prism from z=-head_height to 0, joined to the shaft at z=0
    H = spec.head_height
    size = spec.head_flats
    shape = spec.head_shape
    outline = [_polygon_radius(shape, size, t) for t in thetas]
    top = _ring(mesh, thetas, 0.0, outline)
    hc = min(0.6, H * 0.15)  # small chamfer on the head's free face
    mid = _ring(mesh, thetas, -H + hc, outline)
    bot = _ring(mesh, thetas, -H, [max(r - hc, r * 0.8) for r in outline])
    _annulus(mesh, rings[0], top, up=True)
    _strip(mesh, mid, top, outward=True)
    _strip(mesh, bot, mid, outward=True)
    _fan(mesh, bot, -H, up=False)
    return mesh


def build_nut(spec: ThreadSpec) -> Mesh:
    prof = Profile(spec, "internal")
    surf = _ThreadSurface(spec, prof)
    edge, rpp = QUALITY[spec.quality]
    n = _segments(spec, spec.nut_flats / 2)
    thetas = [2 * math.pi * j / n for j in range(n)]
    H = spec.nut_height
    ch = spec.chamfer
    r_in = prof.r_max  # bore at the thread's major diameter
    outline = [_polygon_radius(spec.nut_shape, spec.nut_flats, t) for t in thetas]
    r_cap = min(outline) - 0.4
    if r_in + ch >= r_cap:
        raise ValueError("nut is too narrow for this thread: increase the nut width")

    def radius(t, z):
        r = surf.r(t, z)
        # countersunk lead-in on both faces
        r = max(r, r_in + ch - z, r_in + ch - (H - z))
        return min(r, r_cap)

    zs = _z_rows(0.0, H, spec.pitch, rpp)
    mesh = Mesh()
    bore = [_ring(mesh, thetas, z, [radius(t, z) for t in thetas]) for z in zs]
    for lo, hi in zip(bore, bore[1:]):
        _strip(mesh, lo, hi, outward=False)
    ob = _ring(mesh, thetas, 0.0, outline)
    ot = _ring(mesh, thetas, H, outline)
    _strip(mesh, ob, ot, outward=True)
    _annulus(mesh, bore[-1], ot, up=True)
    _annulus(mesh, bore[0], ob, up=False)
    return mesh


def build_cutter(spec: ThreadSpec) -> Mesh:
    """The empty space of an internal thread: subtract it to tap a hole."""
    s = ThreadSpec(**asdict(spec))
    return build_external(s, head=False, chamfer_bottom=False, chamfer_top=False,
                          side="internal")


def build(spec: ThreadSpec) -> list[tuple[str, Mesh]]:
    """Return [(label, mesh)] for the requested part(s)."""
    s = spec.resolved()
    if s.part == "bolt":
        return [(s.label(), build_external(s, head=True, chamfer_bottom=False, chamfer_top=True))]
    if s.part == "rod":
        return [(s.label(), build_external(s, head=False, chamfer_bottom=True, chamfer_top=True))]
    if s.part == "nut":
        return [(s.label(), build_nut(s))]
    if s.part == "cutter":
        return [(s.label(), build_cutter(s))]
    # pair: bolt standing on its head, nut beside it
    bolt = build_external(s, head=True, chamfer_bottom=False, chamfer_top=True)
    nut = build_nut(s)
    gap = max(s.head_flats, s.nut_flats) * 0.7 + 5
    bolt_label = ThreadSpec(**{**asdict(s), "part": "bolt"}).label()
    nut_label = ThreadSpec(**{**asdict(s), "part": "nut"}).label()
    moved = Mesh()
    moved.merge(bolt, dz=s.head_height)  # head on the build plate
    nut_m = Mesh()
    nut_m.merge(nut, dx=gap * 2)
    return [(bolt_label, moved), (nut_label, nut_m)]


# --------------------------------------------------------------------------
# SolidCraft integration
# --------------------------------------------------------------------------

def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SolidCraft Thread Generator", "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    data = load_settings()
    data.update(values)
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def documents_dir() -> str:
    """The user's Documents folder, following OneDrive redirection on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return docs if os.path.isdir(docs) else os.path.expanduser("~")


def plugin_manifest() -> dict:
    return {"id": PLUGIN_ID, "name": PLUGIN_NAME, "version": __version__,
            "description": PLUGIN_DESCRIPTION}


def solidcraft_plugins_dir() -> str | None:
    """SolidCraft's per-user plugins folder (Preferences > Plugins)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return os.path.join(base, "SolidCraft", "plugins") if base else None
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/SolidCraft/plugins")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "solidcraft", "plugins")


def plugin_folder() -> str | None:
    d = solidcraft_plugins_dir()
    return os.path.join(d, PLUGIN_ID) if d else None


def install_plugin(files: list[str]) -> str:
    """Copy files into SolidCraft's plugins folder with a plugin.json. Returns the folder."""
    dest = plugin_folder()
    if not dest:
        raise RuntimeError("SolidCraft's plugins folder could not be found")
    os.makedirs(dest, exist_ok=True)
    for f in files:
        target = os.path.join(dest, os.path.basename(f))
        if os.path.abspath(f) != os.path.abspath(target):
            shutil.copy2(f, target)
    with open(os.path.join(dest, "plugin.json"), "w", encoding="utf-8") as fh:
        json.dump(plugin_manifest(), fh, indent=2)
    return dest


def find_solidcraft() -> dict[str, str | None]:
    cands = []
    for d in (os.environ.get("SOLIDCRAFT_HOME"), load_settings().get("solidcraft_home")):
        if d:
            cands.append(d)
    for var in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands.append(os.path.join(base, "SolidCraft"))
            cands.append(os.path.join(base, "Programs", "SolidCraft"))
    for d in cands:
        cli = os.path.join(d, "solidcraft-cli.exe")
        gui = os.path.join(d, "solidcraft.exe")
        if os.path.isfile(cli):
            return {"cli": cli, "gui": gui if os.path.isfile(gui) else None}
    cli = shutil.which("solidcraft-cli")
    return {"cli": cli, "gui": shutil.which("solidcraft")}


def _run_cli(args: list[str], timeout=300) -> subprocess.CompletedProcess:
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=flags, encoding="utf-8", errors="replace")


def make_design(stl_paths: list[str], design_path: str) -> str:
    """Build a .solidcraft design holding the meshes. Returns the path."""
    sc = find_solidcraft()
    if not sc["cli"]:
        raise RuntimeError("SolidCraft not found: use 'Locate SolidCraft…' or set SOLIDCRAFT_HOME")
    cmds = [{"command": "file.insert_mesh",
             "params": {"path": os.path.abspath(p),
                        "name": os.path.splitext(os.path.basename(p))[0]}}
            for p in stl_paths]
    fd, script = tempfile.mkstemp(suffix=".json", prefix="threadgen_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"commands": cmds}, fh)
    try:
        res = _run_cli([sc["cli"], "run", script, "--save", design_path, "--quiet"])
    finally:
        os.unlink(script)
    if res.returncode != 0 or not os.path.isfile(design_path):
        raise RuntimeError((res.stderr or res.stdout).strip() or "solidcraft-cli failed")
    return design_path


def snapshot(design_path: str, png_path: str, width=480, height=400) -> str:
    sc = find_solidcraft()
    if not sc["cli"]:
        raise RuntimeError("solidcraft-cli.exe not found")
    res = _run_cli([sc["cli"], "snapshot", design_path, "--out", png_path,
                    "--width", str(width), "--height", str(height),
                    "--view", "iso", "--no-grid", "--no-axes"], timeout=120)
    if res.returncode != 0 or not os.path.isfile(png_path):
        raise RuntimeError((res.stderr or res.stdout).strip() or "snapshot failed")
    return png_path


def open_in_solidcraft(design_path: str):
    sc = find_solidcraft()
    if not sc["gui"]:
        raise RuntimeError("solidcraft.exe not found")
    subprocess.Popen([sc["gui"], design_path], close_fds=True)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def generate(spec: ThreadSpec, out_dir: str, design: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    parts = build(spec)
    files = []
    report = []
    for label, mesh in parts:
        ok, msg = mesh.check_closed()
        path = os.path.join(out_dir, label + ".stl")
        mesh.write_stl(path, label)
        files.append(path)
        lo, hi = mesh.bbox()
        report.append({"file": path, "triangles": len(mesh.f), "closed": ok,
                       "check": msg, "volume_mm3": round(mesh.volume(), 2),
                       "size_mm": [round(hi[i] - lo[i], 2) for i in range(3)]})
    result = {"spec": asdict(spec.resolved()), "parts": report}
    if design:
        name = parts[0][0] if len(parts) == 1 else spec.resolved().label()
        result["design"] = make_design(files, os.path.join(out_dir, name + ".solidcraft"))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=f"Generate 3D-printable threads for SolidCraft (v{__version__}).")
    ap.add_argument("part", nargs="?", choices=PART_TYPES, help="omit to open the window")
    ap.add_argument("--size", help="standard size, e.g. M8, M10x1, 1/4-20, Tr8x2")
    ap.add_argument("-d", "--diameter", type=float)
    ap.add_argument("-p", "--pitch", type=float)
    ap.add_argument("--profile", choices=list(PROFILES))
    ap.add_argument("--starts", type=int, default=1)
    ap.add_argument("--left", action="store_true", help="left-hand thread")
    ap.add_argument("--depth", type=float, help="thread depth mm (default: standard)")
    ap.add_argument("-c", "--clearance", type=float, default=0.15)
    ap.add_argument("-l", "--length", type=float, default=20.0)
    ap.add_argument("--shank", type=float, default=0.0)
    ap.add_argument("--head", choices=("hex", "round", "square"), default="hex")
    ap.add_argument("--head-height", type=float)
    ap.add_argument("--head-flats", type=float)
    ap.add_argument("--nut", choices=("hex", "round", "square"), default="hex")
    ap.add_argument("--nut-height", type=float)
    ap.add_argument("--nut-flats", type=float)
    ap.add_argument("--chamfer", type=float)
    ap.add_argument("-q", "--quality", choices=list(QUALITY), default="normal")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--name", default="")
    ap.add_argument("--design", action="store_true", help="also save a .solidcraft design")
    ap.add_argument("--open", action="store_true", help="open the design in SolidCraft")
    a = ap.parse_args(argv)

    if a.part is None:
        from threadgen_gui import run_gui
        run_gui()
        return 0

    d, p, prof = a.diameter, a.pitch, a.profile
    if a.size:
        for table, kind in STANDARDS.values():
            if a.size in table:
                d0, p0 = table[a.size]
                d = d if d is not None else d0
                p = p if p is not None else p0
                prof = prof or kind
                break
        else:
            ap.error(f"unknown size {a.size!r}")
    if d is None or p is None:
        ap.error("give --size, or both --diameter and --pitch")
    spec = ThreadSpec(part=a.part, diameter=d, pitch=p, profile=prof or "iso",
                      starts=a.starts, left_hand=a.left, depth=a.depth,
                      clearance=a.clearance, length=a.length, shank=a.shank,
                      head_shape=a.head, head_height=a.head_height,
                      head_flats=a.head_flats, nut_shape=a.nut,
                      nut_height=a.nut_height, nut_flats=a.nut_flats,
                      chamfer=a.chamfer, quality=a.quality, name=a.name,
                      size=a.size or "")
    try:
        res = generate(spec, a.out, design=a.design or a.open)
    except (ValueError, RuntimeError) as e:
        if sys.stderr:  # None in the windowed .exe
            print(f"error: {e}", file=sys.stderr)
        return 1
    if sys.stdout:
        print(json.dumps(res, indent=2))
    if a.open:
        open_in_solidcraft(res["design"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
