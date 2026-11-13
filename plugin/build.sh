#!/usr/bin/env bash
# Builds the SolidCraft plugin: dist/thread-generator/ (plugin.wasm + plugin.json + README + LICENSE)
# and release/thread-generator-<version>.zip, ready for Plugins > Install plugin… in SolidCraft.
# Needs Rust with the wasm32-unknown-unknown target and wasm-tools:
#   rustup target add wasm32-unknown-unknown
#   cargo install wasm-tools --locked
# ./build.sh --install  also installs the zip into this user's SolidCraft (solidcraft-cli plugin.install).
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release --lib --target wasm32-unknown-unknown
out=dist/thread-generator
rm -rf "$out"; mkdir -p "$out"
wasm-tools component new "${CARGO_TARGET_DIR:-target}/wasm32-unknown-unknown/release/thread_generator.wasm" -o "$out/plugin.wasm"
wasm-tools validate "$out/plugin.wasm"
cp plugin.json "$out/"
cp ../LICENSE "$out/"
cp README.md "$out/README.md"
version=$(python -c 'import json;print(json.load(open("plugin.json"))["version"])')
mkdir -p release
zip="release/thread-generator-$version.zip"
rm -f "$zip"
python - "$zip" <<'EOF'
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir("dist/thread-generator")):
        z.write(os.path.join("dist/thread-generator", f), "thread-generator/" + f)
EOF
echo "built $out and $zip"
if [ "${1:-}" = "--install" ]; then
  cli="${SOLIDCRAFT_CLI:-solidcraft-cli}"
  if ! command -v "$cli" >/dev/null && [ -x "/c/Program Files/SolidCraft/solidcraft-cli.exe" ]; then
    cli="/c/Program Files/SolidCraft/solidcraft-cli.exe"
  fi
  tmp=$(mktemp -d)
  printf '[{"command":"plugin.install","params":{"path":"%s","replace":true}}]' "$(cd release && pwd -W 2>/dev/null || pwd)/$(basename "$zip")" > "$tmp/install.json"
  "$cli" run "$tmp/install.json" --results
  rm -rf "$tmp"
fi
