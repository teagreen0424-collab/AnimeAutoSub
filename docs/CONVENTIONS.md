# AnimeAutoSub · 工程研发与配置落地规范 (CONVENTIONS.md)

> **制定版本**: v1.0  
> **核心宗旨**: 杜绝配置假落地、静默降级与未经验证的假设，确立工程确定性与实测闭环原则。

---

## 一、配置读回与真实生效校验规范 (Readback Verification Rule)

### 1.1 核心纪律
**任何影响系统性能、正确性、硬件加速或关键算法分支的参数，严禁仅凭“配置字典已设置”或“代码行已执行”就认定生效；必须在底层驱动/引擎会话初始化完成后，从运行时状态中“真实读回”（Readback）其实际值并做强断言，不许只看设置语句。**

### 1.2 违规典型与历史教训
1. **静默回落教训 (L0)**：
   历史代码设置 `Rec.lang_type = "japan"`，但因缺少对应 `ocr_version/model_type`，引擎静默回退至中文默认模型（`PP-OCRv6`）。由于无读回断言，契约测试与调用代码长期误以为在跑日语专用模型。
2. **算子调优停顿教训 (U1)**：
   RapidOCR 默认配置使用 `cudnn_conv_algo_search = "EXHAUSTIVE"`。当输入动态张量尺寸变动时，cuDNN 触发耗时 1.3s~3.8s 的穷举基准测试评测循环。改造为 `"HEURISTIC"` 后，必须从 `session.get_provider_options()['CUDAExecutionProvider']['cudnn_conv_algo_search']` 中直接读回字符串并验证为 `"HEURISTIC"`，彻底杜绝参数被内部覆盖或失效。

### 1.3 标准实现范例
```python
# 1. 注入配置
ocr_params["EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search"] = "HEURISTIC"
engine = RapidOCR(params=ocr_params)

# 2. 预加载底层模型会话
engine._load_det_model()

# 3. 强行读回运行时实际生效的 provider options
det_session = getattr(engine.text_det.session, "session", None)
if det_session is None:
    raise RuntimeError("会话初始化失败！")

cuda_opts = det_session.get_provider_options().get("CUDAExecutionProvider", {})
actual_algo = cuda_opts.get("cudnn_conv_algo_search", "")

# 4. 断言与强校验
if actual_algo != "HEURISTIC":
    raise RuntimeError(f"配置未真实生效！期望 HEURISTIC，实际读回: {actual_algo}")
```

---

## 二、本地回环通信与网络层规范 (Loopback Network Convention)

### 2.1 IPv4 显式绑定原则 (127.0.0.1 vs localhost)
- **事实**: 在 Windows 操作系统下，DNS 将 `localhost` 优先解析为 IPv6 地址 `[::1]`。若服务端（如 Ollama）仅监听 IPv4，客户端（如 Python `requests`）每次发起新请求均会遭受 Windows 内核的 **2.0 秒 TCP SYN 重传超时**，随后才回落至 IPv4。
- **纪律**: **流水线内所有调用本地服务的 URL（包括 Ollama、Whisper、中间件 API），必须严格写死 `http://127.0.0.1:<port>`，严禁在任何配置文件或请求代码中使用 `localhost`。**

### 2.2 连接池复用原则 (Session Reuse)
- 任何批量发起 HTTP 推理/转写请求的模块，必须全局复用 `requests.Session()`，启用 HTTP Keep-Alive 连接池，严禁在循环内重复调用裸 `requests.post()` / `requests.get()`。

---

## 三、OCR 文本清洗与智能截断规范 (OCR Text Sanitization Convention)

### 3.1 局部切除与整句拒识界限
1. **局部切除 (Salvage)**：
   当识别文本主体为正常对话，仅在边缘或局部夹杂 OCR 幻觉乱码（如大写英文串、时间戳纯数字、括号乱码）时，必须切除乱码片段，保留前后有效文本并拼接后送翻。
2. **整句拒识 (Reject)**：
   仅当切除后的有效文本长度不足原长度的 **40% ~ 45%**，或有效字数不足 3 字符时，方可整句拒识留空。
3. **断句状态客观标注 (Truncation Transparency)**：
   若原文本身在画面边缘被截断（如停留在动词未连词），翻译模型输出半句为忠实翻译，**严禁脑补补全**。且在质检报告中必须如实标记为 `incomplete_translation = true`，不得列入无瑕疵的“完美修复”。

---

