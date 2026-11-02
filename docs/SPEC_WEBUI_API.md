# SPEC-001: AnimeAutoSub WebUI API 契约与接口设计规范

- **状态**: 提议中 / 待 PO 确认 (Proposed for Review)
- **版本**: v1.0.0
- **基础路径**: `http://127.0.0.1:8000/api`
- **协议标准**: HTTP/1.1 (支持 HTTP 206 Partial Content) + SSE (Server-Sent Events)

---

## 一、 通用交互规范与响应结构

### 1. 通用响应结构
所有非流式、非媒体二进制响应，统一使用标准 JSON 包装对象：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```
- `code`: 状态码。`0` 表示完全成功；非 `0` 为业务错误码（参见末尾错误码章节）。
- `message`: 提示信息。成功时为 `"success"`；失败时为人类可读的具体原因。
- `data`: 业务载荷对象。若无返回数据则为 `null`。

### 2. 媒体流与单帧响应
- 视频流端点：返回 `Content-Type: video/mp4`，支持 `Range` 请求头并返回 `HTTP 206 Partial Content`。
- 单帧渲染端点：返回 `Content-Type: image/jpeg`，缓存头设为 `Cache-Control: no-cache`。
- SSE 管道端点：返回 `Content-Type: text/event-stream; charset=utf-8`，长连接保持。

---

## 二、 端点全集详细契约 (API Endpoints)

### 1. 任务管理 (Task Management)

#### 1.1 创建新任务
- **端点**: `POST /api/tasks`
- **说明**: 录入视频源（支持本地绝对文件路径或分片上传后的文件标识），设定语言与处理模式，生成唯一 `task_id` 并初始化目录及 `manifest.json`。
- **请求体 (application/json)**:
  ```json
  {
    "video_path": "E:/translate/input/simulated_ko_fansub_1080p.mp4",
    "lang": "ko",
    "mode": "ocr",
    "title": "韩语1080p合成测试片"
  }
  ```
  - `video_path`: string (必填，本地母片绝对路径或临时上传路径)
  - `lang`: string (必填，支持 `"ja"` | `"ko"`)
  - `mode`: string (必填，支持 `"ocr"` [硬字幕提取] | `"asr"` [语音识别])
  - `title`: string (选填，任务显示别名)
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "task_id": "task_20261101_193000_a1b2",
      "status": "CREATED",
      "lang": "ko",
      "mode": "ocr",
      "work_dir": "E:/translate/work_tasks/task_20261101_193000_a1b2",
      "created_at": "2026-11-01T20:00:00Z"
    }
  }
  ```

#### 1.2 获取任务列表
- **端点**: `GET /api/tasks`
- **说明**: 扫描工作目录或内存索引，返回所有任务的概览列表。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "total": 3,
      "tasks": [
        {
          "task_id": "task_20261101_193000_a1b2",
          "title": "韩语1080p合成测试片",
          "lang": "ko",
          "mode": "ocr",
          "status": "COMPLETED",
          "current_stage": "verify_metrics",
          "progress_percent": 100,
          "has_output_video": true,
          "created_at": "2026-11-01T19:30:00Z",
          "updated_at": "2026-11-01T19:35:12Z"
        }
      ]
    }
  }
  ```

#### 1.3 获取任务详情与流水线状态
- **端点**: `GET /api/tasks/{task_id}`
- **说明**: 读取该任务的 `manifest.json`，返回各个 Stage 的详细运行记录与耗时账本。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "task_id": "task_20261101_193000_a1b2",
      "status": "COMPLETED",
      "stages": [
        {
          "name": "ocr_extract",
          "status": "COMPLETED",
          "elapsed_seconds": 12.35,
          "skipped": false,
          "products": ["ocr_raw.json", "ocr_rects.json"]
        },
        {
          "name": "translate",
          "status": "COMPLETED",
          "elapsed_seconds": 25.10,
          "skipped": false,
          "products": ["chinese.json"]
        },
        {
          "name": "layout_ass",
          "status": "COMPLETED",
          "elapsed_seconds": 0.45,
          "skipped": false,
          "products": ["subtitle.ass", "subtitle.srt"]
        },
        {
          "name": "burn_subtitles",
          "status": "COMPLETED",
          "elapsed_seconds": 8.12,
          "skipped": false,
          "products": ["output.mp4"]
        }
      ],
      "quality_metrics": {
        "max_mask_area_ratio": 0.147,
        "area_criterion_met": true,
        "rejected_count": 0
      }
    }
  }
  ```

