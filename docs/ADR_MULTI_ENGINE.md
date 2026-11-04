# 架构决策记录 (ADR) · 官方 API 翻译分支与多引擎架构

- **状态**: 已接受 (Accepted)
- **日期**: 2026-11-04
- **作者**: Antigravity Autonomous Agent
- **适用范围**: `core/stages/translate.py`, `core/translation_engine.py`, `lang/`, `web/`, `config/`

---

## 1. 背景与问题定义 (Context & Problem Statement)

AnimeAutoSub 原有架构深度绑定本地 Ollama + Sakura-14B 翻译链路。本地 Sakura 具备无内容审查、离线运行、完全私密的优势，但受限于个人工作站显存（RTX 4060 8GB），仅能加载 4-bit 量化小模型，在复杂定语从句、高级敬语层级、影视双关语及长线语义连贯性上存在上限。

与此同时，以 DeepSeek-V3、OpenAI GPT-4o-mini、Moonshot 等为代表的官方云端大模型 API 在翻译文学性、长上下文推理及语境重构方面表现优异，且单任务成本极低（每千句仅数角钱）。然而云端商业 API 普遍具备内容安全审查机制（Content Moderation / Safety Filter），在面对特定限制级或敏感影视片源时会直接拒答。

**核心诉求**:
为字幕流水线构建一条**官方 API 翻译分支**，与本地 Sakura 引擎并存。
- **本地引擎**: 保障“能跑”，无审查兜底；
- **官方 API**: 保障“跑得好”，专攻正规影视文化作品（电视剧、电影、动画、纪录片）；
- 两条链路按任务显式选择，各司其职，互不影响。

---

## 2. 关键架构决策 (Architectural Decisions)

### 决策一：单 OpenAI 兼容协议适配器 (Single OpenAI-Compatible Adapter)
- **决策**:
  只实现一个统一的 OpenAI Chat Completions 协议适配器 (`core/translation_engine.py`)，不针对 Anthropic、Gemini 等开发专有客户端。
- **理由**:
  1. 目前市面主流中文大模型提供商（DeepSeek、Moonshot、智谱 GLM、通义千问、Kimi、OpenRouter、SiliconFlow、Ollama）均原生提供或兼容 OpenAI `/v1/chat/completions` REST 规范；
  2. 极简抽象，零额外重型 SDK 依赖（无需 `pip install openai`，仅需标准 `requests` 或内置 HTTP 客户端），完全符合轻量化与可解释性原则；
  3. 配置外置化（`config/engines.json`），用户仅需更换 `api_url` 与 `model_name` 即可接入任意服务商，无需修改任何代码。
- **放弃方案**:
  - 放弃为 Anthropic Claude / Google Gemini 编写专门协议适配层（v1 不为非兼容的少数派增加冗余抽象，保留规范扩展点即可）。

### 决策二：日韩双语云端影视 Prompt 与本地 Prompt 物理隔离
- **决策**:
  在 `lang/ja.py` 与 `lang/ko.py` 中新增云端专用 Prompt 构建器（`build_cloud_japanese_prompt` / `build_cloud_korean_prompt`），将云端 Prompt 与本地 Sakura 的轻小说字典格式 Prompt 严格隔离。
- **理由**:
  1. 本地 Sakura 模型经过轻小说/ACG 特定格式微调，其对特定标记符（如 `->` 字典格式、特定角括号）有强依赖；
  2. 云端大模型具备通识理解与长上下文重构能力。影视字幕要求：口语自然、根据语境补全主语、避免机器腔敬语、遵循屏幕阅读速度（单行汉字 ≤ 20 字）；
  3. 针对日语敬语与省略主语，以及韩语敬平语（존댓말/반말）对等转换设计了专属的 System Prompt 与影视翻译约束。
- **放弃方案**:
  - 放弃向云端 API 沿用 Sakura 的短提示词结构，避免云端大模型输出机械直译。

### 决策三：指纹三元组防穿透 (Fingerprint Invalidation Guarantee)
- **决策**:
  在 `TranslateStage.fingerprint()` 计算中，强制纳入 `engine_id`、`base_url`、`prompt_version`、`model_name`。
- **理由**:
  1. 流水线依赖 `manifest.json` 的三元组（参数指纹 + 上游产物哈希 + 工具版本）进行增量秒级跳过；
  2. 若指纹中缺少引擎与提示词版本标识，切换引擎后上游产物未变，流水线将误判“已完成”，导致静默复用几个月前的旧引擎译文；
  3. 增设针对性单元测试 `test_fingerprint_strictly_changes_on_engine_switch` 严格锁死这一行为。

