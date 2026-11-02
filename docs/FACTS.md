# AnimeAutoSub 事实清单与现状基线 (FACTS.md)

> 生成时间: 2026-10-31  
> 责任人: AnimeAutoSub 总负责工程师  
> 状态: 已现场验证 (基于当前真实代码与硬件环境)

---

## 1. 真实文件树 (排除 venv 与大型模型目录)

工程根路径: `E:\translate`

```text
E:\translate
├── .idea/                           # IDE 配置文件
├── docs/                            # 工程规范与架构文档
│   ├── FACTS.md                     # 本文档 (现状事实与基线)
│   └── STATE.md                     # 状态跟踪与跨会话档案
├── glossary/                        # 术语表目录
│   └── example.json                 # 术语表示例
├── input/                           # [分支A] 音频流水线视频输入目录 (当前空)
├── ocr_input/                       # [分支B] 画面硬字幕流水线输入目录
│   └── 114877-720p.mp4              # 720p 拔作/视觉小说测试样片 (163.2 MB)
├── logs/                            # 分支A 运行日志目录
├── logs_ocr/                        # 分支B 运行日志目录
├── output/                          # 分支A 输出产物目录
│   ├── 408309-1080p/                # 已完成样本目录 (含 audio.wav, vocals.wav, json, ass, srt, mkv, mp4)
│   └── 408847-1080p/                # 中断留存目录
├── ocr_output/                      # 分支B 输出产物目录
│   └── 114877-720p/                 # 已完成样本目录 (含 japanese.json, chinese.json, subtitle.ass, srt, mkv, mp4)
├── config.py                        # 分支A 集中配置文件 (86行)
├── config_ocr.py                    # 分支B 集中配置文件 (84行)
├── pipeline.py                      # 分支A 完整业务执行脚本 (900行)
├── pipeline_ocr.py                  # 分支B 完整业务执行脚本 (717行)
├── doctor.py                        # G0 环境体检与门禁检查脚本
├── setup_sakura14b.py               # Sakura-14B 下载与 Ollama 注册辅助脚本
├── setup_tools.py                   # 基础环境工具下载脚本
├── install.bat                      # 初始化安装批处理 (编码需重整)
├── run.bat                          # 分支A 一键启动批处理
├── run_ocr.bat                      # 分支B 一键启动批处理
├── requirements.txt                 # pip 依赖声明文件 (仅记录了4个库，不全)
└── README.md                        # 旧版说明文档
```

---

## 2. 真实依赖清单 (运行期实测版本)

Python 解释器路径: `E:\translate\venv\Scripts\python.exe` (Python 3.11/3.13 兼容环境)

| 核心组件 | 安装版本 | 硬件加速提供方 / 证据 | 备注 |
| :--- | :--- | :--- | :--- |
| **PyTorch** | `2.5.1+cu121` | `CUDA 12.1` (`torch.cuda.is_available() == True`) | 显存总容量 8.00 GB |
| **torchaudio** | `2.5.1+cu121` | `CUDA 12.1` | 用于 Demucs 音频张量处理 |
| **faster-whisper** | `1.2.1` | `ctranslate2 4.8.4` (CUDA float16) | 语音转写与打轴 |
| **demucs** | `4.1.0` | `torch.cuda` (`htdemucs_ft`) | 人声分离降噪 |
| **onnxruntime-gpu** | `1.31.1` | `['TensorrtExecutionProvider', 'CUDAExecutionProvider']` | RapidOCR 视觉推理引擎 |
| **rapidocr-onnxruntime** | `1.4.4` | ORT CUDAExecutionProvider | 画面硬字幕检测与识别 |
| **opencv-python** | `5.0.0.93` | CPU (cv2) | 抽帧与帧差变动检测 |
| **pysubs2** | `1.8.1` | 纯 Python | ASS / SRT 字幕语法生成 |
| **requests** | `2.34.2` | 网络通信 | Ollama HTTP API 客户端 |
| **FFmpeg** | `N-128198-g37515cfd87` | 本地构建版 (`D:\Dev\ffmpeg\bin\ffmpeg.exe`) | 软解、抽帧、软封 MKV、硬压 MP4 |
| **Ollama** | 独立可执行文件 | `D:\Dev\ollama\ollama.exe` (API 端口 11434) | Sakura-14B 模型托管后端 |

> **关键漏洞记录**: `requirements.txt` 仅声明了 `faster-whisper`, `demucs`, `pysubs2`, `requests`，完全遗漏了 `onnxruntime-gpu`, `rapidocr-onnxruntime`, `opencv-python`。若换机复现会直接阻塞。

---

## 3. 真实入口命令与调用参数

### 3.1 既有入口
- **分支 A（语音流）**:
  - 命令: `call venv\Scripts\activate.bat && python pipeline.py` 或双击 `run.bat`
  - 前置注入: `set HF_HOME=D:\Dev\huggingface`, `set TORCH_HOME=D:\Dev\torch`, `set OLLAMA_MODELS=D:\Dev\ollama\models`
- **分支 B（硬字幕流）**:
  - 命令: `call venv\Scripts\activate.bat && python pipeline_ocr.py` 或双击 `run_ocr.bat`
  - 前置注入: 同上，同时静默启动 `D:\Dev\ollama\ollama.exe serve`
