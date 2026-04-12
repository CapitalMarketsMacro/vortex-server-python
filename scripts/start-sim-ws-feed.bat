@echo off
REM Start the simulated upstream WebSocket price feed server
REM Usage: scripts\start-sim-ws-feed.bat

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo === Simulated WS Price Feed ===
echo   Listen: ws://localhost:9000
echo.

python scripts\sim_ws_feed.py %*
