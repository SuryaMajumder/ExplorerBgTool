@echo off
echo ================================
echo  Explorer Background Tool
echo ================================
echo.

:: Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Not running as admin. Relaunching with admin rights...
    powershell -Command "Start-Process cmd -ArgumentList '/k cd /d \"%~dp0\" && \"%~f0\"' -Verb RunAs"
    exit /b
)

echo [OK] Running as Administrator
echo [OK] Working folder: %~dp0
cd /d "%~dp0"
echo.

:: Check Python
echo [..] Checking Python...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH!
    echo Please install Python from https://python.org
    echo Make sure to tick "Add Python to PATH" during install!
    pause
    exit /b
)
echo [OK] Python found!
echo.

:: Check Pillow
echo [..] Checking Pillow (image library)...
python -c "from PIL import Image; print('[OK] Pillow found!')"
if %errorlevel% neq 0 (
    echo [..] Pillow not found. Installing now...
    pip install pillow
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install Pillow!
        echo Try running: pip install pillow
        pause
        exit /b
    )
    echo [OK] Pillow installed!
)
echo.

:: Check script exists
echo [..] Looking for explorer_bg_tool.py...
if not exist "explorer_bg_tool.py" (
    echo [ERROR] explorer_bg_tool.py not found in this folder!
    echo Make sure the .py file and this .bat file are in the SAME folder.
    echo Current folder contents:
    dir /b
    pause
    exit /b
)
echo [OK] Script found!
echo.

:: Launch
echo [..] Launching GUI...
python explorer_bg_tool.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] The app crashed! Error code: %errorlevel%
    pause
    exit /b
)

pause
