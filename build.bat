@echo off
rem Builds the standalone window: dist\ThreadGenerator.exe and release\ThreadGenerator-<version>-windows.zip
rem Needs Python 3 with PyInstaller:  python -m pip install pyinstaller
rem The SolidCraft plugin is built by plugin\build.sh (Rust and wasm-tools; see plugin\README.md).
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ThreadGenerator --exclude-module pygame --exclude-module numpy --exclude-module PIL --icon icon.ico --add-data "icon.ico;." --add-data "README.md;." --add-data "LICENSE;." --add-data "winrepair.ps1;." ^
  "Thread Generator.pyw" || exit /b 1
python package.py
