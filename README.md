# SolidCraft Thread Generator

Makes 3D-printable threaded parts: bolts, threaded rods, nuts, bolt + nut pairs
and thread cutters. Output is a watertight STL, optionally opened in SolidCraft.

## Install

1. Download `thread-generator-<version>.zip`.
2. In SolidCraft open **Preferences → Plugins → Show in folder** and unzip the
   zip there, so you get `plugins\thread-generator\plugin.json`
   (on Windows: `%LOCALAPPDATA%\SolidCraft\plugins`).
3. Reopen Preferences → Plugins: **Thread Generator** is listed.
4. Start **ThreadGenerator.exe** from that folder. No Python needed. Windows
   may show "Windows protected your PC" because the program isn't code-signed:
   click *More info → Run anyway*.

Or unzip it anywhere, run the exe and click *Install as SolidCraft plugin*.
Files are saved to `Documents\SolidCraft Threads` (change it in the window).

SolidCraft's plugin system currently lists plugins but doesn't run them yet, so
the generator opens in its own window. When SolidCraft can run plugins
([#1221](https://github.com/tangency-labs/solidcraft/issues/1221)) it can move
inside the app.

## Thread a face in SolidCraft

The first tab works on the design you have open in SolidCraft (0.22 or later):

1. In SolidCraft, select the round face of a shaft, or the inside of a hole.
2. Click **Use selected face**. The generator asks SolidCraft what fits: shaft or
   hole, the size (a 10 mm shaft or an 8.5 mm hole both give M10) and the length.
3. Pick the size (ISO metric M1–M48, fine pitches, UNC) and the **clearance**
   (0, 0.1, 0.15, 0.2 … mm per side), and optionally a shorter length.
4. Click **Add thread**. SolidCraft cuts a modeled thread into the body: a shaft
   gets 2 × clearance smaller in diameter, a hole 2 × clearance larger, with the
   same pitch. It's a normal feature in the timeline, named for example
   "External M10x1.5 +0.2 clearance", and Ctrl+Z in SolidCraft undoes it.

The window stays on top of SolidCraft so you can keep selecting faces.
Printing both a bolt and a nut? Give both a clearance.

SolidCraft is optional: without it you can still save STLs for your slicer.
With it, *Preview* and *Open in SolidCraft* work. If SolidCraft is installed
somewhere other than `C:\Program Files\SolidCraft`, click *Locate SolidCraft…*.

From source: run `python "Thread Generator.pyw"` (Python 3.10+, standard library
only). `build.bat` rebuilds the .exe and the release zip (needs PyInstaller);
`build.bat --install` also installs it in your SolidCraft plugins folder.

## Options

| Option | Meaning |
|---|---|
| Standard / Size | ISO metric coarse & fine, UNC, trapezoidal (Tr), large jar threads, or Custom |
| Diameter, Pitch | Nominal outer diameter and distance between crests (mm). Editable for any size |
| Profile | 60° V (ISO/UNC), 30° trapezoidal, 29° ACME, square, buttress |
| Starts | Multi-start threads (each turn advances starts × pitch). Bolt and nut must match |
| Depth | Thread depth. Blank = standard for the profile |
| Left-hand | Reverse thread |
| Clearance | Gap added to every surface of the part (normal to the surface, so flanks get the same gap as crests). A printed bolt and nut get **2 × clearance** between them; one printed part still fits a metal one. FDM 0.1–0.2 mm, resin 0.05–0.1 mm |
| Chamfer | Lead-in bevel on thread ends (blank = automatic) |
| Length / Plain shank | Shaft length under the head, and the unthreaded part of it |
| Head / Nut shape, width, height | hex, round or square. Width is across the flats. Blank = ISO-like sizes |
| Quality | draft / normal / fine mesh density |

## Thread cutter

SolidCraft can't subtract a mesh from a solid body, so use the cutter in your
slicer instead: in Bambu Studio / OrcaSlicer / PrusaSlicer, right-click your
model → *Add negative part → Load…* and pick the cutter STL. Position it where
the hole should be. It cuts a threaded hole that fits a bolt of the same size.

## Command line

```
python threadgen.py pair --size M8 -l 25 -c 0.15 --open
python threadgen.py rod  --size Tr8x2 --starts 4 -l 100 -o out
python threadgen.py nut  -d 40 -p 4 --profile buttress --nut round --nut-flats 50
python threadgen.py --help
```

`--design` writes a `.solidcraft` file next to the STLs; `--open` opens it in SolidCraft.
Set `SOLIDCRAFT_HOME` if SolidCraft isn't installed in `C:\Program Files\SolidCraft`.
