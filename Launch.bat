@echo off
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ── Already running? ──────────────────────────────────────────────────────────
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    start http://localhost:8000
    exit /b 0
)

:: ── Find uv ───────────────────────────────────────────────────────────────────
set "UV=uv"
where uv >nul 2>&1
if %errorlevel% neq 0 (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
)

:: ── First-time setup ──────────────────────────────────────────────────────────
if not exist ".venv" (
    echo.
    echo bandcamp to rekordbox  ^|  First-time setup
    echo This takes about a minute and only happens once.
    echo.

    where uv >nul 2>&1
    if %errorlevel% neq 0 (
        if not exist "%USERPROFILE%\.local\bin\uv.exe" (
            echo Installing package manager...
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
            set "PATH=%USERPROFILE%\.local\bin;%PATH%"
            set "UV=%USERPROFILE%\.local\bin\uv.exe"
        )
    )

    echo Installing Python and dependencies...
    "%UV%" sync

    echo Installing browser for Bandcamp login...
    "%UV%" run playwright install chromium

    echo.
)

:: ── Create Desktop shortcut (once) ───────────────────────────────────────────
set "SHORTCUT=%USERPROFILE%\Desktop\Rekordbox-Bandcamp.lnk"
if not exist "%SHORTCUT%" (
    :: Convert PNG to ICO using Python (PNG-in-ICO works on Windows Vista+)
    "%UV%" run python -c "import struct,pathlib; p=pathlib.Path('static/images/bc-logo-512.png').read_bytes(); h=struct.pack('<HHH',0,1,1); e=struct.pack('<BBBBHHII',0,0,0,0,1,32,len(p),22); pathlib.Path('static/images/app.ico').write_bytes(h+e+p)"

    powershell -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath='%SCRIPT_DIR%\Launch.bat'; $s.WorkingDirectory='%SCRIPT_DIR%'; $s.IconLocation='%SCRIPT_DIR%\static\images\app.ico'; $s.Description='bandcamp to rekordbox'; $s.Save()"

    echo Created shortcut on your Desktop!
    echo.
)

:: ── Launch ────────────────────────────────────────────────────────────────────
"%UV%" run server.py
