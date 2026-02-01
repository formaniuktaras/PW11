@echo off
set PYTHON=python
set SCRIPT_DIR=%~dp0

pushd "%SCRIPT_DIR%\.."

echo Building InventoryLite...

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.12.
    exit /b 1
)

if not exist ".\.venv" (
    %PYTHON% -m venv ".\.venv"
)
call ".\.venv\Scripts\activate.bat"

python -m pip install --upgrade pip
python -m pip install -r inventorylite\requirements.txt

python -m compileall inventorylite
if errorlevel 1 (
    echo Python compileall failed
    exit /b 1
)

python - <<"PY"
from pathlib import Path
import base64
base64_path = Path("inventorylite/icons/app_ico_base64.txt")
icon_path = Path("inventorylite/icons/app.ico")
icon_path.write_bytes(base64.b64decode(base64_path.read_text().strip()))
PY

set ICON=inventorylite\icons\app.ico
set FONT_ARGS=
if exist ".\inventorylite\assets\fonts\DejaVuSans.ttf" (
    set FONT_ARGS=--add-data "inventorylite\assets\fonts\DejaVuSans.ttf;inventorylite\assets\fonts"
    if exist ".\inventorylite\assets\fonts\DejaVuSans-Bold.ttf" (
        set FONT_ARGS=%FONT_ARGS% --add-data "inventorylite\assets\fonts\DejaVuSans-Bold.ttf;inventorylite\assets\fonts"
    )
)

pyinstaller --onefile --noconsole --name InventoryLite --icon %ICON% %FONT_ARGS% inventorylite\app.py --collect-submodules inventorylite

if exist dist\InventoryLite.exe (
    echo Build complete: %CD%\dist\InventoryLite.exe
) else (
    echo Build failed
    exit /b 1
)

popd
