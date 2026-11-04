"""
AnimeAutoSub 多引擎与云端 API 翻译架构适配器 (core/translation_engine.py)

硬性契约:
  1. 引擎配置外置 (config/engines.json)，密钥禁止进 Git/日志/前端/产物
  2. 统一 OpenAI 兼容协议适配 (DeepSeek / OpenAI / Moonshot 等)
  3. 拒答三形态识别与累计比例保护 (拒答话术绝不进 chinese.json)
  4. 费用预估、实际 Token 统计与硬上限拦截
  5. 密钥严格自动脱敏 redact_secrets
"""

import os
import re
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 拒答形态 1: 文本关键词/正则匹配
REFUSAL_PATTERNS = [
    re.compile(r"(抱歉|对不起|很遗憾).*?(无法|不能|违规|政策|协助|提供|翻译|满足|回答)", re.IGNORECASE),
    re.compile(r"(作为|身为).*?(AI|人工智能|语言模型).*?(无法|不能|没有|不会)", re.IGNORECASE),
    re.compile(r"(违反|不符合).*?(政策|规定|准则|法律|规范|条款)", re.IGNORECASE),
    re.compile(r"(涉及|包含).*?(敏感|违规|不良|色情|成人|暴力|违法).*?(无法|不能|拒绝)", re.IGNORECASE),
    re.compile(r"I cannot (fulfill|assist|translate|provide)", re.IGNORECASE),
    re.compile(r"I am (unable|not able) to (translate|assist|fulfill)", re.IGNORECASE),
    re.compile(r"I cannot assist with", re.IGNORECASE),
    re.compile(r"as an AI (language )?model[,\s]+I (cannot|am unable)", re.IGNORECASE),
    re.compile(r"(against|violates) (our|the) (safety|content) policy", re.IGNORECASE),
    re.compile(r"content policy violation", re.IGNORECASE),
]

_REGISTERED_SECRETS: set = set()


def register_secret(secret: str):
    """注册需要全局脱敏的敏感字符串 (长度需 >= 6)"""
    if secret and len(secret) >= 6:
        _REGISTERED_SECRETS.add(secret)


def redact_secrets(text: str, extra_secrets: Optional[List[str]] = None) -> str:
    """
    对文本进行全局密钥与敏感信息脱敏，绝不泄漏至日志、异常、前端或产物
    """
    if not text:
        return text

    redacted = str(text)

    # 1. 注册的已知密钥精确替换
    all_secrets = set(_REGISTERED_SECRETS)
    if extra_secrets:
        for s in extra_secrets:
            if s and len(s) >= 6:
                all_secrets.add(s)

    for secret in all_secrets:
        if secret in redacted:
            redacted = redacted.replace(secret, "***REDACTED***")

    # 2. 正则模式脱敏 (常见 API Key 格式)
    # sk- 格式 API Key (OpenAI, DeepSeek, Moonshot 等)
    redacted = re.sub(r'(sk-[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]+([a-zA-Z0-9_\-]{4})', r'\1****\2', redacted)
    # Authorization: Bearer xxx 头信息脱敏
    redacted = re.sub(r'(Bearer\s+)[a-zA-Z0-9_\-\.]{8,}', r'\1***REDACTED***', redacted)

    return redacted


