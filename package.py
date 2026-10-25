"""Writes plugin.json and release/thread-generator-<version>.zip from dist/ThreadGenerator.exe.

The zip holds one folder named after the plugin id, ready to drop into SolidCraft's
plugins folder. `python package.py --install` also installs it for this user.
"""
import json
import os
import sys
import zipfile

import threadgen

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ["dist/ThreadGenerator.exe", "README.md", "LICENSE", "plugin.json"]


def main():
    os.chdir(HERE)
    with open("plugin.json", "w", encoding="utf-8") as fh:
        json.dump(threadgen.plugin_manifest(), fh, indent=2)
    os.makedirs("release", exist_ok=True)
    name = f"release/{threadgen.PLUGIN_ID}-{threadgen.__version__}.zip"
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(f, f"{threadgen.PLUGIN_ID}/{os.path.basename(f)}")
    print(name)
    if "--install" in sys.argv:
        print("installed in", threadgen.install_plugin(FILES))


if __name__ == "__main__":
    main()