- **体检入口 (新增)**:
  - 命令: `E:\translate\venv\Scripts\python.exe doctor.py`

---

## 4. 关键产物样例

以测试样片 `114877-720p.mp4` 为例，已落盘标准产物：
- `ocr_output/114877-720p/japanese.json` (115 KB):
  ```json
  [
    {
      "start": 122.22,
      "end": 127.36,
      "text": "それでも娘にとっては夫であり、 孫たちにとって は父親だった。"
    }
  ]
  ```
- `ocr_output/114877-720p/chinese.json` (172 KB):
  ```json
  [
    {
      "start": 122.22,
      "end": 127.36,
      "ja": "それでも娘にとっては夫であり、 孫たちにとって は父親だった。",
      "zh": "即便如此，他对于女儿来说是丈夫， 对于孙辈们来说是父亲。"
    }
  ]
  ```
- `ocr_output/114877-720p/subtitle.ass` (202 KB):
  - 头信息标定: `PlayResX: 1920`, `PlayResY: 1080`
  - 遮罩事件行:
    `Dialogue: 0,0:02:02.22,0:02:07.36,Mask,,0,0,0,,{\an7\pos(0,820)\p1\c&H0a0a0a&\1a&H00&}m 0 0 l 1920 0 l 1920 180 l 0 180{\p0}`
  - 文字事件行:
    `Dialogue: 1,0:02:02.22,0:02:07.36,Default,,0,0,0,,{\an2\pos(960,980)}即便如此，他对于女儿来说是丈夫，\N 对于孙辈们来说是父亲。`

---

## 5. 硬编码常量与经验值位置清单

| 文件 | 行号 | 常量名 | 当前值 | 背后硬编码假设 / 隐患 |
| :--- | :--- | :--- | :--- | :--- |
| `config.py` | L22 | `DEMUCS_MODEL` | `"htdemucs_ft"` | 假设显存充裕且追求极致质量；无法低配回退 |
| `config.py` | L27 | `WHISPER_COMPUTE_TYPE` | `"float16"` | 假设 GPU 支持 fp16，无 CPU 动态回退映射 |
| `config.py` | L49 | `SUBTITLE_MAX_LINE_CHARS`| `18` | 假设单行 18 汉字适合所有分辨率；日漫中常用经验值 |
| `config.py` | L75 | `SUBTITLE_FONTSIZE` | `22` | 在 1080p ASS 画布下 22 号极小（与 OCR 的 68 号分裂） |
| `config_ocr.py` | L22 | `OCR_ROI_BOTTOM_PERCENT`| `0.28` | **经验值**：假设字幕严格在视频下 28%（遇非16:9或中置字幕失效） |
| `config_ocr.py` | L25 | `OCR_SAMPLE_FPS` | `2.0` | 假设字幕驻留 ≥ 0.5s，无法自适应快节奏画面 |
| `config_ocr.py` | L28 | `OCR_FRAME_DIFF_THRESH` | `0.025` | **经验值**：2.5% 阈值对微弱渐变背景可能漏检或误判 |
| `config_ocr.py` | L54 | `MASK_TOP` | `820` | **纯经验值**：仅适配当前样片在 1080p 画布下的垂直坐标 |
| `config_ocr.py` | L55 | `MASK_HEIGHT` | `180` | **纯经验值**：仅刚好包住当前样片的双行字，无法自适应单行/三行 |
| `config_ocr.py` | L57 | `SUBTITLE_POS_Y` | `980` | **纯经验值**：强行指定底对齐 Y 轴坐标 |
| `config_ocr.py` | L61 | `SUBTITLE_FONTSIZE` | `68` | **纯经验值**：为匹配当前样片 52px 日文字号而测出 |
| `pipeline_ocr.py`| L537 | `PlayResX / PlayResY` | `1920 / 1080` | ASS 逻辑画布硬编码为 1080p，非 1080p 素材靠播放器缩放 |

---

## 6. 与预期不符的现场发现 (Discrepancy List)

1. **C 盘缓存发生实质泄漏 (违反 K1)**：
   - 实测在 `C:\Users\10932\.cache\huggingface` 发现 321.1 MB 缓存残留（含 Demucs 权重快照与 Xet 日志）。
   - 原因：过去直接在 Python 进程内使用 `os.environ.setdefault()`，但在执行前若某些全局环境未被注入，第三方库（如 huggingface_hub）会自动退回默认缓存目录。
2. **断点续传完全缺乏指纹校验 (严重违反 K4)**：
   - 现存 `translate_segments()` 与 `generate_subtitles()` 仅靠 `if path.exists()` 决定跳过。
   - 用户若在 `config_ocr.py` 中修改字号、提示词、翻译模型甚至术语表，系统直接静默复用旧文件，导致用户“改了配置却毫无反应”。
3. **字号标准在两条流水线间完全分裂**：
   - 分支 A (`config.py`) 字号为 `22`；
   - 分支 B (`config_ocr.py`) 字号为 `68`；
   - 用户在分支 A 产物中会看到过小字体，在分支 B 中则是巨幅字体。
4. **两套配置与管线高度重合却各自独立**：
   - `config.py` 与 `config_ocr.py` 重复定义了 60% 的变量；
   - `pipeline.py` 与 `pipeline_ocr.py` 重复实现了翻译重试、日志、FFmpeg 调用等基础功能。
