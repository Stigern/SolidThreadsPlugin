"""Writes release/ThreadGenerator-<version>-windows.zip from dist/ThreadGenerator.exe.

This is the standalone window (STL bolts, nuts, rods and cutters, repaired 3MF export, and
threads on a face through SolidCraft's control channel). The SolidCraft plugin is built
separately, by plugin/build.sh, into release/thread-generator-<version>.zip.
"""
import os
import zipfile

import threadgen

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["dist/ThreadGenerator.exe", "README.md", "LICENSE"]


def main():
    os.chdir(HERE)
    os.makedirs("release", exist_ok=True)
    name = f"release/ThreadGenerator-{threadgen.__version__}-windows.zip"
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(f, f"ThreadGenerator/{os.path.basename(f)}")
    print(name)


if __name__ == "__main__":
    main()
