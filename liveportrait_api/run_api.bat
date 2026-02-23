@echo off@echo off

REM ------------------------------------------------REM ──────────────────────────────────────────────

REM  SmileLoop - Start the API serverREM  SmileLoop – Start the local API server

REM ------------------------------------------------REM ──────────────────────────────────────────────

REM  Usage:  run_api.bat [mode] [host] [port]REM  Prerequisites:

REMREM    1. conda activate LivePortrait

REM  mode:  local | modal | cloud   (default: modal)REM    2. pip install -r liveportrait_api\requirements_api.txt

REM  host:  bind address            (default: 127.0.0.1)REM    3. Set LIVEPORTRAIT_ROOT if LivePortrait isn't at .\LivePortrait

REM  port:  port number             (default: 8000)REM

REMREM  Usage:  run_api.bat  [host] [port]

REM  Examples:REM  Default:  127.0.0.1:8000

REM    run_api.bat                    # modal on 127.0.0.1:8000REM ──────────────────────────────────────────────

REM    run_api.bat local              # local GPU inference

REM    run_api.bat modal 0.0.0.0 8080 # modal on all interfacesSET HOST=%1

REM ------------------------------------------------SET PORT=%2

IF "%HOST%"=="" SET HOST=127.0.0.1

SET MODE=%1IF "%PORT%"=="" SET PORT=8000

SET HOST=%2

SET PORT=%3echo.

IF "%MODE%"=="" SET MODE=modalecho   ____            _ _      _

IF "%HOST%"=="" SET HOST=127.0.0.1echo  / ___^|_ __ ___  (_) ^| ___^| ^|    ___   ___  _ __

IF "%PORT%"=="" SET PORT=8000echo  \___ \^| '_ ` _ \^| ^| ^|/ _ \ ^|   / _ \ / _ \^| '_ \

echo   ___) ^| ^| ^| ^| ^| ^| ^| ^|  __/ ^|__^| (_) ^| (_) ^| ^|_) ^|

SET INFERENCE_MODE=%MODE%echo  ^|____/^|_^| ^|_^| ^|_^|_^|_^|\___^|_____\___/ \___/^| .__/

echo                                            ^|_^|

echo.echo.

echo   ____            _ _      _echo  API: http://%HOST%:%PORT%

echo  / ___^|_ __ ___  (_) ^| ___^| ^|    ___   ___  _ __echo  Docs: http://%HOST%:%PORT%/docs

echo  \___ \^| '_ ` _ \^| ^| ^|/ _ \ ^|   / _ \ / _ \^| '_ \echo.

echo   ___) ^| ^| ^| ^| ^| ^| ^| ^|  __/ ^|__^| (_) ^| (_) ^| ^|_) ^|

echo  ^|____/^|_^| ^|_^| ^|_^|_^|_^|\___^|_____\___/ \___/^| .__/cd /d "%~dp0\.."

echo                                            ^|_^|

echo.python -m uvicorn liveportrait_api.server:app --host %HOST% --port %PORT% --reload

echo  Mode: %MODE%
echo  API:  http://%HOST%:%PORT%
echo  Docs: http://%HOST%:%PORT%/docs
echo.

cd /d "%~dp0\.."

python -m uvicorn liveportrait_api.server:app --host %HOST% --port %PORT%
