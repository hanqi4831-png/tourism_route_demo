@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ========================================
echo Tourism Route Recommendation System
echo ========================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    py -3 -m venv .venv >nul 2>nul
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Failed to create virtual environment.
        echo Please make sure Python is installed and available in PATH.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment already exists.
)

echo [2/4] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [3/4] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo [4/4] Starting Web application...
".venv\Scripts\python.exe" main.py

pause
