# 🎬 AnimeAutoSub

<div align="center">

**全本地 · 自动化多语言视频字幕提取、大模型汉化与压制工作站**  
*Local-first, Multi-language Anime & Video Subtitle Translation Station*

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Modern%20WebUI-009688.svg)](https://fastapi.tiangolo.com/)
[![CUDA](https://img.shields.io/badge/CUDA-11.8%2B%20%2F%2012.x-76B900.svg)](https://developer.nvidia.com/cuda-toolkit)
[![Ollama](https://img.shields.io/badge/Ollama-Sakura%20LLM-black.svg)](https://ollama.com/)
[![Tests](https://img.shields.io/badge/Tests-28%2F28%20Passing-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[功能特性](#-核心特性) • [快速上手](#-快速上手) • [架构设计](#-架构与目录结构) • [实测性能基线](#-实测性能与质量基线) • [多语言扩展](#-如何扩展一门新语言)

</div>

---

## 💡 为什么选择 AnimeAutoSub？

传统视频汉化脚本往往依赖单次短连接调用在线 API，既无法离线运行，也难以处理压制在画面底部的硬字幕噪点与音画不同步问题。

**AnimeAutoSub** 是一个面向动漫影视与视频的**全流程、工业级离线字幕工程系统**。它将人声分离、ASR 语音转写、ONNX CUDA 硬字幕识别、本地大模型上下文汉化、自适应遮罩排版与全功能 Web 控制台有机结合，全程在用户本地 GPU 上运行，无需将媒体文件上传至任何第三方云端。

---

## ✨ 核心特性

### 1. 双链路提取架构 (Dual-Engine Pipeline)
- **硬字幕提取链路 (Chain B - OCR)**:
  - 搭载 **RapidOCR (ONNX Runtime CUDA)** 加速推理；
  - 创新**稳定平原区中点帧提取算法**，规避片头淡入淡出噪点帧与背景碎屑；
  - **自适应动态遮罩**：根据日/韩文原文几何区域动态生成遮罩（平原区均值面积控制在安全限额内），彻底覆盖外文原字幕，杜绝文字压边或黑边膨胀；
  - 内置 **N5 乱码尾巴拒识过滤**，防止损坏的 ASCII 碎片污染翻译流水线。
- **纯语音识别链路 (Chain A - ASR)**:
  - 集成 **Demucs** 深度学习人声与背景伴奏分离；
  - 结合 **faster-whisper large-v3** 进行高精度本地离线语音转写与时间戳对齐。

### 2. 本地大模型智能汉化 (LLM Translation)
- 适配 **Sakura-14B / Sakura-7B (Qwen2.5)** 轻小说风格精调大语言模型（via Ollama）；
- **TCP 会话连接池与长连接复用**：彻底杜绝每次请求重新握手带来的性能损耗，稳态单句翻译耗时仅 **1.6s**；
- **Prompt 级多行上下文感知**与人称代词自动推断；
- **多语言人名与术语表机制 (`glossary/`)**：严格锁定角色名译名与专有名词映射（如韩文音译名查表消歧与回退保护）。

### 3. 多语言插件化架构 (`lang/`)
- 严格遵循解耦契约，加一门语言改动面 $\le$ 3 个文件；
- **日文插件 (`ja`)**：基于 MeCab 的词性分析、行间分词与排版包装；
- **韩文插件 (`ko`)**：NFKC 标称化、助词粘连与音节截断保护（防止 은/는/이/가/을/를 等被折行切碎）、拟声叠词降噪、敬语与亲属称谓增强 Prompt。

### 4. 现代化全功能 WebUI 工作站 (FastAPI + 原生 ES6)
- **GPU 独占队列管理器**:
  - 防止多任务同时争抢显存导致 CUDA OOM；
  - 实时显示 GPU 利用率、已占用/总显存，支持 3 秒内安全取消任务并主动向 Ollama 发送 `keep_alive: 0` 释放显存至 < 1GB。
- **全屏高精字幕编辑器 (`#screenEditor`)**:
  - 每页 50 行分页浏览，原文与中文译文并列，单元格行内直接改字并即时标记脏状态；
  - **单帧服务端精确预览**: `-i` 精确 seek 配合 libass 渲染，$\ge$ 150ms 防抖节流与 SHA256 磁盘高速缓存，毫秒级即时校验改字后的字幕画面与遮罩效果；
  - **增量重渲染**: 修改字幕后一键重出片，自动跳过 OCR 与翻译阶段，秒级重新排版并压制成片。
- **流媒体点播与全量产物下载**:
  - HTML5 播放器原生支持 HTTP 206 Partial Content 切片拖拽流媒体点播；
  - 任务列表、详情页、编辑器内提供成片 (`output.mp4`)、ASS 字幕、SRT 字幕一键保存与全量产物直下。
- **运行环境只读设置屏 (`#settings`)**:
  - 集中展示端口、Ollama 守护地址、离线模型权重路径、OCR 引擎驱动模式与 Schema v2 规范。

---

## 📊 实测性能与质量基线

> 所有数据均在 Windows 11 + NVIDIA GeForce RTX 4060 (8GB VRAM) 环境下实测固化。

| 评估维度 | 指标参数 | 实测性能 / 质量水平 |
| :--- | :--- | :--- |
| **日文硬字幕链路** | 69 分钟完整番剧素材 | **30.79 分钟** 完成全片（2.25x 实时速度） |
| **日文语音链路** | 21 分钟番剧素材 | **10.9 分钟** 完成全片 |
| **OCR 识别稳态耗时** | 单帧调用 | **160 ms / 次** |
| **大模型翻译单句耗时** | Sakura-14B (Qwen2.5) | **1.6 s / 句** |
| **OCR 识别字符错误率** | 合成素材双行 / 真实母片 | CER **2.6%**（合成）/ **13% ~ 15%**（真实平原区） |
| **人工审计翻译可用率** | 60 句严格盲测真值 | 实用语义口径 **91.7%** / 严格全量 **83.3%** |
| **显存占用** | 运行稳态 / 任务结束释放 | 约 **6.0 GB**（任务结束立即回落至 < 1.0 GB 桌面基线） |

---

## 🚀 快速上手

### 1. 环境准备

1. **操作系统**: Windows 10/11 64-bit 或 Linux x86_64；
2. **显卡**: NVIDIA GPU（显存 $\ge$ 8GB，驱动支持 CUDA 11.8+ 或 12.x）；
3. **系统依赖**:
   - **FFmpeg**: 下载 [FFmpeg Release Essentials](https://www.gyan.dev/ffmpeg/builds/) 并将 `bin` 目录加入系统环境变量 `PATH`；
   - **Ollama**: 下载安装 [Ollama Windows](https://ollama.com/download/windows)；
   - **Python**: 推荐 Python 3.10 或 3.11。

### 2. 导入 Sakura 翻译模型至 Ollama

推荐使用 Sakura-14B 量化模型以获得最佳翻译质量：

```bash
# 从 HuggingFace 下载 Sakura-14B GGUF 权重 (如 sakura-14b-qwen2.5-v1.0-iq4_xs.gguf)
# 创建 Modelfile:
FROM ./sakura-14b-qwen2.5-v1.0-iq4_xs.gguf
PARAMETER temperature 0.1
PARAMETER top_p 0.3
PARAMETER num_ctx 2048

# 导入 Ollama:
ollama create sakura-14b -f Modelfile
```

### 3. 安装项目依赖

```bash
# 建议在独立虚拟环境中安装
python -m venv venv
.\venv\Scripts\activate

# 安装生产依赖
pip install -r requirements.txt
```

### 4. 启动与使用

#### 方案 A：WebUI 图形控制台（推荐）
双击根目录下的 **`启动WebUI.bat`**，或运行：
```bash
python web/app.py
```
浏览器打开 `http://127.0.0.1:8000` 即可进入工作站。
- 点击右上角「+ 新建任务」或直接将片源拖入窗口；
- 支持日/韩双语、OCR/ASR 双模式切换；
- 任务执行完毕后直接在界面上微调字幕、单帧预览并下载成片。

#### 方案 B：命令行批处理
- **硬字幕链路**: 将视频放入 `ocr_input/`，运行 `python pipeline_ocr.py`；
- **语音链路**: 将视频放入 `input/`，运行 `python pipeline.py`。

---

## 🛠 架构与目录结构

```text
AnimeAutoSub/
├── core/                   # 解耦流水线核心
│   ├── stage.py            # 阶段接口契约 (Stage / PipelineContext)
│   └── stages/             # 标准流水线阶段插件
│       ├── audio_extract.py   # 音频提取与人声分离
│       ├── asr_whisper.py     # Whisper 语音识别
│       ├── ocr_extract.py     # RapidOCR 关键帧文字识别
│       ├── ocr_comparator.py  # 稳定平原区识别与 N5 拒识
│       ├── translate_llm.py   # Sakura-14B 大模型汉化
│       ├── layout_ass.py      # 自适应遮罩计算与 ASS/SRT 字幕生成
│       └── render_video.py    # FFmpeg 视频压制与成片产出
├── lang/                   # 多语言插件目录
│   ├── __init__.py         # 语言注册与调度中枢
│   ├── ja/                 # 日语插件 (MeCab 分词与排版)
│   └── ko/                 # 韩语插件 (助词保护、NFKC 净化与提示词)
├── web/                    # 现代化 WebUI
│   ├── app.py              # FastAPI 后端服务
│   ├── queue_manager.py    # 独占 GPU 队列管理器与任务状态机
│   ├── task_manager.py     # 产物扫描与元数据索引
│   └── static/             # 前端单页应用 (ES Modules)
│       ├── index.html      # 主视图结构
│       ├── style.css       # 现代暗色响应式样式
│       └── app.js          # 前端核心状态与渲染交互
├── glossary/               # 专有名词与角色译名术语表
├── tests/                  # 28 项全套自动化单元测试与契约门禁
├── doctor.py               # 运行环境一键体检工具
├── pipeline.py             # 语音链路 CLI 入口
├── pipeline_ocr.py         # 硬字幕链路 CLI 入口
└── requirements.txt        # Python 依赖清单
```

---

## 🧩 如何扩展一门新语言？

AnimeAutoSub 采用完全插件化架构，加一门语言只需创建或修改 **3 个文件**：

1. **新建 `lang/<lang_code>/text_rules.py`**:
   实现分词清洗、标点规整、敏感词降噪与特定的排版保护逻辑；
2. **新建 `lang/<lang_code>/prompts.py`**:
   配置专属系统提示词（如敬语/谦逊语识别、代词对齐规范）；
3. **在 `lang/__init__.py` 中注册该语言**:
   绑定语言代码（如 `zh`、`en`）并编写对应单测。

---

## 🧪 自动化测试套件

项目内置完备的自动化测试套件，全面覆盖算法边界、环境隔离与 Web 接口契约：

```bash
pytest tests/ -v
```

```text
============================= test session starts =============================
collected 28 items

tests/test_adaptive_mask.py::test_adaptive_mask_geometry_and_area PASSED          [  3%]
tests/test_env_isolation.py::test_env_injection_in_clean_subprocess PASSED       [  7%]
tests/test_korean_text_rules.py (7项) ........................................   [ 32%]
tests/test_ocr_comparator.py (7项) ..........................................   [ 57%]
tests/test_ocr_model_contract.py (2项) ......................................   [ 64%]
tests/test_p3_contract.py (4项) ..............................................   [ 78%]
tests/test_p4_contract.py (4项) ..............................................   [ 92%]
tests/test_s_stage_parity.py (2项) ...........................................   [100%]

============================= 28 passed in 24.50s =============================
```

---

## 🤝 贡献与参与

欢迎提交 Issue 和 Pull Request！
- 代码改动请维持现有注释与文档完整性；
- 提交前请运行 `pytest tests/ -v` 确保 28 项自动化测试 100% 通过；
- 新增功能需遵循 `core/stage.py` 阶段契约与解耦要求。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
