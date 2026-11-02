@echo off
chcp 65001 >nul

REM ======== 所有缓存/模型指向 D:\Dev ========
set HF_HOME=D:\Dev\huggingface
set HF_HUB_CACHE=D:\Dev\huggingface\hub
set HF_ENDPOINT=https://hf-mirror.com
set TORCH_HOME=D:\Dev\torch
set OLLAMA_MODELS=D:\Dev\ollama\models
set PATH=D:\Dev\ffmpeg\bin;%PATH%

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [错误] 未检测到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

REM 检查 ocr_input 文件夹
if not exist "ocr_input" (
    mkdir ocr_input
    echo [提示] 已创建 ocr_input 文件夹，请把需要 OCR 识别硬字幕的视频放进去后重新运行
    pause
    exit /b 0
)

REM 在后台静默启动 Ollama（彻底隐藏调试日志，保持界面干净）
tasklist /fi "imagename eq ollama.exe" 2>nul | findstr /i "ollama.exe" >nul
if errorlevel 1 (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'D:\Dev\ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden"
)

REM 激活虚拟环境并运行
call venv\Scripts\activate.bat
python pipeline_ocr.py
echo.
echo 处理完毕，按任意键关闭窗口...
pause >nul
