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
import shutil
import stat
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

        # 读取 task_meta 与 manifest 数据
        meta_data = {}
        meta_file = d / "task_meta.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    meta_data = json.load(mf)
            except Exception:
                meta_data = {}

        manifest_data = {}
        if has_manifest:
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception:
                manifest_data = {}

        # 语言与模式识别
        lang = meta_data.get("lang") or "ja"
        mode = meta_data.get("mode") or "ocr"
        title = meta_data.get("title") or d.name
        engine_id = meta_data.get("engine_id") or manifest_data.get("engine_id") or manifest_data.get("stages", {}).get("translate", {}).get("engine_id") or "sakura-14b"
        asr_stage = manifest_data.get("stages", {}).get("asr", {})
        asr_engine_id = meta_data.get("asr_engine_id") or manifest_data.get("asr_engine_id") or asr_stage.get("asr_engine_id")

        name_lower = d.name.lower()
        if "ko" in name_lower and not meta_data.get("lang"):
            lang = "ko"
        elif ("114877" in name_lower or "408309" in name_lower or "ja" in name_lower) and not meta_data.get("lang"):
            lang = "ja"

        if "asr" in name_lower and not meta_data.get("mode"):
            mode = "asr"
        elif not meta_data.get("mode"):
            mode = "ocr"

        # 友好的标题命名 (仅在无显式 title 时)
        if not meta_data.get("title"):
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

        trans_stage = manifest_data.get("stages", {}).get("translate", {})
        token_usage = trans_stage.get("token_usage")
        cost_estimate = trans_stage.get("cost_estimate")

        return {
            "task_id": task_id,
            "title": title,
            "lang": lang,
            "mode": mode,
            "engine_id": engine_id,
            "asr_engine_id": asr_engine_id,
            "token_usage": token_usage,
            "cost_estimate": cost_estimate,
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

    def is_task_in_queue(self, task_id: str) -> bool:
        """检查任务是否在活跃队列或正在执行中"""
        try:
            from web.queue_manager import queue_manager
            with queue_manager._lock:
                return task_id in queue_manager.queue or queue_manager.active_task_id == task_id
        except Exception:
            return False

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
        覆盖: queued / running / waiting_gpu / failed / failed_timeout / canceled / interrupted / done
        """
        # 1. 历史产物 (只读任务)
        if is_legacy:
            if video_file and video_file.exists():
                return "done", "历史产物，四件套完整"
            return "done", "历史产物"

        # 2. 显式取消 (用户主动操作)
        if manifest.get("is_cancelled") is True or manifest.get("status") == "canceled":
            return "canceled", manifest.get("cancelled_reason", "用户主动取消流水线")

        # 3. 检查是否全流水线完成 (burn_subtitles 成功且成片存在)
        stages = manifest.get("stages", {})
        burn_stage = stages.get("burn_subtitles", {})
        if burn_stage.get("status") == "completed" and video_file and video_file.exists():
            return "done", "全部流水线阶段执行完毕，成片就绪"

        # 4. 检查内存中是否有活动的 Worker 进程
        worker = self.active_workers.get(work_dir.name)
        if worker:
            if worker.get("waiting_gpu"):
                return "waiting_gpu", "正在等待 GPU 独占租约分配"
            last_heartbeat = worker.get("last_heartbeat", 0)
            if time.time() - last_heartbeat > 180:
                return "failed_timeout", "心跳超时 (>180s)，Worker 可能已僵死"
            return "running", f"阶段 [{worker.get('current_stage')}] 正在执行"

        # 5. 检查全局任务队列状态 (仅当任务真实在队列中时才允许返回 queued / running / waiting_gpu)
        in_queue = self.is_task_in_queue(work_dir.name)
        if in_queue:
            try:
                from web.queue_manager import queue_manager
                with queue_manager._lock:
                    if queue_manager.active_task_id == work_dir.name:
                        st = queue_manager.task_states.get(work_dir.name, {})
                        if st.get("waiting_gpu"):
                            return "waiting_gpu", "正在等待 GPU 独占租约分配"
                        return "running", f"阶段 [{st.get('current_stage', 'init')}] 正在执行"
                    elif work_dir.name in queue_manager.queue:
                        pos = queue_manager.queue.index(work_dir.name) + 1
                        return "queued", f"排队等待执行 (第 {pos} 位)"
            except Exception:
                pass

        # 6. 未在队列中运行 (非 queued): 统一出口判定 (Z11 a)
        # Z9: 显式标记了中断
        if manifest.get("is_interrupted") is True or manifest.get("status") == "interrupted":
            return "interrupted", manifest.get("interrupted_reason", "服务重启或进程中断，可一键续跑")

        # 阶段标记了中断或有上次遗留未完成的 running 阶段 (模拟被 kill -9 或异常崩溃)
        for s_name, s_info in stages.items():
            if s_info.get("status") in ("interrupted", "running"):
                return "interrupted", f"阶段 [{s_name}] 在上次服务退出时被中断，可一键续跑"

        # 检查是否有失败阶段
        for s_name, s_info in stages.items():
            if s_info.get("status") == "failed":
                err = s_info.get("error", "阶段执行失败")
                return "failed", f"阶段 [{s_name}] 报错: {err}"

        # 7. Z11 (b) 终极兜底：目录存在但 manifest 无任何 completed 阶段、且队列中不存在该任务
        # 禁止显示 queued，统一判定为 interrupted，点亮「▶ 恢复」允许一键启动/断点续跑
        completed_count = sum(1 for s in stages.values() if s.get("status") == "completed")
        if completed_count > 0:
            return "interrupted", f"断点中断待命 (已完成 {completed_count} 个阶段，可一键续跑)"

        return "interrupted", "任务未在队列中执行 (已中断待命，可一键启动)"

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

    def get_task_storage_stats(self, task_id: str) -> Dict[str, Any]:
        """
        计算任务的磁盘占用统计 (区分成片、中间资源/缓存、字幕与文本)
        """
        task = self.tasks.get(task_id)
        if not task:
            work_dir = self.project_root / "work_tasks" / task_id
            if not work_dir.exists():
                work_dir = self.project_root / task_id
            if not work_dir.exists():
                raise FileNotFoundError(f"未找到任务工作目录: {task_id}")
            is_legacy = False
        else:
            work_dir = Path(task["work_dir"])
            is_legacy = task.get("is_legacy", False)

        total_bytes = 0
        video_bytes = 0
        cache_bytes = 0
        subtitle_bytes = 0
        other_bytes = 0

        # 临时/可清理中间资源判定规则
        cache_names = {
            "extracted_speech_16k.mp3",
            "extracted_audio.wav",
            "n5_rejection_report.json",
        }
        cache_dirs = {".frame_cache", "crops", "ocr_crops"}
        subtitle_names = {
            "subtitle.ass", "subtitle.srt", "chinese.json",
            "japanese.json", "ocr_raw.json", "asr_raw.json"
        }

        if work_dir.exists() and work_dir.is_dir():
            for p in work_dir.rglob("*"):
                if p.is_file():
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    total_bytes += sz
                    name_lower = p.name.lower()
                    is_in_cache_dir = any(part in cache_dirs for part in p.parts)

                    if name_lower.endswith((".mp4", ".mkv")) and ("output" in name_lower or "字幕" in name_lower or p.name == "output.mp4"):
                        video_bytes += sz
                    elif is_in_cache_dir or p.name in cache_names or name_lower.endswith((".wav", ".pcm")):
                        cache_bytes += sz
                    elif p.name in subtitle_names:
                        subtitle_bytes += sz
                    else:
                        other_bytes += sz

        return {
            "task_id": task_id,
            "work_dir": str(work_dir),
            "total_bytes": total_bytes,
            "total_human": self._human_size(total_bytes),
            "video_bytes": video_bytes,
            "video_human": self._human_size(video_bytes),
            "cache_bytes": cache_bytes,
            "cache_human": self._human_size(cache_bytes),
            "subtitle_bytes": subtitle_bytes,
            "subtitle_human": self._human_size(subtitle_bytes),
            "other_bytes": other_bytes,
            "other_human": self._human_size(other_bytes),
            "is_legacy": is_legacy,
        }

    def delete_task(self, task_id: str, mode: str = "full") -> Dict[str, Any]:
        """
        删除任务或清理中间资源
        mode:
          - "full": 彻底删除任务工作目录及其所有产物与中间资源 (释放全部空间)
          - "clean_cache": 仅清理中间资源 (抠出的音频、切片图片、帧缓存)，保留成片与字幕 (瘦身)
        """
        if task_id not in self.tasks:
            self.refresh_tasks()

        task = self.tasks.get(task_id)
        if not task:
            work_dir = self.project_root / "work_tasks" / task_id
            if not work_dir.exists():
                work_dir = self.project_root / task_id
            if not work_dir.exists():
                raise FileNotFoundError(f"任务不存在: {task_id}")
            is_legacy = False
        else:
            work_dir = Path(task["work_dir"])
            is_legacy = task.get("is_legacy", False)

        # 保护 1: 历史基准产物受保护
        if is_legacy:
            raise PermissionError("历史基准产物受系统保护，不可删除")

        # 保护 2: 正在运行的任务不可直接物理删除 (防止 WinError 32 和线程崩溃)
        from web.queue_manager import queue_manager
        with queue_manager._lock:
            if queue_manager.active_task_id == task_id:
                raise RuntimeError("任务当前正在执行中，请先取消停止任务后再执行删除")
            if task_id in queue_manager.queue:
                queue_manager.queue.remove(task_id)

        # 保护 3: 严格校验路径，防止误删工作区外部目录或输入片源目录
        work_dir = work_dir.resolve()
        safe_bases = [
            (self.project_root / "work_tasks").resolve(),
            self.project_root.resolve()
        ]
        forbidden_dirs = [
            self.project_root.resolve(),
            (self.project_root / "ocr_input").resolve(),
            (self.project_root / "input").resolve(),
            (self.project_root / "core").resolve(),
            (self.project_root / "web").resolve(),
            (self.project_root / "venv").resolve(),
            (self.project_root / "tests").resolve(),
        ]
        if work_dir in forbidden_dirs or not any(str(work_dir).startswith(str(base)) for base in safe_bases):
            raise PermissionError(f"目标目录受到系统安全保护，禁止删除: {work_dir}")

        stats_before = self.get_task_storage_stats(task_id)

        if mode == "clean_cache":
            # 仅清理中间缓存
            cache_names = {
                "extracted_speech_16k.mp3",
                "extracted_audio.wav",
                "n5_rejection_report.json",
            }
            cache_dirs = {".frame_cache", "crops", "ocr_crops"}

            freed_bytes = 0
            for p in list(work_dir.rglob("*")):
                if p.is_file():
                    name_lower = p.name.lower()
                    is_in_cache_dir = any(part in cache_dirs for part in p.parts)
                    if is_in_cache_dir or p.name in cache_names or name_lower.endswith((".wav", ".pcm")):
                        try:
                            freed_bytes += p.stat().st_size
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass

            for c_dir_name in cache_dirs:
                c_dir = work_dir / c_dir_name
                if c_dir.exists() and c_dir.is_dir():
                    shutil.rmtree(c_dir, ignore_errors=True)

            self.refresh_tasks()
            return {
                "task_id": task_id,
                "mode": "clean_cache",
                "freed_bytes": freed_bytes,
                "freed_human": self._human_size(freed_bytes),
                "message": f"任务中间缓存已成功清理，释放空间 {self._human_size(freed_bytes)}"
            }

        else:
            # mode == "full": 彻底删除整个任务工作目录
            freed_bytes = stats_before["total_bytes"]

            def _onerror_remove_readonly(func, path, exc_info):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except Exception:
                    pass

            shutil.rmtree(work_dir, onerror=_onerror_remove_readonly)

            # 清理 queue_manager 内部缓存
            queue_manager.purge_task(task_id)

            # 从 task_manager 字典中移除并刷新全量列表
            self.tasks.pop(task_id, None)
            self.refresh_tasks()

            return {
                "task_id": task_id,
                "mode": "full",
                "freed_bytes": freed_bytes,
                "freed_human": self._human_size(freed_bytes),
                "message": f"任务及关联资源已彻底删除，释放空间 {self._human_size(freed_bytes)}"
            }
