@echo off
REM Builds dist\PdfOcr.exe (single file, no console window).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    python -m venv .venv || exit /b 1
)
.venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --noconsole --onefile --name PdfOcr ^
    --collect-submodules keyring.backends ^
    main.py
