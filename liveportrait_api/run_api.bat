@echo off
REM ──────────────────────────────────────────────
REM  SmileLoop – Start the local API server
REM ──────────────────────────────────────────────
REM  Prerequisites:
REM    1. conda activate LivePortrait
REM    2. pip install -r liveportrait_api\requirements_api.txt
REM    3. Set LIVEPORTRAIT_ROOT if LivePortrait isn't at .\LivePortrait
REM
REM  Usage:  run_api.bat  [host] [port]
REM  Default:  127.0.0.1:8000
REM ──────────────────────────────────────────────

SET HOST=%1
SET PORT=%2
IF "%HOST%"=="" SET HOST=127.0.0.1
IF "%PORT%"=="" SET PORT=8000

echo.
echo   ____            _ _      _
echo  / ___^|_ __ ___  (_) ^| ___^| ^|    ___   ___  _ __
echo  \___ \^| '_ ` _ \^| ^| ^|/ _ \ ^|   / _ \ / _ \^| '_ \
echo   ___) ^| ^| ^| ^| ^| ^| ^| ^|  __/ ^|__^| (_) ^| (_) ^| ^|_) ^|
echo  ^|____/^|_^| ^|_^| ^|_^|_^|_^|\___^|_____\___/ \___/^| .__/
echo                                            ^|_^|
echo.
echo  API: http://%HOST%:%PORT%
echo  Docs: http://%HOST%:%PORT%/docs
echo.

cd /d "%~dp0\.."

python -m uvicorn liveportrait_api.server:app --host %HOST% --port %PORT% --reload
