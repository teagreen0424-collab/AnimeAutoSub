"""
AnimeAutoSub 阶段账本与三元组状态校验 (core/manifest.py)

硬性契约:
  跳过条件必须是三元组（参数指纹 + 上游产物哈希 + 工具版本）。
  禁止仅判断文件存在！
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from .stage import Stage
from .context import PipelineContext


def compute_file_sha256(path: Path) -> str:
    """计算单个文件的 SHA256 哈希"""
    if not path.exists() or not path.is_file():
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def compute_files_sha256(paths: List[Path]) -> str:
    """计算多个文件的联合 SHA256 哈希"""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: str(x)):
        h.update(p.name.encode("utf-8"))
        h.update(compute_file_sha256(p).encode("utf-8"))
    return h.hexdigest()


class ManifestManager:
    """工作目录 manifest.json 状态管理器"""
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.manifest_file = self.work_dir / "manifest.json"
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        data = {
            "version": 1,
            "schema_version": 2,
            "updated_at": "",
            "stages": {}
        }
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
            except Exception:
                pass
        data.setdefault("schema_version", 2)
        return data

    def save(self):
        self._data["schema_version"] = 2
        self._data["updated_at"] = datetime.now().isoformat()
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def should_skip(self, stage: Stage, ctx: PipelineContext, upstream_hash: str, tool_version: str) -> bool:
        """
        硬性三元组校验:
        1. 产物物理存在且非空
        2. stage.verify(ctx) 校验通过
        3. 参数指纹 == manifest 记录
        4. 上游产物哈希 == manifest 记录
        5. 工具版本 == manifest 记录
        """
        stage_records = self._data.get("stages", {}).get(stage.name)
        if not stage_records:
            return False

        if stage_records.get("status") != "completed":
            return False

        # 1. 物理检查 produces 文件
        for rel_path in stage.produces:
            p = ctx.get_product_path(rel_path)
            if not p.exists() or p.stat().st_size == 0:
                return False

        # 2. 校验方法
        if not stage.verify(ctx):
            return False

        # 3. 三元组严格对齐
        current_fingerprint = stage.fingerprint(ctx)
        recorded_fingerprint = stage_records.get("fingerprint")
        recorded_upstream_hash = stage_records.get("upstream_hash")
        recorded_tool_version = stage_records.get("tool_version")

        if current_fingerprint != recorded_fingerprint:
            return False
        if upstream_hash != recorded_upstream_hash:
            return False
        if tool_version != recorded_tool_version:
            return False

        return True

    def record_stage_start(self, stage: Stage):
        if "stages" not in self._data:
            self._data["stages"] = {}
        self._data["stages"][stage.name] = {
            "status": "running",
            "started_at": datetime.now().isoformat()
        }
        self.save()

    def record_stage_completed(self, stage: Stage, ctx: PipelineContext, upstream_hash: str, tool_version: str):
        if "stages" not in self._data:
            self._data["stages"] = {}
        self._data["stages"][stage.name] = {
            "status": "completed",
            "fingerprint": stage.fingerprint(ctx),
            "upstream_hash": upstream_hash,
            "tool_version": tool_version,
            "produces": stage.produces,
            "completed_at": datetime.now().isoformat()
        }
        self.save()

    def record_stage_failed(self, stage: Stage, error_msg: str):
        if "stages" not in self._data:
            self._data["stages"] = {}
        self._data["stages"][stage.name] = {
            "status": "failed",
            "error": error_msg,
            "failed_at": datetime.now().isoformat()
        }
        self.save()
