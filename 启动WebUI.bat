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
echo [INFO] 正在预检本地服务与在途任务状态...

set FORCE_ARG=
"%~dp0venv\Scripts\python.exe" -m web.app --check-running
if errorlevel 2 (
    echo.
    echo ============================================================
    echo [警告] 检测到当前有任务正在执行！
    echo ============================================================
    echo 强行停止将打断在途任务（虽支持断点续跑，但仍需重新计算当前未完成阶段）。
    echo.
    set /p USER_CONFIRM="有任务正在运行，确定要停止吗？(y/N): "
    if /i not "%USER_CONFIRM%"=="y" (
        echo.
        echo [INFO] 已取消操作，保留当前正在运行的任务。
        echo [INFO] 请等待任务完成，或进入 Web 界面手动操作。
        pause
        exit /b 0
    )
    echo [INFO] 用户已确认强制重启，正在安全保存中断标记并重启服务...
    set FORCE_ARG=--force
)

echo [INFO] Starting local service...
echo [INFO] The browser will open automatically.
echo [INFO] Close this window to stop the service.
echo.

"%~dp0venv\Scripts\python.exe" -m web.app %FORCE_ARG%
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
