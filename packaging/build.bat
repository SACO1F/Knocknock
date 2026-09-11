@echo off
REM Build Knocknock into a single portable executable (dist\Knocknock.exe).
REM
REM Usage:  packaging\build.bat
REM
REM The script uses the project's own virtual environment when it exists, so the
REM build never touches the system Python installation.

chcp 65001 >nul
cd /d "%~dp0\.."

set PY=".venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Creating .venv and installing dependencies...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    set PY=".venv\Scripts\python.exe"
)

echo [1/3] Installing PyInstaller...
%PY% -m pip install --upgrade pyinstaller || goto :error

echo [2/3] Generating the application icon...
%PY% "packaging\make_icon.py" || goto :error

echo [3/3] Building the executable...
%PY% -m PyInstaller "packaging\knocknock.spec" --noconfirm --clean || goto :error

echo.
echo Done. The executable is at: dist\Knocknock.exe
echo Copy it anywhere and run it directly. config.json is created next to it.
exit /b 0

:error
echo.
echo [X] Build failed. See the output above for details.
exit /b 1
