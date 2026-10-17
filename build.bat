@echo off
rem Builds dist\ThreadGenerator.exe and release\ThreadGenerator-<version>.zip
rem Needs Python 3 with PyInstaller:  python -m pip install pyinstaller
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ThreadGenerator --exclude-module pygame --exclude-module numpy --exclude-module PIL --icon icon.ico --add-data "icon.ico;." ^
  "Thread Generator.pyw" || exit /b 1
python -c "import threadgen,zipfile,os;v=threadgen.__version__;os.makedirs('release',exist_ok=True);z=zipfile.ZipFile(f'release/ThreadGenerator-{v}.zip','w',zipfile.ZIP_DEFLATED);[z.write(f,f'ThreadGenerator/{os.path.basename(f)}') for f in ['dist/ThreadGenerator.exe','README.md','LICENSE']];z.close();print('release/ThreadGenerator-'+v+'.zip')"