#### 1.4 启动/恢复流水线
- **端点**: `POST /api/tasks/{task_id}/start`
- **说明**: 将任务投递至 GPUJobQueue 进入排队执行。若为中断后重试，利用三元组缓存自动秒级跳过已完成 Stage。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "task_id": "task_20261101_193000_a1b2",
      "status": "QUEUED"
    }
  }
  ```

#### 1.5 安全取消任务
- **端点**: `POST /api/tasks/{task_id}/cancel`
- **说明**: 主动中止流水线执行，强制通知子进程终止，释放 GPU 租约，并通知 Ollama 卸载显存。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "task_id": "task_20261101_193000_a1b2",
      "status": "CANCELLED",
      "gpu_released": true
    }
  }
  ```

---

### 2. 实时进度与日志推送 (SSE Event Stream)

- **端点**: `GET /api/tasks/{task_id}/events`
- **说明**: 基于标准 Server-Sent Events (SSE) 持续向前端单向推送阶段推进与实时日志。
- **请求头要求**: `Accept: text/event-stream`
- **响应事件结构**:
  - **事件类型 1: `stage_change` (阶段流转)**
    ```text
    event: stage_change
    id: 101
    data: {"stage": "ocr_extract", "status": "RUNNING", "progress": 0.35, "message": "正在执行 OCR 识别 (35/100 帧)"}
    ```
  - **事件类型 2: `stage_log` (实时文本日志)**
    ```text
    event: stage_log
    id: 102
    data: {"stage": "translate", "level": "INFO", "text": "[翻译进度] 15/23 (65%) [约剩 0.2 分钟]"}
    ```
  - **事件类型 3: `task_complete` (全流水线完成)**
    ```text
    event: task_complete
    id: 103
    data: {"status": "COMPLETED", "output_video": "/api/tasks/task_20261101_193000_a1b2/video?type=output"}
    ```
  - **事件类型 4: `task_error` (异常中断)**
    ```text
    event: task_error
    id: 104
    data: {"stage": "ocr_extract", "error_code": 50001, "error_message": "CUDA Execution Provider error: out of memory"}
    ```

---

### 3. 流媒体切片与同源单帧渲染 (Media & Preview)

#### 3.1 视频分片流传输 (HTTP Range)
- **端点**: `GET /api/tasks/{task_id}/video`
- **查询参数**:
  - `type`: string (选填，`"origin"` 返回原始未压制母片；`"output"` 返回压制成片，默认 `"origin"`)
- **请求头支持**:
  - `Range: bytes=0-1048575`
- **响应头规范**:
  ```http
  HTTP/1.1 206 Partial Content
  Content-Type: video/mp4
  Content-Range: bytes 0-1048575/74033152
  Content-Length: 1048576
  Accept-Ranges: bytes
  ```
- **价值**: 浏览器 `<video>` 原生进度条拖拽立即平滑响应，拖动无白屏卡死。

#### 3.2 服务端同源单帧对比渲染 (核心验收要求，M1 修正)
- **端点**: `GET /api/tasks/{task_id}/preview_frame`
- **说明**: 使用 FFmpeg 服务端以完全相同的 libass 压制参数对指定时间戳进行单帧渲染，确保与最终成片逐像素同源。
- **渲染命令规则 (M1 规范)**:
  - 必须采用精确 Seek 格式（`-ss` 置于 `-i` 之后）：
    `ffmpeg -y -i input.mp4 -ss {T} -vf "ass='{task_dir_abs}/subtitle.ass'" -vframes 1 -f image2 -q:v 2 pipe:1`
  - 杜绝关键帧快进漂移（快进 seek 易导致字幕时间与画面关键帧错位）。
  - **服务端缓存**: 缓存 Key = `sha256(ass文件内容) + "_" + str(round(timestamp, 2))`，内存/磁盘缓存命中则直接返回 JPEG 字节流（<5ms）。
  - **前端节流控制**: 前端拖动时间轴时必须做 $\ge 150\text{ ms}$ 防抖节流，并在发起新请求前使用 `AbortController.abort()` 强制取消上一次未完成的渲染请求。
- **查询参数**:
  - `timestamp`: float (必填，时间戳，单位：秒，如 `14.25`)
  - `mode`: string (选填，`"burn"` 渲染带字幕与遮罩成片帧；`"origin"` 渲染纯净母片帧，默认 `"burn"`)
- **响应**: `Content-Type: image/jpeg`（二进制图片）
- **性能指标**: 服务端未命中缓存响应耗时约 $100\sim 300\text{ ms}$，缓存命中 $\le 5\text{ ms}$。

---

### 4. 字幕审阅、编辑与增量重渲染 (Subtitle Editing & Rerender)

