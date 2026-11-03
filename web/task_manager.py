"""
AnimeAutoSub WebUI 任务管理与状态机推导 (web/task_manager.py)

落实纪律:
1. M3 扫描已有产物: 启动时扫描本地产物目录，识别标准产物组合；
   - 有 manifest.json: 正式任务 (可续跑、可重渲染)
   - 无 manifest.json: 只读任务 (历史产物，禁用续跑)
2. M4 任务状态机: 严格从 manifest 字段 + worker 心跳推导状态:
   queued / running / waiting_gpu / failed / failed_timeout / canceled / done
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 扫描目标目录配置 (M3)
SCAN_TARGETS = [
    # 现存的正式/历史工作目录
    PROJECT_ROOT / "work_ko_1080p_final",
    PROJECT_ROOT / "work_ko_720p_final",
    PROJECT_ROOT / "work_ko_asr_final",
    PROJECT_ROOT / "ocr_output" / "114877-720p",
    PROJECT_ROOT / "output" / "408309-1080p",
]


class TaskManager:
    """任务管理器: 负责扫描已有产物、状态推导与元数据读取"""

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.active_workers: Dict[str, Dict[str, Any]] = {}
        self.refresh_tasks()

    def refresh_tasks(self) -> Dict[str, Dict[str, Any]]:
        """全量扫描并更新任务索引"""
        scanned: Dict[str, Dict[str, Any]] = {}

        # 1. 扫描固定白名单目录
        candidate_dirs = list(SCAN_TARGETS)

        # 2. 动态扫描工作空间根目录下的所有 work_* 目录与 work_tasks 子目录 (排除 work_tasks 根目录本身)
        for p in self.project_root.glob("work_*"):
            if p.name == "work_tasks":
                continue
            if p.is_dir() and p not in candidate_dirs:
                candidate_dirs.append(p)

        work_tasks_dir = self.project_root / "work_tasks"
        if work_tasks_dir.exists() and work_tasks_dir.is_dir():
            for p in work_tasks_dir.iterdir():
                if p.is_dir() and p not in candidate_dirs:
                    candidate_dirs.append(p)

        # 3. 动态扫描 ocr_output 与 output 子目录
        for base in [self.project_root / "ocr_output", self.project_root / "output"]:
            if base.exists() and base.is_dir():
                for p in base.iterdir():
                    if p.is_dir() and p not in candidate_dirs:
                        candidate_dirs.append(p)

        # 4. 逐个目录检查与解析
        for d in candidate_dirs:
            if not d.exists() or not d.is_dir():
                continue
            task_info = self._parse_task_directory(d)
            if task_info:
                scanned[task_info["task_id"]] = task_info

        self.tasks = scanned
        return self.tasks

    def _parse_task_directory(self, d: Path) -> Optional[Dict[str, Any]]:
        """解析单目录，根据 M3/M4 规则构建任务对象"""
        if d.name == "work_tasks" or d == self.project_root / "work_tasks":
            return None

        manifest_path = d / "manifest.json"
        has_manifest = manifest_path.exists() and manifest_path.stat().st_size > 5

        # 检查是否满足“标准产物四件套/组合”
        files = {f.name.lower(): f for f in d.iterdir() if f.is_file()}
        has_chinese = "chinese.json" in files
        has_japanese = "japanese.json" in files or "ocr_raw.json" in files or "asr_raw.json" in files
        has_subtitle = "subtitle.ass" in files or "subtitle.srt" in files
        
        # 寻找视频产物 (优先 .mp4 保证 HTML5 原生播放器无缝直放)
        video_file: Optional[Path] = None
        for name, fpath in files.items():
            if name.endswith(".mp4") and ("output" in name or "字幕" in name):
                video_file = fpath
                break
        if not video_file:
            for name, fpath in files.items():
                if name.endswith(".mp4"):
                    video_file = fpath
                    break
        if not video_file:
            for name, fpath in files.items():
                if name.endswith(".mkv"):
                    video_file = fpath
                    break

        # 检查是否为正式任务 (含有 task_meta.json 或位于 work_tasks 目录)
        has_meta = (d / "task_meta.json").exists()
        is_in_work_tasks = "work_tasks" in str(d)

        # 若既没有 manifest，也没有任何标准产物，且非新建任务目录，则忽略
        if not has_manifest and not has_meta and not is_in_work_tasks and not (has_chinese or has_subtitle or video_file):
            return None

        task_id = d.name
        is_legacy = not has_manifest and not has_meta and not is_in_work_tasks

        # 读取 manifest 数据
        manifest_data = {}
        if has_manifest:
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception:
                manifest_data = {}

        # 语言与模式识别
        lang = "ja"
        mode = "ocr"
        title = d.name

        name_lower = d.name.lower()
        if "ko" in name_lower:
            lang = "ko"
        elif "114877" in name_lower or "408309" in name_lower or "ja" in name_lower:
            lang = "ja"

        if "asr" in name_lower:
            mode = "asr"
        else:
            mode = "ocr"

        # 友好的标题命名
        if "ko_1080p_final" in name_lower:
            title = "韩语 1080p 模拟压制全链路成片"
        elif "ko_720p_final" in name_lower:
            title = "韩语 720p 模拟压制全链路成片"
        elif "ko_asr_final" in name_lower:
            title = "韩语 Whisper large-v3 ASR 语音成片"
        elif "114877" in name_lower:
            title = "114877-720p 日文硬字幕成片 (Chain B)"
        elif "408309" in name_lower:
            title = "408309-1080p 日文语音成片 (Chain A)"

        # M4 状态机推导
        status, status_reason = self.derive_task_status(manifest_data, d, is_legacy, video_file)

        # 调试任务判定 (目录名含 test_ 或 manifest 标记 is_test)
        is_debug = "test_" in d.name.lower() or manifest_data.get("is_test") is True

        # 提取阶段运行信息
        stages_info = self._extract_stages_info(manifest_data, is_legacy, files)

        # 扫描产物清单
        products = []
        for name, p in files.items():
            products.append({
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "size_human": self._human_size(p.stat().st_size),
                "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()
            })

        # 读取日志内容 (前 200 行 / 最近日志)
        log_content = ""
        log_file = d / "pipeline.log"
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    log_lines = f.readlines()
                    log_content = "".join(log_lines[-200:])
            except Exception:
                log_content = "读取日志失败"

        # 统计修改时间
        mtime = d.stat().st_mtime
        if video_file:
            mtime = video_file.stat().st_mtime

        return {
            "task_id": task_id,
            "title": title,
            "lang": lang,
            "mode": mode,
            "status": status,
            "status_reason": status_reason,
            "is_legacy": is_legacy,
            "is_debug": is_debug,
            "can_resume": not is_legacy and status not in ("done", "running"),
            "can_rerender": not is_legacy,
            "work_dir": str(d.resolve()),
            "video_file": str(video_file.resolve()) if video_file else None,
            "video_name": video_file.name if video_file else None,
            "has_video": video_file is not None,
            "has_subtitles": has_chinese or has_japanese or has_subtitle,
            "stages": stages_info,
            "products": products,
            "manifest": manifest_data,
            "recent_log": log_content,
            "updated_at": datetime.fromtimestamp(mtime).isoformat()
        }

    def derive_task_status(
        self,
        manifest: Dict[str, Any],
        work_dir: Path,
        is_legacy: bool,
        video_file: Optional[Path]
    ) -> tuple[str, str]:
        """
        M4 任务状态机推导
        推导依据: manifest 字段 + 阶段完成标记 + 产物存在性 + worker 心跳
        覆盖: queued / running / waiting_gpu / failed / failed_timeout / canceled / done
        """
        # 1. 历史产物 (只读任务)
        if is_legacy:
            if video_file and video_file.exists():
                return "done", "历史产物，四件套完整"
            return "done", "历史产物"

        # 2. Z9: 检查中断标记 (区别于主动取消 canceled，保障一键续跑)
        if manifest.get("is_interrupted") is True or manifest.get("status") == "interrupted":
            return "interrupted", manifest.get("interrupted_reason", "服务重启或进程中断，可一键续跑")

        # 3. 显式取消
        if manifest.get("is_cancelled") is True:
            return "canceled", "用户主动取消流水线"

        stages = manifest.get("stages", {})

        # 4. 检查是否有中断阶段
        for s_name, s_info in stages.items():
            if s_info.get("status") == "interrupted":
                return "interrupted", f"阶段 [{s_name}] 在上次服务退出时被中断，可一键续跑"

        # 5. 检查是否有失败阶段
        for s_name, s_info in stages.items():
            if s_info.get("status") == "failed":
                err = s_info.get("error", "阶段执行失败")
                return "failed", f"阶段 [{s_name}] 报错: {err}"

        # 6. 检查内存中是否有活动的 Worker 进程
        worker = self.active_workers.get(work_dir.name)
        if worker:
            if worker.get("waiting_gpu"):
                return "waiting_gpu", "正在等待 GPU 独占租约分配"
            last_heartbeat = worker.get("last_heartbeat", 0)
            if time.time() - last_heartbeat > 180:
                return "failed_timeout", "心跳超时 (>180s)，Worker 可能已僵死"
            return "running", f"阶段 [{worker.get('current_stage')}] 正在执行"

        # 7. Worker 未在内存中活跃，但 manifest 中有阶段处于 running 状态 -> 说明进程在执行该阶段时被异常终止
        for s_name, s_info in stages.items():
            if s_info.get("status") == "running":
                return "interrupted", f"阶段 [{s_name}] 在上次服务退出时异常中断，可一键续跑"

        # 8. 检查是否全流水线完成 (burn_subtitles 成功且成片存在)
        burn_stage = stages.get("burn_subtitles", {})
        if burn_stage.get("status") == "completed" and video_file and video_file.exists():
            return "done", "全部流水线阶段执行完毕，成片就绪"

        # 9. 未在 Worker 中执行，但阶段未全满 -> 断点待命状态
        completed_count = sum(1 for s in stages.values() if s.get("status") == "completed")
        if completed_count > 0:
            return "queued", f"断点待命 (已完成 {completed_count} 个阶段，可一键续跑)"

        return "queued", "等待进入执行队列"

    def _extract_stages_info(
        self,
        manifest: Dict[str, Any],
        is_legacy: bool,
        files: Dict[str, Path]
    ) -> List[Dict[str, Any]]:
        """提取并标准化阶段信息"""
        stage_names = ["ocr_extract", "asr", "translate", "layout_ass", "burn_subtitles", "verify_metrics"]
        display_names = {
            "ocr_extract": "OCR 字幕检测与识别",
            "asr": "Whisper 语音转写",
            "translate": "智能清洗与大模型翻译",
            "layout_ass": "自适应排版与字幕生成",
            "burn_subtitles": "FFmpeg 视频压制成片",
            "verify_metrics": "遮罩几何与指标质检"
        }

        result = []
        stages = manifest.get("stages", {})

        for name in stage_names:
            if name in stages:
                s = stages[name]
                result.append({
                    "name": name,
                    "display_name": display_names.get(name, name),
                    "status": s.get("status", "pending"),
                    "completed_at": s.get("completed_at"),
                    "tool_version": s.get("tool_version", "-"),
                    "products": s.get("produces", [])
                })
            elif is_legacy:
                # 历史产物根据实际文件推断阶段完成度
                status = "completed"
                if name == "ocr_extract" and ("japanese.json" not in files and "ocr_raw.json" not in files):
                    status = "skipped"
                elif name == "asr" and ("vocals.wav" not in files and "audio.wav" not in files):
                    status = "skipped"
                elif name == "translate" and "chinese.json" not in files:
                    status = "skipped"
                elif name == "layout_ass" and "subtitle.ass" not in files:
                    status = "skipped"
                elif name == "burn_subtitles" and not any(k.endswith(".mp4") for k in files):
                    status = "skipped"
                elif name == "verify_metrics":
                    status = "skipped"

                result.append({
                    "name": name,
                    "display_name": display_names.get(name, name),
                    "status": status,
                    "completed_at": "-",
                    "tool_version": "历史流水线 (预设)",
                    "products": []
                })

        return result

    @staticmethod
    def _human_size(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} TB"
