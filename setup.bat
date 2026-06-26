@echo off
cd /d "%~dp0"

echo.
echo bandcamp to rekordbox  ^|  Setup
echo ================================
echo.

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing uv (Python manager)...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Installing dependencies...
uv sync

echo.
echo Installing Chromium browser for Bandcamp login...
uv run playwright install chromium

echo.
echo ================================
echo Setup complete!
echo Double-click start.bat to launch the app.
echo ================================
echo.
pause
