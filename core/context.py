"""
AnimeAutoSub 流水线上下文与状态容器 (core/context.py)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional
import threading
from lang.base import LanguagePlugin


class CancelToken:
    """流水线取消令牌"""
    def __init__(self):
        self._is_cancelled = threading.Event()
        self._reason = ""

    def cancel(self, reason: str = "User requested cancellation"):
        self._reason = reason
        self._is_cancelled.set()

    def is_cancelled(self) -> bool:
        return self._is_cancelled.is_set()

    @property
    def reason(self) -> str:
        return self._reason


@dataclass
class PipelineContext:
    """单次运行的上下文与资源配置容器"""
    video_path: Path
    work_dir: Path
    output_dir: Path
    lang: LanguagePlugin
    mode: str = "ocr"                 # "ocr" 或 "asr"
    custom_params: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    cancel_token: CancelToken = field(default_factory=CancelToken)
    engine_id: Optional[str] = None

    def __post_init__(self):
        self.video_path = Path(self.video_path).resolve()
        self.work_dir = Path(self.work_dir).resolve()
        self.output_dir = Path(self.output_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_product_path(self, relative_name: str) -> Path:
        """获取阶段产物的绝对路径"""
        return self.work_dir / relative_name


_LOGGED_DEPRECATIONS = set()


def get_subtitle_src(item: Dict[str, Any], logger: Optional[Any] = None) -> str:
    """
    读取端兼容: 先找 src, 找不到回落 ja, 并打一次 deprecation 日志
    """
    if "src" in item and item["src"] is not None:
        return str(item["src"])
    if "ja" in item and item["ja"] is not None:
        global _LOGGED_DEPRECATIONS
        if "ja" not in _LOGGED_DEPRECATIONS:
            _LOGGED_DEPRECATIONS.add("ja")
            msg = "DEPRECATION: chinese.json 中的字段 'ja' 已废弃，进入兼容模式回落，请尽快迁移至 'src'"
            if logger:
                logger.warning(f"  ⚠ {msg}")
            else:
                import logging
                logging.warning(f"  ⚠ {msg}")
        return str(item["ja"])
    return ""


def get_subtitle_src_raw(item: Dict[str, Any], logger: Optional[Any] = None) -> str:
    """
    读取端兼容: 先找 src_raw, 找不到回落 ja_raw, 并打一次 deprecation 日志
    """
    if "src_raw" in item and item["src_raw"] is not None:
        return str(item["src_raw"])
    if "ja_raw" in item and item["ja_raw"] is not None:
        global _LOGGED_DEPRECATIONS
        if "ja_raw" not in _LOGGED_DEPRECATIONS:
            _LOGGED_DEPRECATIONS.add("ja_raw")
            msg = "DEPRECATION: chinese.json 中的字段 'ja_raw' 已废弃，进入兼容模式回落，请尽快迁移至 'src_raw'"
            if logger:
                logger.warning(f"  ⚠ {msg}")
            else:
                import logging
                logging.warning(f"  ⚠ {msg}")
        return str(item["ja_raw"])
    return ""