#### 4.1 获取当前字幕条目列表
- **端点**: `GET /api/tasks/{task_id}/subtitles`
- **说明**: 读取当前已生成的字幕条目（包含原始语言文本、中文翻译、时间区间、置信度与拒识状态）。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "total": 23,
      "items": [
        {
          "index": 1,
          "start": 1.39,
          "end": 2.05,
          "source_text": "안녕하세요.",
          "target_text": "大家好。",
          "confidence": 0.98,
          "is_rejected": false,
          "rejection_reason": null
        },
        {
          "index": 7,
          "start": 21.70,
          "end": 24.46,
          "source_text": "민수 형, 오늘 저녁에 시간 있어?",
          "target_text": "敏秀哥，今天晚上有空吗？",
          "confidence": 0.96,
          "is_rejected": false,
          "rejection_reason": null
        }
      ]
    }
  }
  ```

#### 4.2 保存字幕修改 (编辑 3 行对白)
- **端点**: `PUT /api/tasks/{task_id}/subtitles`
- **说明**: 用户在前端修改了若干行字幕后提交保存，后端直接原子更新工作目录下的 `chinese.json` 并标记下游 `layout_ass` 与 `burn_subtitles` 需要更新。
- **请求体 (application/json)**:
  ```json
  {
    "updates": [
      {
        "index": 7,
        "target_text": "敏秀哥，今晚有空一起吃饭吗？"
      }
    ]
  }
  ```
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "updated_count": 1,
      "requires_rerender": true
    }
  }
  ```

#### 4.3 增量快速重渲染 (Rerender)
- **端点**: `POST /api/tasks/{task_id}/rerender`
- **说明**: **核心性能优化机制**。跳过耗时漫长的 OCR/ASR（数分钟）与翻译阶段，**仅在 5~10 秒内增量执行 `layout_ass` (排版生成 ASS) 与 `burn_subtitles` (FFmpeg 压制)**。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "task_id": "task_20261101_193000_a1b2",
      "status": "RERENDERING",
      "skipped_stages": ["ocr_extract", "translate"],
      "executing_stages": ["layout_ass", "burn_subtitles"]
    }
  }
  ```

#### 4.4 导出完成产物
- **端点**: `GET /api/tasks/{task_id}/export`
- **查询参数**:
  - `format`: string (选填，`"mp4"` [仅视频] | `"ass"` [仅字幕] | `"srt"` [仅SRT] | `"zip"` [全套打包]，默认 `"mp4"`)
- **响应**: 文件下载流（带 `Content-Disposition: attachment; filename=...`）。

---

### 5. 系统健康与硬件资源监控 (System & GPU)

#### 5.1 查询 GPU 与队列状态
- **端点**: `GET /api/system/gpu`
- **说明**: 实时读取显存与队列独占情况，供前端顶部仪表盘显示。
- **成功响应 (200 OK)**:
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {
      "gpu_name": "NVIDIA GeForce RTX 4060",
      "vram_total_mb": 8188,
      "vram_used_mb": 6038,
      "vram_free_mb": 2150,
      "vram_utilization_percent": 73.7,
      "active_task_id": "task_20261101_193000_a1b2",
      "queue_length": 0
    }
  }
  ```

---

## 三、 统一业务错误代码表 (Error Codes)

| 错误码 | HTTP 状态 | 错误标识符 | 含义与处置对策 |
| :--- | :--- | :--- | :--- |
| `0` | 200 | `SUCCESS` | 请求完全成功 |
| `40001` | 400 | `INVALID_PARAMS` | 请求参数缺失或格式错误（如非法的语言代码） |
| `40002` | 404 | `FILE_NOT_FOUND` | 输入的视频路径在服务器上不存在或不可读 |
| `40003` | 507 | `DISK_SPACE_INSUFFICIENT` | 工作盘可用空间低于 2.0GB 门禁限制，拦截写入 |
| `40004` | 409 | `TASK_CONFLICT` | 任务当前处于排队或执行中，禁止重复启动 |
| `40005` | 400 | `TASK_NOT_CANCELLABLE` | 任务已处于完成或中止终态，无需取消 |
| `50001` | 500 | `STAGE_EXECUTION_FAILED` | 流水线阶段内部抛出异常（如 OCR/FFmpeg 报错） |
| `50002` | 500 | `WORKER_KILLED` | Worker 进程异常退出，触发断点恢复待命状态 |
| `50003` | 503 | `GPU_LEASE_TIMEOUT` | 等待 GPU 租约超时（超过指定门限），系统自动保护 |
