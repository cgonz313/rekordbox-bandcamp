@echo off
cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo Setup has not been run yet. Please double-click setup.bat first.
    pause
    exit /b 1
)

uv run server.py
