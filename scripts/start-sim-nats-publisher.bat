@echo off
REM Start the simulated NATS UST trade publisher
REM Usage: scripts\start-sim-nats-publisher.bat

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo === Simulated NATS Trade Publisher ===
echo   Target:  nats://montunoblenumbat2404:8821
echo   Subject: rates.ust.trades.sim
echo.

python scripts\sim_nats_publisher.py %*
