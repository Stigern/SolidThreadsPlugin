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
2. Click **Use selected face**. The generator reads whether it's a shaft or a
   hole, its diameter and length, and picks a size.
3. Pick the size and the **tolerance**, and optionally a shorter length.
4. Click **Add thread**. SolidCraft cuts a modeled thread into the body. It's a
   normal feature in the timeline, named for example "External M10x3.5 O.2",
   and Ctrl+Z in SolidCraft undoes it.

**Sizes.** The default standard, *3D-printed metric*, follows
[CustomThreads](https://github.com/BalzGuenat/CustomThreads) (MIT): the ISO 60°
profile with a coarse 3.5 or 5 mm pitch for M8–M50. Standard ISO threads
(M10 has a 1.5 mm pitch) are only about 0.9 mm deep, a few layers, and print
poorly; a 3.5 mm pitch is about 2 mm deep. ISO metric, fine and UNC sizes are
still there for parts that must fit metal screws.

Model the parts at the nominal size: a shaft at the thread diameter (10 mm for
M10x3.5), and a hole at diameter − pitch (6.5 mm for M10x3.5). The generator
picks the size from that, and warns when a hole doesn't match the thread.

**Tolerance** uses CustomThreads' classes: O.2 makes this part 0.2 mm looser on
each diameter (a shaft 0.2 mm smaller, a hole 0.2 mm larger). Printing both a
bolt and a nut? Give both a class: start with O.2 on both, go to O.4 if it's
tight, O.1 if it's loose. Any number in mm works too.

Threads are cut into the whole body, and SolidCraft turns every round face of
that body into small flat facets. Keep separate parts as separate bodies
(*New Body* when you extrude) so only the threaded part is affected.

The window stays on top of SolidCraft so you can keep selecting faces.

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