## 四、测试与调试命令行规范 (CLI Testing & PowerShell Escaping Convention)

### 4.1 Windows PowerShell 下 curl POST JSON 引号剥离陷阱
- **事实与根因**:
  在 Windows PowerShell 环境下直接执行 `curl.exe -s -X POST http://127.0.0.1:8000/api/... -H "Content-Type: application/json" -d '{"key": "value"}'` 时，PowerShell 在向底层原生进程传递参数之前会解析并剥离所有单/双引号。最终服务端接收到的原始 Body 变为 `{key: value}`，直接导致服务端的 `json.loads` 或 FastAPI / Starlette `request.json()` 抛出 `json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes`，并返回 HTTP 500 内部服务错误。
- **排查误导教训**:
  该异常极其隐蔽，极易误导排查方向，让人误以为服务内部路由或业务逻辑崩溃，花费大量时间排查服务端代码。

### 4.2 强制规范与标准测试范式
1. **本机命令行 curl 测试 POST JSON**:
   - 严禁在 PowerShell 中使用直接内联的 `-d '{...}'` 或 `-d "{\"key\": \"val\"}"`；
   - 必须将 JSON 写入临时文件，使用 `--data-binary '@payload.json'`（注意在 PowerShell 中 `@` 必须用单引号包裹 `'@...'`，否则会被 PowerShell 误判为变量 Splatting 运算符）：
     ```powershell
     # 写入标准 JSON 文件
     '{"video_path": "ocr_input/sample.mp4"}' | Out-File -Encoding utf8 payload.json
     # 使用 --data-binary 避免 shell 剥离引号 (注意 '@payload.json' 必须加引号)
     curl.exe -s -X POST "http://127.0.0.1:8000/api/tasks" -H "Content-Type: application/json" --data-binary '@payload.json'
     ```
2. **自动化脚本与回归测试**:
   - 优先使用 Python `requests.post(..., json={...})` 或 FastAPI `TestClient(app).post(..., json={...})`，由底层库严密控制请求头与序列化字节流，杜绝 Shell 解析干扰。

---

## 五、生产运维与防中断操作纪律 (Production Operations & Anti-Interruption Discipline)

### 5.1 事故溯源与沉痛教训
- **典型事故 (2026-11-03 12:51)**：
  用户在生产线上提交了长视频任务 `work_20261103_125130_37215-1080p`（34.4 分钟片源），OCR 正在高负载提取字幕。开发运维人员为验证新提交的 Z7/Z8 功能，未经查询直接在本机执行了强杀旧进程与重启操作，导致用户跑至 1.5% 的任务直接被强制中断报废。
- **事故本质**：**“为了验证次要功能，鲁莽中断了用户正在使用的主线业务”**。

### 5.2 铁律一：在途任务预检原则 (Pre-flight Task Check)
- **纪律**：**凡是会中断服务进程的操作（包括但不限于重启服务、杀端口、跑基准压测 Benchmark、覆盖前端静态文件），执行前必须显式查询当前是否有在途运行或排队的任务！**
- **自检手段**：
  1. 脚本级：在停止或启动前执行 `python -m web.app --check-running`，若返回非 0（退出码 2）且提示有在途任务，严禁擅自直接终止，必须向用户明确确认或等待任务完成；
  2. 接口级：调用 `GET http://127.0.0.1:8000/api/system/running_check`，检查 `has_running` 是否为 `false`；
  3. 严禁使用裸 `Stop-Process -Force` 或 `taskkill /f /im python.exe` 盲目杀进程。

### 5.3 铁律二：验证与生产隔离原则 (Port & Sandbox Isolation)
- **纪律**：**任何功能验收、调优实验与自动化单测，严禁侵入并中断线上默认 8000 端口服务！**
- **操作范式**：
  1. **单元测试与回归测试**：一律使用 FastAPI `TestClient(app)` 进行内存沙箱级测试，杜绝任何物理端口占用与线上冲突；
  2. **临时功能或端到端验证**：若必须启动真实 HTTP 服务，必须指定独立隔离端口（如 `python -m web.app --port 8099 --no-browser`），验证完毕后立即释放，绝不动线上 8000 端口。

