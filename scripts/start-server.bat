@echo off
REM Start the Vortex data server (Perspective + connectors)
REM Usage: scripts\start-server.bat

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo === Vortex Server ===
echo   WebSocket: ws://0.0.0.0:8080/websocket
echo   Health:    http://0.0.0.0:8080/health/ready
echo   Metrics:   http://0.0.0.0:8080/metrics
echo   Status:    http://0.0.0.0:8080/api/status
echo.

python -m vortex.server %*
