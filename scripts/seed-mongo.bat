@echo off
REM Seed the Vortex MongoDB with initial transports and tables.
REM Idempotent — safe to run multiple times.
REM Usage: scripts\seed-mongo.bat

cd /d "%~dp0\.."

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo === Seeding Mongo (Vortex DB) ===
python scripts\seed_mongo.py %*
echo === Done ===
