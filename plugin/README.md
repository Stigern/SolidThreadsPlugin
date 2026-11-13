# Thread Generator plugin for SolidCraft

Cuts a 3D-printable thread into the shaft or hole you select in SolidCraft (0.41 or later),
with the tolerance classes and lower teeth of the [Thread Generator](https://github.com/Stigern/SolidThreadsPlugin).

## Use

1. Select the round face of a shaft, or the inside of a hole.
2. **Plugins › Thread Generator › Add thread…**
3. Pick the size, pitch, tolerance and height, and optionally a length. Run.

The thread is a modeled thread feature in the timeline, named like "External M8x1 O.15 85%".
With a height below 100% the face is first offset and both steps are grouped in a folder.
One run is one undo step.

| Field | Default | Meaning |
|---|---|---|
| Size | Auto | Auto fits the face. Or type `M8x1`, `M10` (pitch from Pitch) or a UNC size like `1/4-20` |
| Pitch | 1 mm | 1, 1.25, 1.5, 1.75, 2, 2.5, 3.5 or 5 mm (3D-printed metric), or ISO standard (metric coarse) |
| Tolerance | O.2 | Looser by this much on each diameter: a shaft smaller, a hole larger |
| Height | 85% | Tooth height as a share of the full ISO height; lower teeth have flat tops |
| Length | empty | Thread length along the face; empty threads the whole face |

Hover over a field in the dialog to see what it does and which value to start with.

With **Auto** a shaft gets its own diameter (Ø8 → M8x1), and so does a hole of a whole
millimetre (Ø14 → M14x1), so a shaft and a hole modelled at the same diameter fit each other.
Any other hole is read as a tap drill and gets the size whose tap drill it is (Ø6.8 with a 1 mm
pitch → M8x1), as does a whole-millimetre hole too small for the pitch (Ø3 → M4x1).

## Install

Plugins › **Install plugin…** (or Preferences › Plugins › Install plugin…) and pick
`thread-generator-<version>.zip`. It asks for no files, network or app settings: it only runs
SolidCraft's own selection, thread, offset-face and timeline commands on the open design.

MIT license.
