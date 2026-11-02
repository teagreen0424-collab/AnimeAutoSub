"""
AnimeAutoSub 阶段接口契约 (core/stage.py)

硬性契约:
  - name: 阶段唯一标识名称
  - requires_gpu: 是否需要独占 GPU
  - produces: 声明本阶段生产的文件相对路径或产物名列表
  - fingerprint(ctx) -> sha256: 包含输入参数、上游依赖产物哈希与工具版本
  - run(ctx, log, cancel): 幂等、支持取消、严禁写 produces 声明之外的产物
  - verify(ctx) -> bool: 产物完整性与合规性校验
"""

from abc import ABC, abstractmethod
from typing import List, Any, Optional
import logging


class Stage(ABC):
    """流水线阶段抽象基类"""
    name: str
    requires_gpu: bool = False
    produces: List[str] = []

    def __init__(self):
        if not hasattr(self, "name") or not self.name:
            raise ValueError(f"{self.__class__.__name__} 必须声明阶段名称 name")
        if not hasattr(self, "produces"):
            self.produces = []

    @abstractmethod
    def fingerprint(self, ctx: Any) -> str:
        """
        计算本阶段的三元组执行指纹 (sha256):
        包含:
          1. 阶段特定超参数
          2. 上游依赖产物的 SHA256 哈希
          3. 依赖核心工具/环境版本 (如 RapidOCR, FFmpeg, Whisper)
        """
        pass

    @abstractmethod
    def run(self, ctx: Any, log: logging.Logger, cancel_token: Optional[Any] = None) -> None:
        """
        幂等执行当前阶段:
        - 只允许写入 self.produces 声明的文件
        - 遇到 cancel_token.is_cancelled() 时平稳安全中断退出
        """
        pass

    @abstractmethod
    def verify(self, ctx: Any) -> bool:
        """
        校验产物是否存在且合规:
        - 验证 self.produces 声明的文件在 ctx.work_dir 下全部真实存在
        - 验证文件大小 > 0 且格式解析合法 (非空、非半写损坏)
        """
        pass
