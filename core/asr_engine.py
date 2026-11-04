"""
AnimeAutoSub 多引擎与云端 ASR 语音转写架构适配器 (core/asr_engine.py)
支持本地 Whisper (large-v3) 与云端 API (硅基流动 SiliconFlow SenseVoiceSmall 等)。

硬性契约:
  1. ASR 引擎配置外置 (config/engines.json 的 asr_engines 部分)
  2. 密钥走环境变量 (SILICONFLOW_API_KEY) 或文件 (config/siliconflow_key.txt)，绝不进 Git/日志/前端/产物
  3. 云端 ASR 引擎 requires_gpu=False，零 GPU 显存依赖
  4. 产出标准的 asr_raw.json 格式，完美兼容下游 translate / layout_ass 阶段
  5. 密钥严格自动脱敏 redact_secrets
"""

import os
import re
import json
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import requests
from .translation_engine import redact_secrets, register_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_ENGINES_FILE = CONFIG_DIR / "engines.json"
EXAMPLE_ENGINES_FILE = CONFIG_DIR / "engines.example.json"

DEFAULT_ASR_ENGINES: Dict[str, Dict[str, Any]] = {
    "siliconflow-sensevoice": {
        "id": "siliconflow-sensevoice",
        "name": "硅基流动 SenseVoice (云端 API)",
        "type": "api",
        "api_url": "https://api.siliconflow.cn/v1/audio/transcriptions",
        "model_name": "FunAudioLLM/SenseVoiceSmall",
        "api_key_env": "SILICONFLOW_API_KEY",
        "api_key_file": "config/siliconflow_key.txt",
        "requires_gpu": false if False else False,
        "response_format": "verbose_json",
        "pricing": {
            "per_minute": 0.002,
            "currency": "CNY"
        },
        "description": "阿里云通义实验室开源多语种富文本语音识别，极度轻量低延迟，原生支持日中韩英"
    },
    "local-whisper": {
        "id": "local-whisper",
        "name": "本地 Whisper (large-v3)",
        "type": "local",
        "api_url": "",
        "model_name": "large-v3",
        "api_key_env": "",
        "api_key_file": "",
        "requires_gpu": True,
        "response_format": "",
        "pricing": {
            "per_minute": 0.0,
            "currency": "CNY"
        },
        "description": "本地离线推理，需 4GB+ 显存"
    }
}


