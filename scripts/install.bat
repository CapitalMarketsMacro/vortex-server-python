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
REM Try py launcher first (standard on Windows), then python on PATH
set PYTHON=

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set PYTHON=py -3
    goto :found
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    set PYTHON=python
    goto :found
)

echo ERROR: Python is not found on PATH.
echo        Install Python 3.11+ from https://www.python.org and try again.
exit /b 1

:found
echo === Vortex Install ===
%PYTHON% --version
echo.

REM Verify version is 3.11+
%PYTHON% -c "import sys; assert sys.version_info >= (3, 11), f'Python 3.11+ required, got {sys.version}'" 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python 3.11+ is required.
    %PYTHON% --version
    exit /b 1
)

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
    echo Installing vortex-server-python production only...
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
