@echo off
chcp 65001 >nul
echo.
echo ============================================
echo   日漫全自动中文字幕流水线 - 环境安装
echo ============================================
echo.

REM ======== 所有缓存/模型存放到 D:\Dev，不占 C 盘 ========
set HF_HOME=D:\Dev\huggingface
set TORCH_HOME=D:\Dev\torch
set PIP_CACHE_DIR=D:\Dev\pip_cache
set OLLAMA_MODELS=D:\Dev\ollama\models

if not exist "D:\Dev\huggingface" mkdir "D:\Dev\huggingface"
if not exist "D:\Dev\torch" mkdir "D:\Dev\torch"
if not exist "D:\Dev\pip_cache" mkdir "D:\Dev\pip_cache"
if not exist "D:\Dev\ollama\models" mkdir "D:\Dev\ollama\models"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 创建虚拟环境
echo [1/4] 创建 Python 虚拟环境...
if not exist "venv" (
    python -m venv venv
) else (
    echo   已存在，跳过
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 安装 PyTorch (CUDA 12.1)
echo.
echo [2/4] 安装 PyTorch (CUDA 12.1)...
echo   首次安装约需下载 2-3 GB，请耐心等待...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet

REM 安装其他依赖
echo.
echo [3/4] 安装管线依赖...
pip install -r requirements.txt --quiet

REM 创建文件夹
echo.
echo [4/4] 创建工作目录...
if not exist "input" mkdir input
if not exist "output" mkdir output
if not exist "glossary" mkdir glossary

echo.
echo ============================================
echo   安装完成！
echo ============================================
echo.
echo   所有模型和缓存将存放在 D:\Dev，不会占用 C 盘空间
echo.
echo 接下来你还需要：
echo.
echo   1. 安装 FFmpeg（如果还没装的话）：
echo      下载: https://www.gyan.dev/ffmpeg/builds/
echo      建议解压到 D:\Dev\ffmpeg，然后把 D:\Dev\ffmpeg\bin 加入系统 PATH
echo.
echo   2. 安装 Ollama：
echo      下载: https://ollama.com/download/windows
echo      安装后，设置系统环境变量 OLLAMA_MODELS=D:\Dev\ollama\models
echo      这样模型文件就不会存到 C 盘
echo.
echo   3. 导入 Sakura 翻译模型（见 README.md 详细步骤）
echo.
echo   4. 把视频放入 input\ 文件夹，双击 run.bat 开始处理！
echo.
pause