### 决策四：拒答三形态识别与累计比例熔断 (Three-form Refusal Detection & Circuit Breaker)
- **决策**:
  设计专门的 `is_refusal_response()` 过滤器，全方位捕获：
  1. **形态一（文本语义拒绝）**: 正则匹配 polite refusal 话术（“抱歉/对不起/作为AI...无法协助/政策限制/提供翻译”等）；
  2. **形态二（结构化原因拒绝）**: 响应结构中 `finish_reason == "content_filter"` 或 `"safety"`；
  3. **形态三（HTTP 层安全阻断）**: HTTP 400 / 403 并在响应体中返回 policy violation 报错。
  流水线中若检测到拒答：
  - **绝不将拒答话术写入 `chinese.json`**（置空并记录警告）；
  - **累计拒答率 > 20% 立即中止任务**，明确向用户抛出异常并给出“建议切换至本地 Sakura-14B 引擎”的可操作指引。
- **放弃方案**:
  - 放弃将拒答内容直接作为译文上屏（严重影响观影体验与字幕成片质量）。

### 决策五：绝对禁止自动降级 (Zero Auto-Fallback)
- **决策**:
  当官方云端 API 发生拒答、网络超时或鉴权失败时，流水线直接报错中止，**绝对不自动降级到本地 Sakura**。
- **理由**:
  1. 影视字幕风格一致性至关重要。如果在同一部片子中前半段是 DeepSeek 影视口语译风，中间因网络波动或内容敏感突然变成 Sakura 轻小说译风，译名、人称、语气将彻底混乱，用户极难定位与排查；
  2. 失败就是失败，应当如实报告，把决策权留给用户。

### 决策六：严格密钥脱敏与零明文外露 (Strict Secret Redaction)
- **决策**:
  1. `config/engines.json` 纳入 `.gitignore`，版本库仅保留脱敏模板 `config/engines.example.json`；
  2. 密钥仅支持通过环境变量（如 `DEEPSEEK_API_KEY`）或未跟踪文件（`config/*_key.txt`）读取；
  3. 前端 UI 与 API 接口一律使用掩码（如 `sk-****abcd`），严禁返回明文；
  4. 核心工具注册脱敏函数 `redact_secrets()`，在流水线日志、异常抛出、`manifest.json` 记录前对密钥进行全局脱敏；
  5. 严禁在 WebUI 前端提供保存密钥的输入框，杜绝新增泄露攻击面。

### 决策七：预算估算、硬上限与广播播报 (Cost Estimation & Hard Cap)
- **决策**:
  1. 前端新建任务弹窗中：选云端引擎时根据预估字数动态展示参考费用，选本地引擎时自动隐藏费用行；
  2. 运行时配置 `hard_cost_cap`（默认 5.0 元人民币/单任务），单任务累计超过阈值立即安全熔断，防止无限循环重试造成资费损失；
  3. 流水线每翻译 20 句广播一次已消耗 Token 与累计估算费用，并在任务详情页和 `manifest.json` 中完整沉淀用量账单。

### 决策八：云端引擎跳过 GPU 租约 (Zero GPU Lease for Cloud API)
- **决策**:
  云端引擎配置 `requires_gpu: false`。在 `TranslateStage.requires_gpu()` 中根据当前选定的 `engine_id` 动态返回 `False`。
- **理由**:
  云端 API 不占用本地显存，无需与 OCR、ASR、本地渲染争抢 GPU 独占租约，避免无谓阻塞本地任务队列。

---

## 3. 评测与基准体系 (Benchmark Architecture)

为避免依赖真实视频抽帧的高额开销与噪音，专门建立纯文本影视对白基准语料体系：
- 语料目录: `bench/corpus/film_ja_dialogue.json` (日文) 与 `bench/corpus/film_ko_dialogue.json` (韩文)；
- 语料规模: 各 120 句，覆盖 10 大影视真实难点分类（敬语、省略主语、口语语气词、文化特色词、长定语从句、专有名词、双关与梗、时间数字、情感浓度、字数受限）；
- A/B 对比工具: `bench/run_translation_ab.py` 自动生成机器指标分析报告及并排对比表（`bench/corpus/ab_report_ja.md`, `bench/corpus/ab_report_ko.md`），供人工 10 分钟快速审校。

---

## 4. 后续演进建议 (Future Evolution)

1. 若后续业务需要接入非兼容协议平台（如 Azure OpenAI 特殊鉴权、AWS Bedrock），可通过扩展 `core/translation_engine.py` 中的 `EngineConfig.type` 分支实现；
2. 术语表（Glossary）在云端影视 Prompt 中已做注入支持，未来可在 WebUI 任务配置弹窗中开放用户自定义人名词典的快捷挂载。
