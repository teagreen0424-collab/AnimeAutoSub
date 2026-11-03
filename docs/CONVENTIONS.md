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
