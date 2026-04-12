@echo off
REM Start the Vortex Admin GUI (Flask)
REM Usage: scripts\start-admin.bat

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo === Vortex Admin GUI ===
echo   Dashboard: http://0.0.0.0:8090/
echo   Status:    http://0.0.0.0:8090/status
echo.

python -m vortex.admin.app %*
