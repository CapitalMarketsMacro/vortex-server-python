@echo off
REM Launch all Vortex processes in the correct order.
REM Each sim/server runs in its own window; closing this window stops the seed only.
REM
REM Usage:
REM   scripts\start-all.bat              — all processes including simulators
REM   scripts\start-all.bat --no-sims    — server + admin only

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM ── 1. Seed Mongo ──────────────────────────────────────────────────────
echo === Step 1: Seed Mongo ===
python scripts\seed_mongo.py
echo.

set NO_SIMS=0
if "%~1"=="--no-sims" set NO_SIMS=1

REM ── 2. Simulated WS feed ──────────────────────────────────────────────
if %NO_SIMS%==0 (
    echo === Step 2: Starting simulated WS feed ===
    start "Vortex - WS Feed Sim" cmd /k "cd /d %CD% && .venv\Scripts\activate.bat && python scripts\sim_ws_feed.py"
    timeout /t 1 /nobreak >nul
)

REM ── 3. Simulated NATS publisher ────────────────────────────────────────
if %NO_SIMS%==0 (
    echo === Step 3: Starting simulated NATS publisher ===
    start "Vortex - NATS Publisher Sim" cmd /k "cd /d %CD% && .venv\Scripts\activate.bat && python scripts\sim_nats_publisher.py"
    timeout /t 1 /nobreak >nul
)

REM ── 4. Vortex data server ──────────────────────────────────────────────
echo === Step 4: Starting Vortex server ===
start "Vortex - Data Server" cmd /k "cd /d %CD% && .venv\Scripts\activate.bat && python -m vortex.server"
timeout /t 2 /nobreak >nul

REM ── 5. Vortex admin GUI ────────────────────────────────────────────────
echo === Step 5: Starting Vortex admin GUI ===
start "Vortex - Admin GUI" cmd /k "cd /d %CD% && .venv\Scripts\activate.bat && python -m vortex.admin.app"

echo.
echo =============================================
echo   All Vortex processes running.
echo.
echo   Data server:    ws://0.0.0.0:8080/websocket
echo   Health:         http://0.0.0.0:8080/health/ready
echo   Metrics:        http://0.0.0.0:8080/metrics
echo   Admin GUI:      http://0.0.0.0:8090/
echo   Live status:    http://0.0.0.0:8090/status
echo.
echo   Each process runs in its own window.
echo   Close individual windows to stop them.
echo =============================================
