@echo off
REM Create a virtual environment and install all dependencies.
REM
REM Usage:
REM   scripts\install.bat              — production + dev deps
REM   scripts\install.bat --prod       — production deps only

cd /d "%~dp0\.."

set EXTRAS=dev
if "%~1"=="--prod" set EXTRAS=

REM ── Find Python 3.11+ ──────────────────────────────────────────────────
set PYTHON=
for %%P in (python3.13 python3.12 python3.11 python3 python py) do (
    where %%P >nul 2>&1 && (
        for /f "tokens=*" %%V in ('%%P -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do (
            set PYTHON=%%P
        )
    )
)

REM Try py launcher (Windows standard) with version flag
if "%PYTHON%"=="" (
    where py >nul 2>&1 && (
        set PYTHON=py -3.11
    )
)

if "%PYTHON%"=="" (
    echo ERROR: Python 3.11+ is required but not found on PATH.
    echo        Install Python 3.11+ and try again.
    exit /b 1
)

echo === Vortex Install ===
%PYTHON% --version
echo.

REM ── Create venv ────────────────────────────────────────────────────────
if not exist .venv (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
)

call .venv\Scripts\activate.bat

REM ── Upgrade pip ────────────────────────────────────────────────────────
echo Upgrading pip...
python -m pip install --upgrade pip --quiet

REM ── Install ────────────────────────────────────────────────────────────
if "%EXTRAS%"=="" (
    echo Installing vortex-server-python (production only)...
    pip install -e . --quiet
) else (
    echo Installing vortex-server-python with [%EXTRAS%] extras...
    pip install -e ".[%EXTRAS%]" --quiet
)

echo.
echo === Install complete ===
echo   Activate with:  .venv\Scripts\activate.bat
echo   Run tests:      pytest tests\ -v
echo   Seed Mongo:     scripts\seed-mongo.bat
echo   Start all:      scripts\start-all.bat
