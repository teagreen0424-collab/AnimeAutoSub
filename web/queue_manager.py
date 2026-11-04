"""
AnimeAutoSub 任务队列、Worker 调度与 SSE 事件流 (web/queue_manager.py)

落实纪律:
1. 独占 GPU 队列: 同一时刻至多 1 个任务进入 GPU 推理，其余显示 '等待 GPU'。
2. 实时 SSE 事件流: 阶段名 + 阶段内百分比 + 加权总进度 + 实时日志。
3. 历史事件环形回放: 基于 Last-Event-ID 刷新页面进度不丢。
4. 秒级安全取消: 3秒内停住，释放 GPU 租约，保留已完成阶段以供续跑。
5. 自动断点续跑: 命中三元组缓存跳过已完成阶段，体现从断点恢复。
"""

import os
import sys
import time
import json
import logging
import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context import PipelineContext, CancelToken
from core.pipeline import Pipeline
from core.manifest import ManifestManager
from core.gpu_lease import release_ollama_vram
from lang import get_language, SUPPORTED_LANGUAGES


class SSEEvent:
    def __init__(self, event_id: int, event_type: str, data: Dict[str, Any]):
        self.event_id = event_id
        self.event_type = event_type
        self.data = data
        self.timestamp = time.time()

    def to_sse_str(self) -> str:
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


class SSELogHandler(logging.Handler):
    """拦截 Pipeline 日志并实时推送到队列管理器的 SSE 事件广播池"""
    def __init__(self, queue_manager, task_id: str):
        super().__init__()
        self.queue_manager = queue_manager
        self.task_id = task_id

    def emit(self, record):
        msg = self.format(record)
        self.queue_manager.record_task_log(self.task_id, record.levelname, msg)


