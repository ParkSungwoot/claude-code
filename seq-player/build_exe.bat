@echo off
rem Builds "dist\COC_SEQ Player\COC_SEQ Player.exe" on Windows.
rem Needs Python 3.10-3.13 (64-bit) from python.org. Run by double-clicking or from cmd.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 (
    echo [!] Python was not found. Install Python 3.12 64-bit from https://www.python.org and try again.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [!] Installing packages failed.
    pause
    exit /b 1
)

pyinstaller --noconfirm "COC_SEQ Player.spec"
if errorlevel 1 (
    echo [!] Build failed.
    pause
    exit /b 1
)

"dist\COC_SEQ Player\COC_SEQ Player.exe" --self-test "dist\self-test.txt"
type "dist\self-test.txt"
echo.
echo Done: dist\COC_SEQ Player\COC_SEQ Player.exe
echo Copy the whole "dist\COC_SEQ Player" folder to share the program.
pause