### 5.4 铁律三：异常中断透明打标与断点续跑保障 (Interrupted vs Canceled)
- **纪律**：若发生不可抗力导致的服务中断（系统重启、显式 `--force` 维护）：
  1. 任务在 `manifest.json` 中必须标记为 `status = "interrupted"` / `is_interrupted = true`，**严禁标记为用户主动取消的 `canceled`**；
  2. WebUI 界面必须明确呈现 `⏸ 中断` 药丸，且必须点亮 `▶ 恢复` 操作按钮；
  3. 恢复启动时必须根据三元组账本，自动秒级跳过已完成阶段，从中断点恢复流水线。

### 5.5 铁律四：自检验证与零破坏硬规则 (Verification Protocol & Zero Disruption)
- **警示与教训**:
  严禁出现“为了验证‘防中断’机制，又把用户正在跑的在途任务中断一次”的荒谬操作。开发自测与验收流程本身必须百分之百服从运维纪律，将自身的验证行为纳进自己写的纪律中。
- **强制执行硬规则**:
  1. 在本机启动 WebUI、执行任何验收验证前，**必须先执行**:
     ```powershell
     python -m web.app --check-running
     ```
  2. **红线禁令**:
     - **若返回退出码 2（检测到在途任务），必须原地等待任务完成，严禁传入 `--force`，严禁杀端口，严禁擅自重启接管！**
     - 只有当退出码为 0（服务空闲或离线）时，才允许启动新实例或执行维护。
  3. 若必须在任务执行期间进行代码调试或接口回归，**必须且只能使用 `TestClient` 内存沙箱或隔离端口（`--port 8099`）**，绝对不许触碰正在服务用户的生产实例。


---

## 六、密钥与外部 API 纪律 (Secrets & External API Discipline)

### 6.1 密钥零泄漏五处铁律 (Strict Secret Redaction)
- **绝对禁令**：API Key 与敏感凭据**绝不许**以任何明文形式出现在以下 5 个位置：
  1. **Git 仓库**：`config/engines.json`、`config/*_key.txt`、`.env` 必须严格列入 `.gitignore`，版本库中只允许提交示例脱敏模板 `config/engines.example.json`；
  2. **日志文件**：`pipeline.log`、控制台输出、异常 Traceback 打印前必须统一经 `core.translation_engine.redact_secrets()` 过滤；
  3. **产物清单**：`manifest.json`、`chinese.json`、`task_meta.json` 中禁止记录密钥明文，只允许记录 `engine_id` 与脱敏配置；
  4. **API 接口响应**：`GET /api/system/settings`、`GET /api/system/engines`、`GET /api/tasks/{id}` 等响应中，密钥字段必须使用掩码（如 `sk-****4f2a`）；
  5. **前端代码与 DOM**：静态 HTML、JavaScript 文件或浏览器渲染的 DOM 元素中，禁止直接暴露、内联注入或提供不安全的明文输入框。

### 6.2 离线化与单元测试安全 (Offline & Mock-First Testing)
- **纪律**：**严禁在单元测试和日常自动化测试中发起对外部真实商业 API 的带凭据扣费请求！**
- **规范**：
  1. 所有针对云端翻译分支的自动化测试（如 `test_translation_engines.py`、`test_webui_engines.py`）必须使用 `unittest.mock.patch` 或本地隔离沙箱模拟网络响应与 Usage 消耗；
  2. 严禁因为单测运行而消耗真实用户的账户额度，保障在无网络连接、未配置 API Key 的离线环境下所有测试均能 100% 稳定运行。

### 6.3 云端引擎 GPU 租约隔离 (Zero GPU Lease for Cloud API)
- **纪律**：官方云端 API 引擎必须显式声明 `requires_gpu: false`。
- **规范**：
  1. `TranslateStage` 阶段在选定云端 API 引擎时，严禁请求 `acquire_gpu_lease()` 独占锁；
  2. 云端 API 的网络并发与本地 OCR、ASR、视频压制互不挤占显存，保障本地 GPU 资源的高效利用。

### 6.4 拒答与失败处理铁律 (Zero Auto-Fallback & Refusal Protection)
- **纪律**：
  1. **严禁自动静默降级 (Zero Auto-Fallback)**：云端 API 发生拒答、网络不可达或超时报错时，必须如实向用户报错中止，严禁擅自自动 fallback 回本地 Sakura 引擎，防止同一片源中字幕译风、人称断层撕裂；
  2. **拒答话术绝不上屏**：严格检测“抱歉我无法协助”等内容审查拒答话术，一旦命中绝不写进 `chinese.json`；若累计拒答率超过 20%，立即触发任务熔断，并向用户提供明确的改选建议。