@dataclass
class AsrEngineConfig:
    """ASR 引擎结构定义与参数配置"""
    id: str
    name: str
    type: str                         # "local" 或 "api"
    api_url: str = ""
    model_name: str = "FunAudioLLM/SenseVoiceSmall"
    api_key_env: str = ""
    api_key_file: str = ""
    api_key: str = field(default="", repr=False)
    requires_gpu: bool = False
    response_format: str = "verbose_json"
    pricing: Dict[str, Any] = field(default_factory=lambda: {
        "per_minute": 0.0,
        "currency": "CNY"
    })
    description: str = ""

    def is_configured(self) -> bool:
        """判定引擎是否已具备调用条件"""
        if self.type == "local":
            return True
        key = self.get_effective_api_key()
        return bool(key and len(key.strip()) >= 8)

    def get_effective_api_key(self) -> str:
        """获取真实 API 密钥"""
        if self.api_key:
            return self.api_key.strip()
        if self.api_key_env and self.api_key_env in os.environ:
            val = os.environ[self.api_key_env].strip()
            if val:
                register_secret(val)
                return val
        if self.api_key_file:
            key_file = PROJECT_ROOT / self.api_key_file
            if key_file.exists():
                try:
                    val = key_file.read_text(encoding="utf-8").strip()
                    if val:
                        register_secret(val)
                        return val
                except Exception:
                    pass
        return ""

    def get_masked_key(self) -> str:
        """获取安全展示的密钥掩码"""
        if self.type == "local":
            return "本地免密 (离线)"
        key = self.get_effective_api_key()
        if not key:
            return "未配置密钥"
        if len(key) <= 8:
            return "****"
        prefix = key[:3] if key.startswith("sk-") else key[:2]
        suffix = key[-4:]
        return f"{prefix}****{suffix}"

    def to_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        """序列化输出，默认对密钥脱敏"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "api_url": self.api_url,
            "model_name": self.model_name,
            "requires_gpu": self.requires_gpu,
            "response_format": self.response_format,
            "pricing": self.pricing,
            "description": self.description,
            "configured": self.is_configured(),
            "masked_key": self.get_masked_key() if mask_secrets else self.get_effective_api_key(),
            "api_key_file": self.api_key_file,
            "api_key_env": self.api_key_env
        }


def load_asr_engine_configs() -> Dict[str, AsrEngineConfig]:
    """从 config/engines.json 中加载 ASR 引擎配置"""
    data = None
    if DEFAULT_ENGINES_FILE.exists():
        try:
            data = json.loads(DEFAULT_ENGINES_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logging.warning(f"读取 {DEFAULT_ENGINES_FILE} 失败: {e}")

    if not data and EXAMPLE_ENGINES_FILE.exists():
        try:
            data = json.loads(EXAMPLE_ENGINES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    asr_raw_dict = (data or {}).get("asr_engines", DEFAULT_ASR_ENGINES)
    configs = {}
    for eng_id, eng_dict in asr_raw_dict.items():
        cfg = AsrEngineConfig(
            id=eng_dict.get("id", eng_id),
            name=eng_dict.get("name", eng_id),
            type=eng_dict.get("type", "local"),
            api_url=eng_dict.get("api_url", ""),
            model_name=eng_dict.get("model_name", "large-v3"),
            api_key_env=eng_dict.get("api_key_env", ""),
            api_key_file=eng_dict.get("api_key_file", ""),
            requires_gpu=eng_dict.get("requires_gpu", False),
            response_format=eng_dict.get("response_format", "verbose_json"),
            pricing=eng_dict.get("pricing", {"per_minute": 0.0, "currency": "CNY"}),
            description=eng_dict.get("description", "")
        )
        # 预注册密钥脱敏
        eff_key = cfg.get_effective_api_key()
        if eff_key:
            register_secret(eff_key)
        configs[eng_id] = cfg
    return configs


def get_asr_engine_config(engine_id: Optional[str] = None) -> AsrEngineConfig:
    """根据 ID 获取 ASR 引擎，默认返回首选配置"""
    configs = load_asr_engine_configs()
    if engine_id and engine_id in configs:
        return configs[engine_id]

    # 优先使用配置好的 API 引擎
    for eid in ("siliconflow-sensevoice", "local-whisper"):
        if eid in configs and configs[eid].is_configured():
            return configs[eid]

    if configs:
        return next(iter(configs.values()))
    return AsrEngineConfig(
        id="siliconflow-sensevoice",
        name="硅基流动 SenseVoice (云端 API)",
        type="api",
        api_url="https://api.siliconflow.cn/v1/audio/transcriptions",
        model_name="FunAudioLLM/SenseVoiceSmall",
        api_key_file="config/siliconflow_key.txt"
    )


def extract_audio_for_api(video_or_audio: Path, work_dir: Path, log: logging.Logger) -> Path:
    """
    使用 ffmpeg 将视频/音频转换为轻量高效的单声道 16kHz MP3 格式 (32k~64kbps)
    针对超长视频自动调整码率，确保严格低于平台 25MB 上传限制
    """
    output_mp3 = work_dir / "extracted_speech_16k.mp3"
    if output_mp3.exists() and output_mp3.stat().st_size > 1000:
        return output_mp3

    ffmpeg_bin = r"D:\Dev\ffmpeg\bin\ffmpeg.exe"
    if not Path(ffmpeg_bin).exists():
        ffmpeg_bin = "ffmpeg"

    ffprobe_bin = r"D:\Dev\ffmpeg\bin\ffprobe.exe"
    if not Path(ffprobe_bin).exists():
        ffprobe_bin = "ffprobe"

    duration_sec = 0.0
    try:
        p_res = subprocess.run([
            str(ffprobe_bin), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_or_audio)
        ], capture_output=True, text=True)
        if p_res.returncode == 0:
            duration_sec = float(p_res.stdout.strip())
    except Exception:
        pass

    # 动态码率策略: 30 分钟 64k 约 14MB; >50 分钟使用 32k 避免超限
    bitrate = "64k"
    if duration_sec > 3000:
        bitrate = "32k"
    elif duration_sec > 1800:
        bitrate = "48k"

    cmd = [
        str(ffmpeg_bin), "-y",
        "-i", str(video_or_audio),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", bitrate,
        str(output_mp3)
    ]
    log.info(f"    [AudioExtract] 提取轻量音频流: {output_mp3.name} (16kHz mono {bitrate})...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg 抽取音频失败: {redact_secrets(res.stderr)}")
    return output_mp3


def transcribe_via_api(
    audio_path: Path,
    engine_cfg: AsrEngineConfig,
    language_code: str,
    log: logging.Logger,
    session: Optional[requests.Session] = None
) -> List[Dict[str, Any]]:
    """
    调用 SiliconFlow / OpenAI 标准语音识别 API 接口，返回标准化的 asr_raw segments
    """
    api_key = engine_cfg.get_effective_api_key()
    if not api_key:
        raise ValueError(
            f"ASR 引擎 [{engine_cfg.name}] 未配置有效密钥！"
            f"请在 {engine_cfg.api_key_file} 中填入密钥，或设置环境变量 {engine_cfg.api_key_env}。"
        )

    url = engine_cfg.api_url or "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    log.info(f"    [CloudASR] 发起云端语音转写请求: URL={url}, 模型={engine_cfg.model_name}, 语种={language_code}...")

    sess = session or requests.Session()
    with open(audio_path, "rb") as f:
        files = {
            "file": (audio_path.name, f, "audio/mpeg")
        }
        data = {
            "model": engine_cfg.model_name,
            "response_format": engine_cfg.response_format or "verbose_json"
        }
        # 语种映射 (SenseVoice / Whisper 支持规范)
        if language_code:
            lang_map = {"ja": "ja", "ko": "ko", "zh": "zh", "en": "en"}
            data["language"] = lang_map.get(language_code, language_code)

        try:
            resp = sess.post(url, headers=headers, files=files, data=data, timeout=180)
        except Exception as e:
            raise RuntimeError(f"云端 ASR 请求网络异常: {redact_secrets(str(e))}")

    if resp.status_code != 200:
        err_msg = redact_secrets(resp.text)
        raise RuntimeError(f"云端 ASR 请求失败 (HTTP {resp.status_code}): {err_msg}")

    res_json = resp.json()

    # 1. 解析带时间戳的 segments
    segments = res_json.get("segments") or []
    results = []
    if segments:
        for s in segments:
            text = s.get("text", "").strip()
            if text:
                results.append({
                    "start": round(float(s.get("start", 0.0)), 2),
                    "end": round(float(s.get("end", 0.0)), 2),
                    "text": text,
                    "words": []
                })

    # 2. 兜底处理: 若返回纯文本而无细分时间戳
    if not results:
        full_text = res_json.get("text", "").strip()
        if full_text:
            # 尝试根据标点切分成合理台词句
            sentences = re.split(r'([。？！\n\.\?!]+)', full_text)
            chunks = []
            for i in range(0, len(sentences), 2):
                sent = sentences[i].strip()
                punct = sentences[i+1] if i+1 < len(sentences) else ""
                combined = (sent + punct).strip()
                if combined:
                    chunks.append(combined)

            # 获取音频时长
            duration_sec = 60.0
            try:
                ffprobe_bin = r"D:\Dev\ffmpeg\bin\ffprobe.exe"
                if not Path(ffprobe_bin).exists():
                    ffprobe_bin = "ffprobe"
                probe_cmd = [str(ffprobe_bin), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                p_res = subprocess.run(probe_cmd, capture_output=True, text=True)
                duration_sec = float(p_res.stdout.strip())
            except Exception:
                pass

            step = duration_sec / max(1, len(chunks))
            for idx, c in enumerate(chunks):
                results.append({
                    "start": round(idx * step, 2),
                    "end": round(min(duration_sec, (idx + 1) * step), 2),
                    "text": c,
                    "words": []
                })

    log.info(f"    ✓ [CloudASR] 云端转写成功，共解析得到 {len(results)} 条台词片段")
    return results
