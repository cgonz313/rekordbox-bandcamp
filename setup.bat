@echo off
echo bandcamp ^> rekordbox  ^|  setup
echo ================================
echo.

:: Check for Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed.
    echo.
    echo Download it from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [ok] %PYVER% found

:: Install pip dependencies
echo.
echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Try running manually:
    echo   python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo [ok] Dependencies installed

:: Install Playwright browser
echo.
echo Installing Chromium browser for Bandcamp login...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ERROR: Playwright install failed. Try running manually:
    echo   python -m playwright install chromium
    echo.
    pause
    exit /b 1
)
echo [ok] Chromium installed

echo.
echo ================================
echo Setup complete!
echo Double-click start.bat to launch the app.
echo.
pause
