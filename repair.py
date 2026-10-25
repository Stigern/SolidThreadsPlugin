"""Checks 3MF meshes and repairs them with Windows' 3D printing repair.

Windows' repair (Windows.Graphics.Printing3D, the one 3D Builder and the
slicers' "fix model" use) is reached through winrepair.ps1 in Windows
PowerShell 5.1, which every Windows 10/11 has. Pure standard library.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def here() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def read_3mf(path: str) -> list[tuple[list, list]]:
    """[(vertices, triangles)] for each mesh object in a 3MF file."""
    meshes = []
    with zipfile.ZipFile(path) as z:
        models = [n for n in z.namelist() if n.lower().endswith(".model")]
        for name in models:
            root = ET.fromstring(z.read(name))
            for mesh in root.iter(NS + "mesh"):
                vs = [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
                      for v in mesh.iter(NS + "vertex")]
                ts = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3")))
                      for t in mesh.iter(NS + "triangle")]
                meshes.append((vs, ts))
    return meshes


def check_mesh(vertices, triangles, tol=1e-5) -> dict:
    """Counts what slicers complain about: degenerate triangles, open edges
    (holes), edges shared by more than two triangles, and triangles facing
    the wrong way compared with their neighbours."""
    key = lambda p: tuple(round(c / tol) for c in p)
    ids, remap = {}, []
    for p in vertices:
        remap.append(ids.setdefault(key(p), len(ids)))
    faces = [(remap[a], remap[b], remap[c]) for a, b, c in triangles]
    degenerate = sum(1 for a, b, c in faces if a == b or b == c or a == c)
    directed = collections.Counter()
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            if u != v:
                directed[(u, v)] += 1
    undirected = collections.Counter()
    for (u, v), n in directed.items():
        undirected[(min(u, v), max(u, v))] += n
    open_edges = sum(1 for n in undirected.values() if n == 1)
    non_manifold = sum(1 for n in undirected.values() if n > 2)
    flipped = sum(1 for (u, v), n in directed.items() if n > 1 and undirected[(min(u, v), max(u, v))] == 2)
    return {"triangles": len(faces), "degenerate": degenerate, "open_edges": open_edges,
            "non_manifold_edges": non_manifold, "flipped_edges": flipped}


def check_3mf(path: str) -> dict:
    total = collections.Counter()
    meshes = read_3mf(path)
    for vs, ts in meshes:
        total.update(check_mesh(vs, ts))
    out = dict(total)
    out["meshes"] = len(meshes)
    out["problems"] = sum(out.get(k, 0) for k in
                          ("degenerate", "open_edges", "non_manifold_edges", "flipped_edges"))
    return out


def windows_repair(src: str, dst: str, timeout: float = 600) -> dict:
    """Repair `src` (3MF) into `dst` (3MF) with Windows' repair."""
    if sys.platform != "win32":
        raise RuntimeError("Windows' model repair is only on Windows.")
    script = os.path.join(here(), "winrepair.ps1")
    ps = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                      r"System32\WindowsPowerShell\v1.0\powershell.exe")
    res = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", script, "-In", src, "-Out", dst],
                         capture_output=True, text=True, timeout=timeout,
                         creationflags=0x08000000)  # no console window
    line = next((l for l in reversed(res.stdout.splitlines()) if l.startswith("{")), None)
    if res.returncode != 0 or not line or not os.path.isfile(dst):
        err = (res.stderr or res.stdout).strip().splitlines()
        raise RuntimeError("Windows repair failed: " + (err[0] if err else "no output"))
    return json.loads(line)


def repair_file(src: str, dst: str) -> dict:
    """Repair a 3MF and report the problems found before and after."""
    before = check_3mf(src)
    info = windows_repair(src, dst)
    after = check_3mf(dst)
    return {"before": before, "after": after, "windows": info, "path": dst}
