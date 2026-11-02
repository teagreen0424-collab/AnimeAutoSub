"""
AnimeAutoSub 语言插件注册与获取
"""

from typing import Dict
from .base import LanguagePlugin
from .ja import japanese_plugin
from .ko import korean_plugin

SUPPORTED_LANGUAGES: Dict[str, LanguagePlugin] = {
    "ja": japanese_plugin,
    "ko": korean_plugin
}

def get_language(code: str) -> LanguagePlugin:
    if code not in SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的语言代码: '{code}' (支持: {list(SUPPORTED_LANGUAGES.keys())})")
    return SUPPORTED_LANGUAGES[code]