class QueueManager:
    """全局任务队列与调度中心"""

    STAGE_WEIGHTS_OCR = {
        "ocr_extract": 0.25,
        "translate": 0.45,
        "layout_ass": 0.05,
        "burn_subtitles": 0.20,
        "verify_metrics": 0.05
    }

    STAGE_WEIGHTS_ASR = {
        "asr": 0.25,
        "translate": 0.45,
        "layout_ass": 0.05,
        "burn_subtitles": 0.20,
        "verify_metrics": 0.05
    }

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root
        self.queue: List[str] = []              # task_id 队列
        self.active_task_id: Optional[str] = None
        self.active_cancel_tokens: Dict[str, CancelToken] = {}
        
        # 事件回放缓冲区: task_id -> List[SSEEvent]
        self.event_buffers: Dict[str, List[SSEEvent]] = {}
        self.event_counter = 0

        # 异步监听器: task_id -> List[asyncio.Queue]
        self.listeners: Dict[str, List[asyncio.Queue]] = {}

        # 任务进度状态缓存
        self.task_states: Dict[str, Dict[str, Any]] = {}

        # 启动调度守护线程 (必须为可重入锁 RLock, 防止同一线程在嵌套调用 emit_event 时自锁死锁)
        self._lock = threading.RLock()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def submit_task(self, task_id: str) -> Dict[str, Any]:
        """将任务投入排队队列"""
        with self._lock:
            if task_id in self.queue:
                return {"status": "queued", "position": self.queue.index(task_id) + 1}
            if self.active_task_id == task_id:
                return {"status": "running", "position": 0}

            self.queue.append(task_id)
            pos = len(self.queue)
            
            self._update_task_state(task_id, {
                "status": "queued",
                "queue_position": pos,
                "waiting_gpu": (pos > 1 or self.active_task_id is not None)
            })

            self.emit_event(task_id, "task_queued", {
                "task_id": task_id,
                "queue_position": pos,
                "message": f"任务已进入排队队列 (当前第 {pos} 位)"
            })
            return {"status": "queued", "position": pos}

    def submit_rerender(self, task_id: str) -> Dict[str, Any]:
        """提交增量重渲染 (自动秒级跳过 OCR/翻译，只重跑排版与压制)"""
        with self._lock:
            work_dir = self.project_root / "work_tasks" / task_id
            if not work_dir.exists():
                work_dir = self.project_root / task_id
            mf_path = work_dir / "manifest.json"
            if mf_path.exists():
                try:
                    with open(mf_path, "r", encoding="utf-8") as f:
                        mf = json.load(f)
                    stgs = mf.get("stages", {})
                    stgs.pop("layout_ass", None)
                    stgs.pop("burn_subtitles", None)
                    stgs.pop("verify_metrics", None)
                    with open(mf_path, "w", encoding="utf-8") as f:
                        json.dump(mf, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            return self.submit_task(task_id)

    def purge_task(self, task_id: str) -> None:
        """从队列、事件缓冲和监听器中彻底注销任务 (配合任务物理删除)"""
        with self._lock:
            if task_id in self.queue:
                self.queue.remove(task_id)
            self.task_states.pop(task_id, None)
            self.event_buffers.pop(task_id, None)
            self.active_cancel_tokens.pop(task_id, None)
            self.listeners.pop(task_id, None)

    def cancel_task(self, task_id: str) -> bool:
        """安全取消任务 (3 秒内生效并释放 GPU 租约)"""
        with self._lock:
            # 1. 若在队列中排队尚未开始
            if task_id in self.queue:
                self.queue.remove(task_id)
                self._update_task_state(task_id, {"status": "canceled", "message": "用户取消排队"})
                self.emit_event(task_id, "task_canceled", {
                    "task_id": task_id,
                    "status": "canceled",
                    "message": "已从队列中移除，任务已取消"
                })
                # Z11: 显式写盘记录 canceled 状态，防止落单目录被误判
                work_dir = self.project_root / "work_tasks" / task_id
                if not work_dir.exists():
                    work_dir = self.project_root / task_id
                if work_dir.exists():
                    try:
                        ManifestManager(work_dir).record_cancelled(reason="用户取消排队")
                    except Exception:
                        pass
                return True

            # 2. 若正在执行
            if self.active_task_id == task_id:
                token = self.active_cancel_tokens.get(task_id)
                if token:
                    token.cancel("用户主动点击取消")
                self._update_task_state(task_id, {
                    "status": "canceled",
                    "message": "正在中止阶段执行并释放 GPU 租约..."
                })
                self.emit_event(task_id, "task_canceling", {
                    "task_id": task_id,
                    "status": "canceled",
                    "message": "正在请求中断流水线，3 秒内释放 GPU 租约..."
                })
                work_dir = self.project_root / "work_tasks" / task_id
                if not work_dir.exists():
                    work_dir = self.project_root / task_id
                if work_dir.exists():
                    try:
                        ManifestManager(work_dir).record_cancelled(reason="用户主动点击取消")
                    except Exception:
                        pass
                return True
        return False

    def has_running_tasks(self) -> bool:
        """Z9: 检查是否有正在运行或排队中的任务"""
        with self._lock:
            return self.active_task_id is not None or len(self.queue) > 0

    def get_active_task_summary(self) -> Optional[Dict[str, Any]]:
        """Z9: 获取当前活跃任务的概要信息"""
        with self._lock:
            if not self.active_task_id:
                return None
            st = self.task_states.get(self.active_task_id, {})
            return {
                "task_id": self.active_task_id,
                "current_stage": st.get("current_stage", "-"),
                "stage_pct": st.get("stage_pct", 0.0),
                "total_pct": st.get("total_pct", 0.0),
                "queue_length": len(self.queue)
            }

    def interrupt_active_task(self, task_id: Optional[str] = None, reason: str = "服务停机或重启中断") -> bool:
        """Z9: 显式中断活跃任务并打上 interrupted 标记（区别于 canceled），保障断点续跑"""
        with self._lock:
            target_id = task_id or self.active_task_id
            if not target_id:
                return False

            # 若仍在排队队列中
            if target_id in self.queue:
                self.queue.remove(target_id)
                self._update_task_state(target_id, {
                    "status": "interrupted",
                    "message": f"服务重启移出队列 ({reason})，可一键续跑"
                })
                self.emit_event(target_id, "task_interrupted", {
                    "task_id": target_id,
                    "status": "interrupted",
                    "message": f"任务已安全中断 ({reason})，可一键续跑"
                })
                work_dir = self.project_root / "work_tasks" / target_id
                if not work_dir.exists():
                    work_dir = self.project_root / target_id
                if work_dir.exists():
                    try:
                        ManifestManager(work_dir).record_interrupted(reason=reason)
                    except Exception:
                        pass
                return True

            # 若正在执行
            if self.active_task_id == target_id:
                token = self.active_cancel_tokens.get(target_id)
                if token:
                    token.cancel(reason)
                self._update_task_state(target_id, {
                    "status": "interrupted",
                    "message": f"正在安全中断流水线 ({reason}) 并释放资源..."
                })
                self.emit_event(target_id, "task_interrupted", {
                    "task_id": target_id,
                    "status": "interrupted",
                    "message": f"正在请求安全中断流水线 ({reason})，已完成阶段已保留以供恢复"
                })
                work_dir = self.project_root / "work_tasks" / target_id
                if not work_dir.exists():
                    work_dir = self.project_root / target_id
                if work_dir.exists():
                    try:
                        ManifestManager(work_dir).record_interrupted(reason=reason)
                    except Exception:
                        pass
                return True
        return False

    def emit_event(self, task_id: str, event_type: str, data: Dict[str, Any]):
        """记录事件至回放缓冲区并向所有活跃 SSE 连接分发"""
        self.event_counter += 1
        ev = SSEEvent(self.event_counter, event_type, data)

        with self._lock:
            if task_id not in self.event_buffers:
                self.event_buffers[task_id] = []
            buf = self.event_buffers[task_id]
            buf.append(ev)
            if len(buf) > 500:  # 保留最近 500 条
                buf.pop(0)

            # 向异步队列广播
            queues = self.listeners.get(task_id, [])
            for q in list(queues):
                try:
                    q.put_nowait(ev)
                except Exception:
                    pass

    def record_task_log(self, task_id: str, level: str, log_text: str):
        """解析日志流中的进度信息并广播日志事件"""
        # 解析阶段与进度条
        progress_info = self._parse_progress_from_log(task_id, log_text)
        
        event_data = {
            "task_id": task_id,
            "level": level,
            "text": log_text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        if progress_info:
            event_data.update(progress_info)

        self.emit_event(task_id, "stage_log", event_data)

    def _parse_progress_from_log(self, task_id: str, log_text: str) -> Optional[Dict[str, Any]]:
        """从阶段日志文本中智能提取阶段内与加权总进度"""
        state = self.task_states.get(task_id, {})
        current_stage = state.get("current_stage", "ocr_extract")
        mode = state.get("mode", "ocr")
        weights = self.STAGE_WEIGHTS_OCR if mode == "ocr" else self.STAGE_WEIGHTS_ASR

        stage_pct = state.get("stage_pct", 0.0)

        # 匹配日志中的进度标记
        import re
        m_ocr = re.search(r'OCR 进度.*?(\d+\.?\d*)%', log_text)
        if m_ocr:
            stage_pct = float(m_ocr.group(1)) / 100.0
            current_stage = "ocr_extract"

        m_trans = re.search(r'翻译进度.*?(\d+)%', log_text)
        if m_trans:
            stage_pct = float(m_trans.group(1)) / 100.0
            current_stage = "translate"

        if "压制完成" in log_text or "BurnSubtitlesStage" in log_text:
            current_stage = "burn_subtitles"
            stage_pct = 0.5
            if "压制完成 ->" in log_text:
                stage_pct = 1.0

        # 计算加权总进度
        completed_weight = 0.0
        stage_names = list(weights.keys())
        if current_stage in stage_names:
            curr_idx = stage_names.index(current_stage)
            for prev_s in stage_names[:curr_idx]:
                completed_weight += weights[prev_s]
            curr_weight = weights[current_stage] * stage_pct
            total_pct = round((completed_weight + curr_weight) * 100, 1)
        else:
            total_pct = state.get("total_pct", 0.0)

        self._update_task_state(task_id, {
            "current_stage": current_stage,
            "stage_pct": round(stage_pct * 100, 1),
            "total_pct": min(100.0, total_pct)
        })

        return {
            "current_stage": current_stage,
            "stage_pct": round(stage_pct * 100, 1),
            "total_pct": min(100.0, total_pct)
        }

    def _update_task_state(self, task_id: str, updates: Dict[str, Any]):
        if task_id not in self.task_states:
            self.task_states[task_id] = {
                "task_id": task_id,
                "status": "queued",
                "current_stage": "-",
                "stage_pct": 0.0,
                "total_pct": 0.0,
                "waiting_gpu": False,
                "message": ""
            }
        self.task_states[task_id].update(updates)

    def _worker_loop(self):
        """后台单 Worker 轮询消费队列"""
        while True:
            task_id = None
            with self._lock:
                if self.queue and self.active_task_id is None:
                    task_id = self.queue.pop(0)
                    self.active_task_id = task_id

            if not task_id:
                time.sleep(0.5)
                continue

            # 开始执行任务
            self._execute_pipeline_task(task_id)

            with self._lock:
                self.active_task_id = None
                if task_id in self.active_cancel_tokens:
                    del self.active_cancel_tokens[task_id]

    def _execute_pipeline_task(self, task_id: str):
        """端到端驱动 Pipeline 并在关键阶段广播事件"""
        token = CancelToken()
        self.active_cancel_tokens[task_id] = token

        # 寻找任务工作目录与元数据
        work_dir = self.project_root / task_id
        if not work_dir.exists():
            # 兼容 work_tasks/<task_id>
            work_dir = self.project_root / "work_tasks" / task_id

        # 读取任务参数配置
        task_meta_file = work_dir / "task_meta.json"
        meta = {}
        if task_meta_file.exists():
            try:
                with open(task_meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}

        video_path = Path(meta.get("video_path", ""))
        if not video_path.exists():
            # 尝试在工作目录下查找原始视频或直接由上游指定
            for cand in [self.project_root / "input", self.project_root / "ocr_input"]:
                if (cand / video_path.name).exists():
                    video_path = cand / video_path.name
                    break

        lang_code = meta.get("lang", "ja")
        mode = meta.get("mode", "ocr")
        engine_id = meta.get("engine_id") or "sakura-14b"
        asr_engine_id = meta.get("asr_engine_id")

        self._update_task_state(task_id, {
            "status": "running",
            "mode": mode,
            "lang": lang_code,
            "waiting_gpu": False,
            "message": "流水线已启动，开始执行阶段检查..."
        })

        self.emit_event(task_id, "stage_change", {
            "task_id": task_id,
            "stage": "init",
            "status": "running",
            "message": f"任务已开始执行 (语言: {lang_code.upper()}, 模式: {mode.upper()})"
        })

        # 检查是否为断点续跑 (是否有已完成阶段)
        manifest_file = work_dir / "manifest.json"
        is_resume = False
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    mf = json.load(f)
                    completed_stages = [k for k, v in mf.get("stages", {}).items() if v.get("status") == "completed"]
                    if completed_stages:
                        is_resume = True
                        self.emit_event(task_id, "stage_change", {
                            "task_id": task_id,
                            "stage": "resume",
                            "status": "running",
                            "message": f"⚡ 检测到历史断点！已完成阶段 {completed_stages} 将自动秒级跳过，从中断处恢复"
                        })
            except Exception:
                pass

        try:
            lang_plugin = get_language(lang_code)
            ctx = PipelineContext(
                video_path=video_path,
                work_dir=work_dir,
                output_dir=work_dir,
                lang=lang_plugin,
                mode=mode,
                cancel_token=token,
                engine_id=engine_id,
                asr_engine_id=asr_engine_id
            )

            pipeline = Pipeline(ctx)

            # 挂载 SSE 日志监听器
            sse_handler = SSELogHandler(self, task_id)
            pipeline.log.addHandler(sse_handler)

            # 执行全流程
            success = pipeline.run()

            pipeline.log.removeHandler(sse_handler)

            if token.is_cancelled():
                is_interrupted = any(w in token.reason.lower() for w in ["interrupt", "中断", "停机", "重启", "shutdown"])
                new_status = "interrupted" if is_interrupted else "canceled"
                msg = f"任务已安全中断 ({token.reason})，可一键续跑" if is_interrupted else "任务已被用户取消，GPU 租约已安全释放"
                self._update_task_state(task_id, {
                    "status": new_status,
                    "message": msg
                })
                event_name = "task_interrupted" if is_interrupted else "task_canceled"
                self.emit_event(task_id, event_name, {
                    "task_id": task_id,
                    "status": new_status,
                    "message": msg
                })
                try:
                    mf_mgr = ManifestManager(work_dir)
                    if is_interrupted:
                        mf_mgr.record_interrupted(reason=token.reason)
                    else:
                        mf_mgr._data["is_cancelled"] = True
                        mf_mgr._data["status"] = "canceled"
                        mf_mgr.save()
                except Exception:
                    pass
            elif success:
                self._update_task_state(task_id, {
                    "status": "done",
                    "total_pct": 100.0,
                    "message": "全部阶段执行完毕，成片就绪"
                })
                self.emit_event(task_id, "task_complete", {
                    "task_id": task_id,
                    "status": "done",
                    "total_pct": 100.0,
                    "video_url": f"/api/tasks/{task_id}/video",
                    "message": "🎉 全部流水线阶段执行完毕！最终成片就绪，正在自动跳转到详情播放..."
                })
            else:
                # Z11 (a): 非用户显式取消一律为 interrupted
                self._update_task_state(task_id, {
                    "status": "interrupted",
                    "message": "流水线未完成中断 (已保留断点，可一键恢复续跑)"
                })
                self.emit_event(task_id, "task_interrupted", {
                    "task_id": task_id,
                    "status": "interrupted",
                    "message": "流水线异常中断，已保留阶段产物，可一键恢复断点续跑"
                })
                try:
                    ManifestManager(work_dir).record_interrupted(reason="流水线未完成异常退出")
                except Exception:
                    pass

        except Exception as e:
            err_msg = str(e)
            if token.is_cancelled():
                is_user_cancel = "用户" in token.reason or ("cancel" in token.reason.lower() and not any(w in token.reason.lower() for w in ["interrupt", "中断", "停机", "重启", "shutdown"]))
                new_status = "canceled" if is_user_cancel else "interrupted"
                err_msg = "用户取消操作" if is_user_cancel else f"任务已安全中断: {token.reason}"
                self._update_task_state(task_id, {"status": new_status, "message": err_msg})
                event_name = "task_canceled" if is_user_cancel else "task_interrupted"
                self.emit_event(task_id, event_name, {"task_id": task_id, "status": new_status, "message": err_msg})
                try:
                    mf_mgr = ManifestManager(work_dir)
                    if is_user_cancel:
                        mf_mgr.record_cancelled(reason=token.reason)
                    else:
                        mf_mgr.record_interrupted(reason=token.reason)
                except Exception:
                    pass
            else:
                # Z11 (a): 异常中断统一出口：未完成且非用户显式取消 -> 标记 interrupted 并保留已完成阶段供续跑
                self._update_task_state(task_id, {
                    "status": "interrupted",
                    "message": f"阶段异常中断: {err_msg} (已保留断点，可一键恢复续跑)"
                })
                self.emit_event(task_id, "task_interrupted", {
                    "task_id": task_id,
                    "status": "interrupted",
                    "error": err_msg,
                    "message": f"阶段异常中断: {err_msg} (可一键恢复断点续跑)"
                })
                try:
                    ManifestManager(work_dir).record_interrupted(reason=f"阶段异常中断: {err_msg}")
                except Exception:
                    pass
        finally:
            # 任务进入 done/failed/canceled 时主动释放 Ollama 模型显存并断言回落
            try:
                rel_info = release_ollama_vram()
                self.record_task_log(task_id, "INFO", f"🧹 [显存释放] 已释放显存 {rel_info.get('freed_mb', 0)} MB (当前显存: {rel_info.get('curr_mb', 0)} MB)")
            except Exception as e:
                self.record_task_log(task_id, "WARNING", f"⚠ 释放 Ollama 显存失败: {e}")


# 单例导出
queue_manager = QueueManager(PROJECT_ROOT)
