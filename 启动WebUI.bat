@echo off
setlocal
title AnimeAutoSub WebUI

echo ============================================================
echo   AnimeAutoSub WebUI - startup
echo ============================================================
echo.

cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] Python venv not found:
    echo         %~dp0venv\Scripts\python.exe
    echo.
    echo         Create it first, then run this launcher again.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0web\app.py" (
    echo [ERROR] Launcher must sit next to the project folder.
    echo         Missing: %~dp0web\app.py
    echo.
    pause
    exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
chcp 65001 >nul

echo [INFO] Work directory: %~dp0
echo [INFO] Starting local service...
echo [INFO] The browser will open automatically.
echo [INFO] Close this window to stop the service.
echo.

"%~dp0venv\Scripts\python.exe" -m web.app
set EXITCODE=%errorlevel%

echo.
echo ------------------------------------------------------------
if "%EXITCODE%"=="0" (
    echo [INFO] Service stopped normally.
) else (
    echo [WARN] Service exited with code %EXITCODE%
    echo        Scroll up to see the error message.
)
echo ------------------------------------------------------------
echo.
pause
endlocal
