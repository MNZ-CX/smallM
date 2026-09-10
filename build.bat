@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================================
echo   smallM  -  build single-file dist\smallM.exe
echo ==========================================================
echo.

REM ---------- 1) locate a working Python ----------
REM  You may pin the interpreter first:
REM      set PYTHON=D:\Python312\python.exe
REM      build.bat
set "PY="
if defined PYTHON set "PY=%PYTHON%"
if not defined PY where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && py -c "import sys" >nul 2>nul && set "PY=py"
if not defined PY for %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*\python.exe" "C:\Python3*\python.exe" "D:\Python3*\python.exe") do (
    if not defined PY if exist %%P set "PY=%%~fP"
)
if not defined PY (
    echo [ERROR] No usable Python found.
    echo         1^) Install Python 3.9+ and tick "Add python.exe to PATH"
    echo            https://www.python.org/downloads/windows/
    echo         2^) Or pin the interpreter manually:
    echo            set PYTHON=D:\Python312\python.exe
    echo            build.bat
    pause
    exit /b 1
)
echo [1/5] Python: %PY%
"%PY%" --version
echo.

REM ---------- 2) runtime dependencies ----------
echo [2/5] Installing runtime dependencies (requirements.txt) ...
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo.

REM ---------- 3) PyInstaller ----------
echo [3/5] Installing / upgrading PyInstaller ...
"%PY%" -m pip install --disable-pip-version-check --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)
echo.

REM ---------- 4) clean previous output ----------
echo [4/5] Cleaning build / dist ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist smallM.spec del /q smallM.spec
echo.

REM ---------- 5) build one-file exe ----------
echo [5/5] Building (first run may take 1-3 minutes) ...
set "ICON="
if exist assets\smallM.ico set "ICON=--icon assets\smallM.ico"

"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name smallM %ICON% --exclude-module tkinter --exclude-module unittest --exclude-module pydoc --exclude-module sqlite3 --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtBluetooth --exclude-module PyQt6.QtDesigner --exclude-module PyQt6.QtCharts --exclude-module PyQt6.Qt3DCore --exclude-module PyQt6.QtTest --exclude-module PyQt6.QtSql --exclude-module PyQt6.QtNetwork --exclude-module PyQt6.QtOpenGL --exclude-module PyQt6.QtPdf main.py

if not exist dist\smallM.exe (
    echo.
    echo [ERROR] Build failed: dist\smallM.exe not found.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   BUILD OK
echo   Output : %cd%\dist\smallM.exe
for %%A in (dist\smallM.exe) do echo   Size   : %%~zA bytes
echo.
echo   Usage:
echo     - Double-click smallM.exe (no Python required)
echo     - memos.json is created next to the exe
echo     - Keep the exe in a writable folder, e.g. D:\Tools\smallM\
echo ==========================================================
echo.
if /i "%~1"=="--no-open" goto done
if exist dist explorer "dist"
:done
pause
endlocal