@dataclass
class EngineConfig:
    """翻译引擎结构定义与参数配置"""
    id: str
    name: str
    type: str                         # "ollama" 或 "api"
    api_url: str
    model_name: str
    api_key_env: str = ""
    api_key_file: str = ""
    api_key: str = field(default="", repr=False)  # 避免 repr 泄漏明文
    requires_gpu: bool = False
    temperature: float = 0.1
    top_p: float = 0.3
    context_lines: int = 3
    max_retries: int = 3
    pricing: Dict[str, Any] = field(default_factory=lambda: {
        "input_per_m": 0.0,
        "output_per_m": 0.0,
        "currency": "CNY"
    })
    description: str = ""
    hard_cost_cap: float = 5.0        # 单任务费用硬上限 (单位: 对应币种，默认 5.0 CNY)
    prompt_version: str = "film_v1.0"

    def is_configured(self) -> bool:
        """判定引擎是否已具备调用条件"""
        if self.type == "ollama":
            return True
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    def get_masked_key(self) -> str:
        """返回用于前端安全展示的掩码密钥 (不泄露明文)"""
        if self.type == "ollama":
            return "本地免密 (Ollama)"
        if not self.api_key:
            return "未配置"
        key = self.api_key.strip()
        if len(key) <= 8:
            return "****"
        return f"{key[:3]}****{key[-4:]}"

    def to_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        """序列化输出，默认对密钥脱敏"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "api_url": self.api_url,
            "model_name": self.model_name,
            "requires_gpu": self.requires_gpu,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "context_lines": self.context_lines,
            "max_retries": self.max_retries,
            "pricing": self.pricing,
            "description": self.description,
            "configured": self.is_configured(),
            "masked_key": self.get_masked_key(),
            "hard_cost_cap": self.hard_cost_cap,
            "prompt_version": self.prompt_version
        }


def _resolve_api_key(api_key_env: str, api_key_file: str) -> str:
    """按优先级寻找并加载 API Key (环境变量 -> .env -> key 文件)"""
    # 1. 系统/会话环境变量
    if api_key_env and api_key_env in os.environ:
        val = os.environ[api_key_env].strip()
        if val:
            register_secret(val)
            return val

    # 2. 尝试从 PROJECT_ROOT / ".env" 读取
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == api_key_env:
                        val = v.strip().strip("'\"")
                        if val:
                            register_secret(val)
                            return val
        except Exception:
            pass

    # 3. 尝试从指定密钥文件读取
    if api_key_file:
        key_p = Path(api_key_file)
        if not key_p.is_absolute():
            key_p = PROJECT_ROOT / key_p
        if key_p.exists():
            try:
                val = key_p.read_text(encoding="utf-8").strip()
                if val:
                    register_secret(val)
                    return val
            except Exception:
                pass

    return ""


def load_engine_configs() -> Dict[str, EngineConfig]:
    """从 config/engines.json 或 config/engines.example.json 加载引擎清单"""
    config_file = PROJECT_ROOT / "config" / "engines.json"
    if not config_file.exists():
        config_file = PROJECT_ROOT / "config" / "engines.example.json"

    raw_data = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            logging.warning(f"读取引擎配置文件失败: {e}，将采用内置兜底配置")

    engines_dict = raw_data.get("engines", {})
    configs: Dict[str, EngineConfig] = {}

    # 若未找到任何引擎配置，提供默认标准三项
    if not engines_dict:
        engines_dict = {
            "sakura-14b": {
                "id": "sakura-14b",
                "name": "本地 Sakura-14B (Ollama)",
                "type": "ollama",
                "api_url": "http://127.0.0.1:11434/v1/chat/completions",
                "model_name": "sakura-14b-qwen2.5-v1.0-iq4_xs",
                "requires_gpu": True,
                "temperature": 0.1,
                "top_p": 0.3,
                "context_lines": 5,
                "pricing": {"input_per_m": 0.0, "output_per_m": 0.0, "currency": "CNY"}
            },
            "deepseek-chat": {
                "id": "deepseek-chat",
                "name": "DeepSeek-V3 (官方 API)",
                "type": "api",
                "api_url": "https://api.deepseek.com/v1/chat/completions",
                "model_name": "deepseek-chat",
                "api_key_env": "DEEPSEEK_API_KEY",
                "api_key_file": "config/deepseek_key.txt",
                "requires_gpu": False,
                "temperature": 0.3,
                "top_p": 0.7,
                "context_lines": 3,
                "pricing": {"input_per_m": 1.0, "output_per_m": 2.0, "currency": "CNY"}
            },
            "openai-gpt4o-mini": {
                "id": "openai-gpt4o-mini",
                "name": "OpenAI GPT-4o-mini (官方 API)",
                "type": "api",
                "api_url": "https://api.openai.com/v1/chat/completions",
                "model_name": "gpt-4o-mini",
                "api_key_env": "OPENAI_API_KEY",
                "api_key_file": "config/openai_key.txt",
                "requires_gpu": False,
                "temperature": 0.3,
                "top_p": 0.7,
                "context_lines": 3,
                "pricing": {"input_per_m": 1.1, "output_per_m": 4.4, "currency": "CNY"}
            }
        }

    for eid, edata in engines_dict.items():
        env_var = edata.get("api_key_env", "")
        file_path = edata.get("api_key_file", "")
        loaded_key = edata.get("api_key", "")
        if not loaded_key:
            loaded_key = _resolve_api_key(env_var, file_path)
        else:
            register_secret(loaded_key)

        cfg = EngineConfig(
            id=eid,
            name=edata.get("name", eid),
            type=edata.get("type", "api"),
            api_url=edata.get("api_url", "http://127.0.0.1:11434/v1/chat/completions"),
            model_name=edata.get("model_name", "sakura-14b"),
            api_key_env=env_var,
            api_key_file=file_path,
            api_key=loaded_key,
            requires_gpu=edata.get("requires_gpu", edata.get("type") == "ollama"),
            temperature=float(edata.get("temperature", 0.1)),
            top_p=float(edata.get("top_p", 0.3)),
            context_lines=int(edata.get("context_lines", 3)),
            max_retries=int(edata.get("max_retries", 3)),
            pricing=edata.get("pricing", {"input_per_m": 0.0, "output_per_m": 0.0, "currency": "CNY"}),
            description=edata.get("description", ""),
            hard_cost_cap=float(edata.get("hard_cost_cap", 5.0)),
            prompt_version=edata.get("prompt_version", "film_v1.0" if edata.get("type") == "api" else "sakura_v1.0")
        )
        configs[eid] = cfg

    return configs


def get_engine_config(engine_id: Optional[str] = None) -> EngineConfig:
    """
    根据 engine_id 获取引擎配置。若不存在则抛出异常，绝不静默自动 fallback。
    """
    all_configs = load_engine_configs()
    target_id = engine_id or "sakura-14b"
    if target_id not in all_configs:
        raise ValueError(
            f"未知的翻译引擎: [{target_id}]。可选引擎: {list(all_configs.keys())}。"
            f"请检查 config/engines.json 或 task_meta.json 中的 engine_id。"
        )
    return all_configs[target_id]


def is_refusal_response(content: str, resp_json: Optional[Dict[str, Any]] = None, status_code: int = 200) -> Tuple[bool, str]:
    """
    拒答三形态识别:
      形态 1: 文本关键词匹配 (例如'抱歉我无法协助')
      形态 2: finish_reason == 'content_filter' / 'safety' 或由于审查内容为空
      形态 3: HTTP 400/403/422 安全审查错误
    返回: (is_refused: bool, refusal_reason: str)
    """
    # 形态 3: HTTP 状态码或 API 错误
    if status_code in (400, 403, 422):
        err_msg = ""
        if resp_json and isinstance(resp_json, dict):
            err_data = resp_json.get("error", {})
            if isinstance(err_data, dict):
                err_msg = err_data.get("message", "")
            else:
                err_msg = str(err_data)
        if any(w in err_msg.lower() for w in ["content_filter", "safety", "policy", "sensitive", "moderation", "inappropriate"]):
            return True, f"HTTP_{status_code}_safety_policy: {err_msg}"

    # 形态 2: finish_reason 校验
    if resp_json and isinstance(resp_json, dict):
        choices = resp_json.get("choices", [])
        if choices and isinstance(choices, list):
            first_choice = choices[0]
            finish_reason = str(first_choice.get("finish_reason", "")).lower()
            if finish_reason in ("content_filter", "safety", "sensitive"):
                return True, f"finish_reason_{finish_reason}"

    # 形态 1: 文本关键词校验
    if content:
        clean_text = content.strip()
        for pat in REFUSAL_PATTERNS:
            if pat.search(clean_text):
                matched = pat.pattern
                return True, f"refusal_pattern_matched: {matched}"

    return False, ""


def estimate_tokens(text: str) -> int:
    """粗略预估文本的 Token 数量 (中日韩文字约为 1.2-1.4 tokens/字)"""
    if not text:
        return 0
    return max(1, int(len(text) * 1.3))


def calculate_cost(prompt_tokens: int, completion_tokens: int, pricing: Dict[str, Any]) -> float:
    """计算本次调用的精确费用"""
    input_rate = float(pricing.get("input_per_m", 0.0))
    output_rate = float(pricing.get("output_per_m", 0.0))
    cost = (prompt_tokens / 1_000_000.0) * input_rate + (completion_tokens / 1_000_000.0) * output_rate
    return round(cost, 6)
