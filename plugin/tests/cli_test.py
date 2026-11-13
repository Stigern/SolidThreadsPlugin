#!/usr/bin/env python3
"""End to end test: runs the built plugin through solidcraft-cli on real shafts and holes.

    python tests/cli_test.py [package-dir]

The package dir holds plugin.json and plugin.wasm (default: dist/thread-generator). Set
SOLIDCRAFT_CLI if solidcraft-cli (0.41 or newer) isn't on PATH or in C:\\Program Files\\SolidCraft.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "thread-generator"))
CLI = os.environ.get("SOLIDCRAFT_CLI") or shutil.which("solidcraft-cli") or r"C:\Program Files\SolidCraft\solidcraft-cli.exe"
TMP = tempfile.mkdtemp(prefix="threadgen-test-")
ISO_HEIGHT = 0.54127


def run(steps, save=None, inp=None, fail_ok=False):
    script = os.path.join(TMP, "s.json")
    out = os.path.join(TMP, "o.json")
    if os.path.exists(out):
        os.remove(out)
    with open(script, "w", encoding="utf-8") as fh:
        json.dump(steps, fh)
    cmd = [CLI, "run", script, "--results", "--quiet", "--json-out", out]
    if inp:
        cmd += ["--in", inp]
    if save:
        cmd += ["--save", save]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        if fail_ok:
            return None, p.stderr + p.stdout
        sys.exit("cli failed: " + p.stderr[-2000:] + p.stdout[-500:])
    with open(out, encoding="utf-8") as fh:
        res = json.load(fh)
    return [r.get("result", r) if isinstance(r, dict) else r for r in res], ""


APPROVAL = run([{"command": "plugin.inspect", "params": {"path": PKG}}])[0][0]["approval"]


def thread(params):
    return {"command": "plugin.run", "params": {"path": PKG, "approval": APPROVAL, "entry": "add-thread", "params": params}}


def select(body, point):
    return {"command": "select.set", "params": {"items": [{"type": "face", "body": body, "point": point}]}}


failed = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failed.append(name)


SHAFT = [{"command": "solid.cylinder", "params": {"diameter": 8, "height": 20, "operation": "new", "body_name": "Shaft"}}]
HOLE = [
    {"command": "solid.box", "params": {"length": 20, "width": 20, "height": 15, "center": [0, 0, 7.5], "operation": "new", "body_name": "Block"}},
    {"command": "solid.cylinder", "params": {"diameter": 7.2, "height": 15, "operation": "cut", "targets": ["Block"]}},
]
INSPECT = [
    {"command": "document.inspect", "params": {"timeline": "summary", "bodies": False}},
    {"command": "inspect.measure", "params": {}},
]


def case(label, setup, body, point, params, expect_name, expect_designation, expect_span=None, save=None):
    res, _ = run(setup + [select(body, point), thread(params)] + INSPECT, save=save)
    out = res[len(setup) + 1]
    timeline = res[-2]["timeline"]
    names = [f["name"] for f in timeline]
    measure = res[-1]["bodies"]
    check(f"{label}: named {expect_name!r}", out["name"] == expect_name and expect_name in names, f"{out['name']}, timeline {names}")
    check(f"{label}: cut as {expect_designation}", out["designation"] == expect_designation, out["designation"])
    check(f"{label}: every feature evaluates", not any(f.get("error") for f in timeline), str([f for f in timeline if f.get("error")]))
    check(f"{label}: one closed body", len(measure) == 1 and measure[0]["closed"])
    if expect_span is not None:
        bb = measure[0]["bbox"]
        span = bb["max"][0] - bb["min"][0]
        check(f"{label}: shaft spans Ø{expect_span:.3f}", abs(span - expect_span) < 0.02, f"{span:.4f}")
    return out, res


# A shaft: the defaults (Auto, 1 mm, O.15, 85%) make it thinner first, then thread it.
surface = 7.85 - 2 * 0.15 * ISO_HEIGHT
out, res = case("shaft Ø8 defaults", SHAFT, "Shaft", [4, 0, 10],
                {"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "85%"},
                "External M8x1 O.15 85%", "M7.85x1", expect_span=surface)
check("shaft Ø8 defaults: two steps in a folder", out["steps"] == 2)

# Full height with a tolerance: the shaft still goes to the looser diameter first
out, res = case("shaft Ø8 ISO O.2 100%", SHAFT, "Shaft", [4, 0, 10],
                {"size": "Auto", "pitch": "ISO standard", "tolerance": "O.2", "height": "100%"},
                "External M8x1.25 O.2", "M7.8x1.25", expect_span=7.8)
check("shaft Ø8 ISO O.2 100%: two steps", out["steps"] == 2)

# A typed size, O.0 and full height: the shaft is already right, one step
out, res = case("shaft typed M8x2 O.0", SHAFT, "Shaft", [4, 0, 10],
                {"size": "M8x2", "pitch": "1 mm", "tolerance": "O.0", "height": "100%"},
                "External M8x2 O.0", "M8x2", expect_span=8.0)
check("shaft typed M8x2 O.0: one step", out["steps"] == 1)
full_length = res[-1]["bodies"][0]["volume_mm3"]
out, res = case("shaft typed M8x2 O.0 length 10", SHAFT, "Shaft", [4, 0, 10],
                {"size": "M8x2", "pitch": "1 mm", "tolerance": "O.0", "height": "100%", "length": 10},
                "External M8x2 O.0", "M8x2")
check("length 10: less material cut than the whole face", res[-1]["bodies"][0]["volume_mm3"] > full_length + 1,
      f"{res[-1]['bodies'][0]['volume_mm3']:.1f} vs {full_length:.1f} mm³")

# A hole: Ø7.2 is a tap drill of M8x1, so Auto picks M8x1 and makes it looser
hole_point = [3.6, 0, 7.5]
sc = os.path.join(TMP, "hole.sc")
out, res = case("hole Ø7.2 O.2 100%", HOLE, "Block", hole_point,
                {"size": "Auto", "pitch": "1 mm", "tolerance": "O.2", "height": "100%"},
                "Internal M8x1 O.2", "M8.2x1", save=sc)
check("hole: no drill hint for the right drill", out["hint"] is None, str(out["hint"]))
reopened, _ = run([{"command": "document.inspect", "params": {"timeline": "summary", "bodies": False}}], inp=sc)
check("hole: saved design reopens with the thread", "Internal M8x1 O.2" in [f["name"] for f in reopened[0]["timeline"]])

# Holes at a lower height: opened up first
out, res = case("hole Ø7.2 80%", HOLE, "Block", hole_point,
                {"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "80%"},
                "Internal M8x1 O.15 80%", "M8.15x1")
check("hole 80%: two steps", out["steps"] == 2)

# A full-height hole narrower than the thread's teeth reach (SolidCraft refuses to cut it) is
# opened up to the thread's minor diameter first
NARROW = [HOLE[0], {"command": "solid.cylinder", "params": {"diameter": 6.8, "height": 15, "operation": "cut", "targets": ["Block"]}}]
out, res = case("hole Ø6.8 O.2 100%", NARROW, "Block", [3.4, 0, 7.5],
                {"size": "Auto", "pitch": "1 mm", "tolerance": "O.2", "height": "100%"},
                "Internal M8x1 O.2", "M8.2x1")
check("hole Ø6.8 100%: opened to the minor diameter, then threaded",
      out["steps"] == 2 and abs(out["surface_diameter"] - (8.2 - 2 * ISO_HEIGHT)) < 1e-6, f"{out['steps']} steps, {out['surface_diameter']}")

# A second thread with the same settings gets its own name
two = SHAFT + [{"command": "solid.cylinder", "params": {"diameter": 8, "height": 20, "operation": "new", "body_name": "Shaft2", "base": [20, 0, 0]}}]
res, _ = run(two + [select("Shaft", [4, 0, 10]), thread({"size": "Auto", "pitch": "1 mm", "tolerance": "O.2", "height": "100%"}),
                    select("Shaft2", [24, 0, 10]), thread({"size": "Auto", "pitch": "1 mm", "tolerance": "O.2", "height": "100%"})])
check("second thread: unique name", res[-1]["name"] == "External M8x1 O.2 (2)", res[-1]["name"])

# A shaft and a hole modelled at the same whole millimetre get the same size and engage: the
# hole's teeth reach inside the shaft's crests (once both were cut a size apart and fell through).
def mate(shaft_d, hole_d, params):
    setup = [
        {"command": "solid.cylinder", "params": {"diameter": shaft_d, "height": 20, "operation": "new", "body_name": "Bolt", "base": [100, 0, 0]}},
        {"command": "solid.box", "params": {"length": 60, "width": 60, "height": 15, "center": [0, 0, 7.5], "operation": "new", "body_name": "Nut"}},
        {"command": "solid.cylinder", "params": {"diameter": hole_d, "height": 15, "operation": "cut", "targets": ["Nut"]}},
        select("Bolt", [100 + shaft_d / 2, 0, 10]), thread(params), select("Nut", [hole_d / 2, 0, 7.5]), thread(params),
    ]
    res, _ = run(setup + [{"command": "inspect.measure", "params": {}}])
    bolt = [b for b in res[-1]["bodies"] if b["name"] == "Bolt"][0]
    crest = bolt["bbox"]["max"][1] - bolt["bbox"]["min"][1]
    inside, err = run(setup + [
        {"command": "solid.cylinder", "params": {"diameter": crest, "height": 13, "base": [0, 0, 1], "operation": "intersect", "targets": ["Nut"]}},
        {"command": "inspect.measure", "params": {}}], fail_ok=True)
    volume = sum(b["volume_mm3"] for b in inside[-1]["bodies"] if b["name"] == "Nut") if inside else 0.0
    return res[4]["size"], res[6]["size"], volume, res[6]["hint"]


for h in ("85%", "100%"):
    bolt, nut, volume, hint = mate(14, 14, {"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": h})
    check(f"Ø14 shaft and Ø14 hole {h}: both M14x1", bolt == nut == "M14x1", f"{bolt} / {nut}")
    check(f"Ø14 shaft and Ø14 hole {h}: the threads engage", volume > 1, f"{volume:.1f} mm³ of the nut inside the bolt's crests")
    check(f"Ø14 hole {h}: no drill hint", hint is None, str(hint))
bolt, nut, volume, _ = mate(8, 6.8, {"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "85%"})
check("Ø8 shaft and Ø6.8 tap-drilled hole: both M8x1 and engage", bolt == nut == "M8x1" and volume > 1, f"{bolt} / {nut}, {volume:.1f} mm³")

# Errors: nothing selected, a flat face, a pitch too coarse for the shaft
_, err = run(SHAFT + [thread({"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "85%"})], fail_ok=True)
check("nothing selected: says to select a face", "Select a cylindrical face" in err, err.strip()[-200:])
_, err = run(SHAFT + [select("Shaft", [0, 0, 20]), thread({"size": "Auto", "pitch": "1 mm", "tolerance": "O.15", "height": "85%"})], fail_ok=True)
check("flat face: says it isn't cylindrical", "isn't cylindrical" in err, err.strip()[-200:])
SMALL = [{"command": "solid.cylinder", "params": {"diameter": 6, "height": 20, "operation": "new", "body_name": "Small"}}]
_, err = run(SMALL + [select("Small", [3, 0, 10]), thread({"size": "Auto", "pitch": "3.5 mm", "tolerance": "O.15", "height": "85%"})], fail_ok=True)
check("Ø6 with a 3.5 mm pitch: too small", "too small" in err, err.strip()[-200:])
res, err = run(SHAFT + [select("Shaft", [4, 0, 10]), thread({"size": "Auto", "pitch": "1 mm", "tolerance": "O.8", "height": "85%"}),
                        {"command": "document.inspect", "params": {"timeline": "summary", "bodies": False}}], fail_ok=True)
check("O.8 on a 1 mm pitch: refused, nothing cut", res is None and "at most 0.5 mm" in err, err.strip()[-200:])

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{len(failed)} failed" if failed else "\nall passed")
sys.exit(1 if failed else 0)
