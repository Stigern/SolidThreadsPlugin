@echo off
rem Builds dist\ThreadGenerator.exe and release\thread-generator-<version>.zip
rem build.bat --install  also installs it in SolidCraft's plugins folder
rem Needs Python 3 with PyInstaller:  python -m pip install pyinstaller
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ThreadGenerator --exclude-module pygame --exclude-module numpy --exclude-module PIL --icon icon.ico --add-data "icon.ico;." --add-data "README.md;." --add-data "LICENSE;." ^
  "Thread Generator.pyw" || exit /b 1
python package.py %*
