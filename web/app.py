"""
AnimeAutoSub WebUI 主服务入口 (web/app.py)

落实纪律:
1. M5: 绑定 127.0.0.1，端口从 8000 起，占用则 +1 重试 (最多 20 次)；自动打印 URL 并打开浏览器。
2. M3: 启动时加载已扫描的任务列表 (区分正式任务与历史产物)。
3. M4: 严格依据状态机推导任务状态。
4. HTTP 206: 原生支持视频流 Range 分片，进度条随意拖拽。
5. P2 全套功能: 新建任务表单、独占排队、实时 SSE 进度推送、秒级取消、断点续跑。
"""

import os
import sys
import socket
import webbrowser
import logging
import subprocess
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import hashlib
import shutil
from core.context import get_subtitle_src, get_subtitle_src_raw
from core.gpu_lease import release_ollama_vram
from web.task_manager import TaskManager
from web.queue_manager import queue_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AnimeAutoSubWeb")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Z9: 应用生命周期管理，优雅停止与在途任务状态保护"""
    logger.info("AnimeAutoSub WebUI 服务已就绪")
    yield
    logger.info("AnimeAutoSub WebUI 服务正在关闭...")
    if queue_manager.has_running_tasks():
        active_id = queue_manager.active_task_id
        logger.warning(f"⚠ 检测到服务停止时存在在途任务 [{active_id}]，正在安全记录 interrupted 状态...")
        queue_manager.interrupt_active_task(active_id, reason="服务进程退出或停止")
    try:
        release_ollama_vram()
    except Exception:
        pass


app = FastAPI(title="AnimeAutoSub WebUI", version="1.0.0", lifespan=lifespan)

# 启用 CORS 允许本地调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化任务管理器
task_manager = TaskManager(PROJECT_ROOT)


def merge_live_queue_state(task_dict: Dict[str, Any]) -> Dict[str, Any]:
    """将内存中活跃的队列状态合并进任务详情中"""
    task_id = task_dict.get("task_id")
    if not task_id:
        return task_dict

    active = queue_manager.task_states.get(task_id)
    if active:
        task_dict["status"] = active.get("status", task_dict.get("status"))
        task_dict["current_stage"] = active.get("current_stage", "-")
        task_dict["stage_pct"] = active.get("stage_pct", 0.0)
        task_dict["total_pct"] = active.get("total_pct", 0.0)
        task_dict["queue_position"] = active.get("queue_position", 0)
        task_dict["waiting_gpu"] = active.get("waiting_gpu", False)
        task_dict["message"] = active.get("message", "")
        if task_dict["status"] in ("running", "waiting_gpu", "queued"):
            task_dict["can_resume"] = False
        elif task_dict["status"] in ("canceled", "failed", "interrupted"):
            task_dict["can_resume"] = True
    return task_dict


@app.get("/api/tasks")
async def get_tasks():
    """获取全量任务列表 (M3 扫描结果 + 实时队列状态)"""
    tasks = task_manager.refresh_tasks()
    task_list = list(tasks.values())
    
    # 合并活跃状态
    for t in task_list:
        merge_live_queue_state(t)

    # 按更新时间倒序
    task_list.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "total": len(task_list),
            "queue_length": len(queue_manager.queue),
            "active_task_id": queue_manager.active_task_id,
            "tasks": task_list
        }
    }


@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str):
    """获取单任务详细信息与各阶段状态"""
    tasks = task_manager.refresh_tasks()
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    task_data = dict(tasks[task_id])
    merge_live_queue_state(task_data)

    return {
        "code": 0,
        "message": "success",
        "data": task_data
    }


@app.post("/api/tasks")
async def create_new_task(req: Request):
    """
    新建任务 (支持拖拽/表单指定路径、语言、模式)，并自动加入独占队列
    """
    body = await req.json()
    video_path_str = body.get("video_path", "").strip().strip('"\'')
    if not video_path_str:
        raise HTTPException(status_code=400, detail="请提供有效的视频/音频片源路径")

    # 路径解析与容错寻找
    video_path = Path(video_path_str)
    if not video_path.is_absolute():
        found = False
        for d in [PROJECT_ROOT / "ocr_input", PROJECT_ROOT / "input", PROJECT_ROOT]:
            cand = d / video_path_str
            if cand.exists() and cand.is_file():
                video_path = cand.resolve()
                found = True
                break
            # 兼容省略扩展名的情况 (如 21684-720p 自动补全 .mp4/.mkv 等)
            if not video_path.suffix:
                for ext in [".mp4", ".mkv", ".avi", ".wav", ".mp3"]:
                    cand_ext = d / f"{video_path_str}{ext}"
                    if cand_ext.exists() and cand_ext.is_file():
                        video_path = cand_ext.resolve()
                        found = True
                        break
            if found:
                break

    if not video_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"片源文件不存在: {video_path}。请填写完整路径（如 D:\\视频\\a.mp4），或先把文件复制到 ocr_input 目录后从下拉框选择。"
        )

    # 模式推导
    mode = body.get("mode", "auto")
    if mode == "auto":
        suffix = video_path.suffix.lower()
        name_lower = video_path.name.lower()
        if suffix in [".mp3", ".wav", ".aac", ".flac", ".m4a"] or "asr" in name_lower or "audio" in name_lower:
            mode = "asr"
        else:
            mode = "ocr"

    lang = body.get("lang", "ja")
    title = body.get("title", "").strip() or video_path.stem
    engine_id = body.get("engine_id", "deepseek-flash")

    from core.translation_engine import load_engine_configs
    available_engines = load_engine_configs()
    if engine_id not in available_engines:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的翻译引擎 [{engine_id}]，可选引擎: {list(available_engines.keys())}"
        )

    asr_engine_id = body.get("asr_engine_id")
    if asr_engine_id:
        from core.asr_engine import load_asr_engine_configs
        available_asr = load_asr_engine_configs()
        if asr_engine_id not in available_asr:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的 ASR 引擎 [{asr_engine_id}]，可选引擎: {list(available_asr.keys())}"
            )
    elif mode == "asr":
        from core.asr_engine import get_asr_engine_config
        asr_engine_id = get_asr_engine_config().id

    # 生成规范任务目录
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_stem = "".join(c if c.isalnum() or c in "_-" else "_" for c in video_path.stem)[:24]
    task_id = f"work_{ts}_{clean_stem}"

    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # 持久化 task_meta.json
    meta = {
        "task_id": task_id,
        "title": title,
        "video_path": str(video_path.resolve()),
        "lang": lang,
        "mode": mode,
        "engine_id": engine_id,
        "asr_engine_id": asr_engine_id,
        "created_at": datetime.now().isoformat()
    }
    with open(work_dir / "task_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 自动加入执行队列
    auto_start = body.get("auto_start", True)
    if auto_start:
        queue_info = queue_manager.submit_task(task_id)
    else:
        queue_info = {"status": "created", "position": 0}

    # 刷新任务管理器
    task_manager.refresh_tasks()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "task_id": task_id,
            "title": title,
            "lang": lang,
            "mode": mode,
            "engine_id": engine_id,
            "work_dir": str(work_dir),
            "queue_info": queue_info
        }
    }


@app.post("/api/tasks/{task_id}/start")
async def start_or_resume_task(task_id: str):
    """启动或断点续跑任务"""
    if task_id not in task_manager.tasks:
        task_manager.refresh_tasks()

    queue_info = queue_manager.submit_task(task_id)
    return {
        "code": 0,
        "message": "success",
        "data": queue_info
    }


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task_endpoint(task_id: str):
    """3 秒内安全取消任务，释放 GPU 租约"""
    canceled = queue_manager.cancel_task(task_id)
    # 若任务未在队列中执行，但用户显式对该任务发起了取消请求，依然将其持久化标记为 canceled
    if not canceled:
        work_dir = PROJECT_ROOT / "work_tasks" / task_id
        if not work_dir.exists():
            work_dir = PROJECT_ROOT / task_id
        if work_dir.exists():
            from core.manifest import ManifestManager
            ManifestManager(work_dir).record_cancelled(reason="用户主动取消")
            canceled = True
    task_manager.refresh_tasks()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "canceled": canceled,
            "gpu_released": True
        }
    }


@app.get("/api/tasks/{task_id}/events")
async def sse_task_events(task_id: str, request: Request):
    """
    实时 SSE 进度流: 阶段名 + 阶段内百分比 + 加权总进度 + 实时日志
    支持 Last-Event-ID 环形缓冲区回放，页面刷新进度不丢失！
    """
    last_event_id_header = request.headers.get("last-event-id")
    last_id = 0
    if last_event_id_header:
        try:
            last_id = int(last_event_id_header)
        except ValueError:
            pass

    async def event_generator():
        queue = asyncio.Queue()
        with queue_manager._lock:
            if task_id not in queue_manager.listeners:
                queue_manager.listeners[task_id] = []
            queue_manager.listeners[task_id].append(queue)

            buf = queue_manager.event_buffers.get(task_id, [])
            replay_events = [ev for ev in buf if ev.event_id > last_id]

        try:
            # 1. 回放历史丢失事件
            for ev in replay_events:
                yield ev.to_sse_str()

            # 2. 实时推送新事件
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=12.0)
                    yield ev.to_sse_str()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with queue_manager._lock:
                if task_id in queue_manager.listeners and queue in queue_manager.listeners[task_id]:
                    queue_manager.listeners[task_id].remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/server/input_files")
async def list_server_input_files():
    """扫描服务器 input/ 与 ocr_input/ 目录下的可用片源供表单快捷选择"""
    files = []
    for d in [PROJECT_ROOT / "ocr_input", PROJECT_ROOT / "input"]:
        if d.exists() and d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in [".mp4", ".mkv", ".avi", ".mp3", ".wav"]:
                    files.append({
                        "name": p.name,
                        "folder": d.name,
                        "rel_path": str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "abs_path": str(p.resolve()),
                        "size_bytes": p.stat().st_size,
                        "size_human": TaskManager._human_size(p.stat().st_size)
                    })
    return {
        "code": 0,
        "message": "success",
        "data": files
    }


@app.post("/api/upload")
async def upload_video_file(file: UploadFile = File(...), request: Request = None):
    """
    Z4: 片源文件流式上传接口
    - 限制: 单文件 > 4 GB 拒绝; 磁盘剩余 < 文件大小 * 2 拒绝
    - 命名: 同名存在时递增改名 (xxx_1.mp4) 而非覆盖
    - 存储: 使用 shutil.copyfileobj 流式写入 ocr_input/，杜绝全量加载入内存
    """
    MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB
    ocr_input_dir = PROJECT_ROOT / "ocr_input"
    ocr_input_dir.mkdir(parents=True, exist_ok=True)

    # 1. 预检请求大小与 4GB 限制
    file.file.seek(0, 2)
    incoming_size = file.file.tell()
    file.file.seek(0)

    header_size = None
    content_length_header = request.headers.get("content-length") if request else None
    if content_length_header:
        try:
            header_size = int(content_length_header)
        except ValueError:
            header_size = None

    # 若请求头或实际大小任一超过 4GB，立即拦截
    if (header_size and header_size > MAX_FILE_SIZE) or incoming_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="单文件大小超过 4 GB 限制，拒绝上传")

    # 2. 预检磁盘剩余空间: 磁盘剩余 < 文件大小 * 2 拒绝并提示
    file_size_for_disk = max(incoming_size, header_size or 0)
    total_space, used_space, free_space = shutil.disk_usage(ocr_input_dir)
    if file_size_for_disk > 0:
        needed_free = file_size_for_disk * 2
        if free_space < needed_free:
            free_gb = round(free_space / (1024 ** 3), 2)
            needed_gb = round(needed_free / (1024 ** 3), 2)
            raise HTTPException(
                status_code=400,
                detail=f"磁盘剩余空间不足: 剩余可用 {free_gb} GB，导入该文件需要至少 {needed_gb} GB (文件大小 × 2)"
            )

    # 3. Z7 判重优化: 若 ocr_input 下已存在同名且大小相同的文件，直接复用已有路径并提示，杜绝重复写盘
    raw_filename = Path(file.filename or "uploaded_video.mp4").name
    dest_path = ocr_input_dir / raw_filename
    if dest_path.exists() and dest_path.is_file():
        existing_size = dest_path.stat().st_size
        if existing_size == incoming_size:
            rel_path = str(dest_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            return {
                "code": 0,
                "message": "该片源已存在，已为你选中",
                "existed": True,
                "data": {
                    "filename": dest_path.name,
                    "rel_path": rel_path,
                    "abs_path": str(dest_path.resolve()),
                    "size": existing_size,
                    "size_human": TaskManager._human_size(existing_size)
                }
            }

    # 若文件名相同但大小不同，避免覆盖，自动递增重命名 (xxx_1.mp4, xxx_2.mp4)
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while True:
            candidate = ocr_input_dir / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                dest_path = candidate
                break
            counter += 1

    # 4. 使用 shutil.copyfileobj 流式写入临时文件，杜绝内存堆积
    class BoundedWriter:
        def __init__(self, target_fp, max_bytes):
            self.target_fp = target_fp
            self.max_bytes = max_bytes
            self.written = 0

        def write(self, data):
            self.written += len(data)
            if self.written > self.max_bytes:
                raise ValueError("file_exceeds_4gb")
            return self.target_fp.write(data)

    tmp_dest = dest_path.with_suffix(dest_path.suffix + f".upload_tmp_{os.getpid()}_{int(datetime.now().timestamp()*1000)}")
    try:
        with open(tmp_dest, "wb") as f_out:
            bounded = BoundedWriter(f_out, MAX_FILE_SIZE)
            shutil.copyfileobj(file.file, bounded, length=1024 * 1024)

        actual_size = tmp_dest.stat().st_size
        # 复核实际写入后的磁盘剩余空间限制
        total_curr, used_curr, free_curr = shutil.disk_usage(ocr_input_dir)
        orig_free = free_curr + actual_size
        if orig_free < actual_size * 2:
            tmp_dest.unlink(missing_ok=True)
            free_gb = round(orig_free / (1024 ** 3), 2)
            needed_gb = round((actual_size * 2) / (1024 ** 3), 2)
            raise HTTPException(
                status_code=400,
                detail=f"磁盘剩余空间不足: 剩余可用 {free_gb} GB，导入该文件需要至少 {needed_gb} GB (文件大小 × 2)"
            )

        os.replace(tmp_dest, dest_path)
    except ValueError as ve:
        tmp_dest.unlink(missing_ok=True)
        if str(ve) == "file_exceeds_4gb":
            raise HTTPException(status_code=400, detail="单文件大小超过 4 GB 限制，拒绝上传")
        raise HTTPException(status_code=400, detail=f"文件写入失败: {ve}")
    except Exception as e:
        tmp_dest.unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"上传写入失败: {e}")
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    final_size = dest_path.stat().st_size
    rel_path = str(dest_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "filename": dest_path.name,
            "rel_path": rel_path,
            "abs_path": str(dest_path.resolve()),
            "size": final_size,
            "size_human": TaskManager._human_size(final_size)
        }
    }


@app.get("/api/tasks/{task_id}/video")
async def stream_task_video(task_id: str, request: Request, type: str = "output"):
    """流媒体切片视频传输，支持 HTTP 206 Partial Content (Range) 协议"""
    if task_id not in task_manager.tasks:
        task_manager.refresh_tasks()
    task = task_manager.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    video_path_str = task.get("video_file")
    if not video_path_str:
        raise HTTPException(status_code=404, detail="该任务尚无已生成的视频文件")

    video_path = Path(video_path_str)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"视频文件不存在: {video_path}")

    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")
    CHUNK_SIZE = 4 * 1024 * 1024

    if range_header:
        try:
            byte_range = range_header.replace("bytes=", "").split("-")
            start = int(byte_range[0])
            end = int(byte_range[1]) if byte_range[1] else min(start + CHUNK_SIZE - 1, file_size - 1)
        except ValueError:
            start = 0
            end = min(CHUNK_SIZE - 1, file_size - 1)

        if start >= file_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        end = min(end, file_size - 1)
        length = end - start + 1

        with open(video_path, "rb") as f:
            f.seek(start)
            data = f.read(length)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return Response(content=data, status_code=206, headers=headers)
    else:
        return FileResponse(
            path=str(video_path),
            media_type="video/mp4",
            headers={"Accept-Ranges": "bytes"}
        )


def format_seconds_to_timestamp(s: float) -> str:
    """时间戳格式化 mm:ss.xx"""
    m = int(s // 60)
    sec = int(s % 60)
    cs = int(round((s - int(s)) * 100))
    return f"{m:02d}:{sec:02d}.{cs:02d}"


@app.get("/api/tasks/{task_id}/subtitles")
async def get_task_subtitles(task_id: str):
    """
    P3: 获取任务的字幕行列表 (chinese.json)
    兼容读取: 先找 src，找不到回落 ja，并记录 deprecation 警告
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / "output" / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    c_path = work_dir / "chinese.json"
    if not c_path.exists():
        return {"code": 0, "message": "暂无字幕数据", "data": []}

    try:
        with open(c_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 chinese.json 失败: {e}")

    subtitles = []
    for idx, item in enumerate(data):
        src_text = get_subtitle_src(item, logger)
        src_raw = get_subtitle_src_raw(item, logger)
        subtitles.append({
            "index": idx + 1,
            "start": round(item.get("start", 0.0), 2),
            "end": round(item.get("end", 0.0), 2),
            "start_str": format_seconds_to_timestamp(item.get("start", 0.0)),
            "end_str": format_seconds_to_timestamp(item.get("end", 0.0)),
            "src": src_text,
            "src_raw": src_raw,
            "zh": item.get("zh", ""),
            "rejected": item.get("rejected", False),
            "incomplete": item.get("incomplete_translation", False),
            "duplicate_translation": item.get("duplicate_translation", False),
            "box": item.get("box")
        })

    return {
        "code": 0,
        "message": "success",
        "data": subtitles
    }


@app.put("/api/tasks/{task_id}/subtitles")
async def update_task_subtitles(task_id: str, req: Request):
    """
    P3: 行内改字保存接口 (更新 chinese.json，备份原文件)
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / "output" / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    body = await req.json()
    new_subtitles = body.get("subtitles", [])
    if not isinstance(new_subtitles, list):
        raise HTTPException(status_code=400, detail="字幕数据必须为列表格式")

    c_path = work_dir / "chinese.json"
    old_list = []
    if c_path.exists():
        try:
            shutil.copy2(c_path, work_dir / "chinese.json.bak")
            with open(c_path, "r", encoding="utf-8") as f:
                old_list = json.load(f)
        except Exception:
            pass

    updated_items = []
    for idx, item in enumerate(new_subtitles):
        base_item = dict(old_list[idx]) if idx < len(old_list) else {}
        base_item["start"] = item.get("start", base_item.get("start", 0.0))
        base_item["end"] = item.get("end", base_item.get("end", 0.0))
        base_item["src"] = item.get("src", base_item.get("src", base_item.get("ja", "")))
        base_item["src_raw"] = item.get("src_raw", base_item.get("src_raw", base_item.get("ja_raw", "")))
        base_item["zh"] = item.get("zh", "").strip()
        # 彻底移除旧字段，杜绝重复与冗余，新写入严格统一为 src / src_raw
        base_item.pop("ja", None)
        base_item.pop("ja_raw", None)
        if "box" in item:
            base_item["box"] = item["box"]
        updated_items.append(base_item)

    with open(c_path, "w", encoding="utf-8") as f:
        json.dump(updated_items, f, ensure_ascii=False, indent=2)

    # 即时重构 subtitle.ass 与 subtitle.srt (仅耗时 ~20ms)，使单帧预览无需全片重压制即可立即看到画面变化!
    try:
        from core.stages.layout_ass import LayoutAssStage
        from core.context import PipelineContext
        from lang import get_language

        lang_code = "ja"
        meta_file = work_dir / "task_meta.json"
        video_path = work_dir / "output.mp4"
        mode = "ocr"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as mf:
                    m = json.load(mf)
                    lang_code = m.get("lang", "ja")
                    mode = m.get("mode", "ocr")
                    if m.get("video_path") and Path(m["video_path"]).exists():
                        video_path = Path(m["video_path"])
            except Exception:
                pass

        lang_plugin = get_language(lang_code)
        ctx = PipelineContext(
            video_path=video_path,
            work_dir=work_dir,
            output_dir=work_dir,
            lang=lang_plugin,
            mode=mode,
            custom_params={}
        )
        LayoutAssStage().run(ctx, logger)
    except Exception as e:
        logger.warning(f"即时重生成 ASS 字幕失败 (将在重渲染时补充): {e}")

    return {
        "code": 0,
        "message": f"成功保存 {len(updated_items)} 条字幕改动并即时更新 ASS 排版"
    }


@app.get("/api/tasks/{task_id}/frame")
async def get_task_single_frame(task_id: str, time: float = 0.0):
    """
    P3: 精确单帧预览 API (严格遵循 M1 规范: -i 后再 -ss 精确 seek，加 sha256+T 缓存)
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / "output" / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    meta_file = work_dir / "task_meta.json"
    video_path = None
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                v_str = json.load(f).get("video_path")
                if v_str and Path(v_str).exists():
                    video_path = Path(v_str)
        except Exception:
            pass

    if not video_path:
        for cand in [work_dir / "output.mp4", PROJECT_ROOT / "input" / f"{task_id}.mp4", PROJECT_ROOT / "ocr_input" / f"{task_id}.mp4"]:
            if cand.exists():
                video_path = cand
                break

    if not video_path or not video_path.exists():
        for f in work_dir.glob("*.mp4"):
            video_path = f
            break

    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="未找到用于提取画面的片源视频")

    ass_path = work_dir / "subtitle.ass"
    ass_hash = "no_ass"
    if ass_path.exists():
        try:
            with open(ass_path, "rb") as af:
                ass_hash = hashlib.sha256(af.read()).hexdigest()[:16]
        except Exception:
            pass

    cache_dir = work_dir / ".frame_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = f"{ass_hash}_{round(time, 2):.2f}"
    cache_file = cache_dir / f"{cache_key}.jpg"

    if cache_file.exists() and cache_file.stat().st_size > 1000:
        return FileResponse(str(cache_file), media_type="image/jpeg")

    ffmpeg_bin = r"D:\Dev\ffmpeg\bin\ffmpeg.exe" if Path(r"D:\Dev\ffmpeg\bin\ffmpeg.exe").exists() else "ffmpeg"
    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(video_path),
        "-ss", str(round(time, 3)),
        "-vframes", "1"
    ]
    if ass_path.exists():
        escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        cmd.extend(["-vf", f"subtitles='{escaped_ass}'"])

    cmd.extend(["-q:v", "3", str(cache_file)])

    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not cache_file.exists():
        # 降级不带字幕滤镜渲染
        cmd_fallback = [
            ffmpeg_bin, "-y",
            "-i", str(video_path),
            "-ss", str(round(time, 3)),
            "-vframes", "1",
            "-q:v", "3", str(cache_file)
        ]
        res_fb = subprocess.run(cmd_fallback, capture_output=True)
        if res_fb.returncode != 0 or not cache_file.exists():
            raise HTTPException(status_code=500, detail="生成单帧预览图片失败")

    return FileResponse(str(cache_file), media_type="image/jpeg")


@app.post("/api/tasks/{task_id}/rerender")
async def rerender_task(task_id: str):
    """
    P3: 增量重渲染 (只跑排版与压制，跳过 OCR 和翻译)
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    res = queue_manager.submit_rerender(task_id)
    return {
        "code": 0,
        "message": "已成功提交增量重渲染队列",
        "data": res
    }


@app.get("/api/tasks/{task_id}/export/{format}")
async def export_task_product(task_id: str, format: str):
    """
    P3: 导出 ASS / SRT 字幕文件或最终视频
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / "output" / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    filename_map = {
        "ass": ("subtitle.ass", "application/x-ass"),
        "srt": ("subtitle.srt", "text/plain"),
        "video": ("output.mp4", "video/mp4"),
        "chinese": ("chinese.json", "application/json")
    }
    if format not in filename_map:
        raise HTTPException(status_code=400, detail=f"不支持的导出格式: {format}")

    fname, media_type = filename_map[format]
    file_path = work_dir / fname
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"产物文件不存在: {fname}")

    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=f"{task_id}_{fname}"
    )


@app.get("/api/tasks/{task_id}/file/{file_name}")
async def download_task_file(task_id: str, file_name: str):
    """
    P4: 下载任务工作目录下的指定产物文件
    """
    work_dir = PROJECT_ROOT / "work_tasks" / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / task_id
    if not work_dir.exists():
        work_dir = PROJECT_ROOT / "output" / task_id
    if not work_dir.exists():
        raise HTTPException(status_code=404, detail="任务工作目录不存在")

    safe_name = Path(file_name).name
    file_path = work_dir / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {safe_name}")

    media_type = "application/octet-stream"
    if safe_name.endswith(".mp4"):
        media_type = "video/mp4"
    elif safe_name.endswith(".ass"):
        media_type = "application/x-ass"
    elif safe_name.endswith(".srt") or safe_name.endswith(".log"):
        media_type = "text/plain"
    elif safe_name.endswith(".json"):
        media_type = "application/json"

    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=f"{task_id}_{safe_name}"
    )


@app.get("/api/system/engines")
async def get_system_engines():
    """获取所有可用翻译引擎配置与状态 (密钥脱敏)"""
    from core.translation_engine import load_engine_configs
    engines = load_engine_configs()
    data = [cfg.to_dict(mask_secrets=True) for cfg in engines.values()]
    return {
        "code": 0,
        "message": "success",
        "data": data
    }


@app.get("/api/system/asr_engines")
async def get_system_asr_engines():
    """获取所有可用 ASR 语音转写引擎配置与状态 (密钥脱敏)"""
    from core.asr_engine import load_asr_engine_configs
    asr_engines = load_asr_engine_configs()
    data = [cfg.to_dict(mask_secrets=True) for cfg in asr_engines.values()]
    return {
        "code": 0,
        "message": "success",
        "data": data
    }


@app.get("/api/system/settings")
async def get_system_settings():
    """P4: 系统只读设置与运行环境"""
    import os
    from core.translation_engine import load_engine_configs
    from core.asr_engine import load_asr_engine_configs
    ollama_models = os.environ.get("OLLAMA_MODELS", r"D:\Dev\ollama\models")
    ffmpeg_path = r"D:\Dev\ffmpeg\bin\ffmpeg.exe" if Path(r"D:\Dev\ffmpeg\bin\ffmpeg.exe").exists() else "ffmpeg"
    return {
        "code": 0,
        "message": "success",
        "data": {
            "port": 8000,
            "host": "127.0.0.1",
            "ollama_models_path": str(ollama_models),
            "ollama_url": "http://127.0.0.1:11434",
            "translation_model": "sakura-14b-qwen2.5-v1.0-iq4_xs",
            "ocr_engine": "RapidOCR (ONNX Runtime CUDA)",
            "ffmpeg_path": str(ffmpeg_path),
            "workspace_root": str(PROJECT_ROOT),
            "schema_version": 2,
            "engines": [cfg.to_dict(mask_secrets=True) for cfg in load_engine_configs().values()],
            "asr_engines": [cfg.to_dict(mask_secrets=True) for cfg in load_asr_engine_configs().values()]
        }
    }


@app.get("/api/system/gpu")
async def get_gpu_status():
    """实时读取本地 GPU 状态 (nvidia-smi)"""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split(",")
            name = lines[0].strip()
            total_mb = int(lines[1].strip())
            used_mb = int(lines[2].strip())
            free_mb = int(lines[3].strip())
            util_pct = float(lines[4].strip())
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "available": True,
                    "name": name,
                    "vram_total_mb": total_mb,
                    "vram_used_mb": used_mb,
                    "vram_free_mb": free_mb,
                    "utilization_percent": util_pct,
                    "queue_length": len(queue_manager.queue),
                    "active_task_id": queue_manager.active_task_id
                }
            }
    except Exception as e:
        logger.warning(f"读取 nvidia-smi 失败: {e}")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "available": False,
            "name": "N/A",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_free_mb": 0,
            "utilization_percent": 0.0,
            "queue_length": 0,
            "active_task_id": None
        }
    }


@app.get("/api/system/running_check")
async def system_running_check():
    """Z9: 查询当前服务是否有在途执行或排队中的任务"""
    has_running = queue_manager.has_running_tasks()
    summary = queue_manager.get_active_task_summary()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "has_running": has_running,
            "active_task": summary,
            "queue_length": len(queue_manager.queue),
            "pid": os.getpid()
        }
    }


@app.post("/api/system/interrupt_and_stop")
async def interrupt_and_stop(force: bool = False):
    """Z9: 安全中断任务并停止服务"""
    if queue_manager.has_running_tasks():
        summary = queue_manager.get_active_task_summary()
        if not force:
            raise HTTPException(
                status_code=400,
                detail=f"当前有任务正在执行 ({summary.get('task_id') if summary else '排队中'})，若需强制中断停服请携带 force=true"
            )
        queue_manager.interrupt_active_task(reason="远程管理强行中断停机")

    async def _delayed_shutdown():
        await asyncio.sleep(0.5)
        os._exit(0)

    asyncio.create_task(_delayed_shutdown())
    return {
        "code": 0,
        "message": "服务正在安全停止并释放资源..."
    }


# 挂载前端静态资源目录
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def check_remote_running_tasks(host: str = "127.0.0.1", port: int = 8000, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
    """Z9: 检查指定主机端口上已存在的 AnimeAutoSub 服务运行状态"""
    try:
        import urllib.request
        req = urllib.request.Request(f"http://{host}:{port}/api/system/running_check", headers={"User-Agent": "AnimeAutoSub-CLI"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("data")
    except Exception:
        pass
    return None


def request_remote_stop(host: str = "127.0.0.1", port: int = 8000, force: bool = False, timeout: float = 3.0) -> bool:
    """Z9: 优雅停止已有服务"""
    try:
        import urllib.request
        url = f"http://{host}:{port}/api/system/interrupt_and_stop?force={'true' if force else 'false'}"
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_available_port(host: str = "127.0.0.1", start_port: int = 8000, max_attempts: int = 20) -> int:
    """M5: 动态端口寻找 (8000 起占用则 +1 重试，最多 20 次)"""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"在 {host}:{start_port}~{start_port + max_attempts - 1} 范围内均未找到空闲端口！")


def start_server(host: str = "127.0.0.1", start_port: int = 8000, open_browser: bool = True):
    """启动 WebUI 服务并自动打开浏览器"""
    port = find_available_port(host, start_port, max_attempts=20)
    url = f"http://{host}:{port}"

    print("=" * 60)
    print(f"  🎉 AnimeAutoSub WebUI 服务已启动")
    print(f"  🌐 访问地址: {url}")
    print(f"  📂 扫描发现任务: {len(task_manager.tasks)} 个 (含正式与历史产物)")
    print("=" * 60)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"自动打开浏览器失败: {e}")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    import time
    parser = argparse.ArgumentParser(description="AnimeAutoSub WebUI")
    parser.add_argument("--port", type=int, default=8000, help="服务端口 (默认 8000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="绑定地址 (默认 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--force", action="store_true", help="强制重启服务（若有在途任务，安全中断打标后重启）")
    parser.add_argument("--check-running", action="store_true", help="仅检查当前端口是否有在途任务，有则退出码 2，无则退出码 0")
    args = parser.parse_args()

    # 1. 预检在途任务 (供重启脚本 / CLI 查询)
    if args.check_running:
        status = check_remote_running_tasks(args.host, args.port)
        if status and status.get("has_running"):
            task_info = status.get("active_task") or {}
            task_id = task_info.get("task_id", "未知")
            stage = task_info.get("current_stage", "-")
            pct = task_info.get("stage_pct", 0.0)
            total = task_info.get("total_pct", 0.0)
            q_len = status.get("queue_length", 0)
            print(f"[WARN] 发现端口 {args.port} 上有在途任务正在运行:")
            print(f"       - 活跃任务: {task_id}")
            print(f"       - 当前阶段: {stage} ({pct}%)，总进度: {total}%")
            print(f"       - 队列积压: {q_len} 个任务")
            sys.exit(2)
        else:
            print(f"[OK] 端口 {args.port} 无在途运行任务 (服务空闲或离线)")
            sys.exit(0)

    # 2. 启动前安全检查 (Z9)
    status = check_remote_running_tasks(args.host, args.port)
    if status:
        if status.get("has_running") and not args.force:
            task_info = status.get("active_task") or {}
            task_id = task_info.get("task_id", "未知")
            stage = task_info.get("current_stage", "-")
            pct = task_info.get("stage_pct", 0.0)
            total = task_info.get("total_pct", 0.0)
            q_len = status.get("queue_length", 0)
            print("=" * 60)
            print(f"[WARNING] 检测到端口 {args.port} 已有服务正在运行 (PID: {status.get('pid')})，且有在途任务！")
            print(f"          - 活跃任务: {task_id}")
            print(f"          - 当前阶段: {stage} ({pct}%)，总进度: {total}%")
            print(f"          - 排队任务: {q_len} 个")
            print("[ERROR] 严禁在任务运行中直接重启或强占端口！否则将导致在途任务被强制中断。")
            print("        若确实需要强行停止并重启，请在命令行传入 --force 参数。")
            print("=" * 60)
            sys.exit(1)
        elif status.get("has_running") and args.force:
            print(f"[INFO] 收到 --force 指令，正在安全中断端口 {args.port} 上的在途任务并停止旧服务...")
            request_remote_stop(args.host, args.port, force=True)
            time.sleep(1.5)
        elif not status.get("has_running"):
            print(f"[INFO] 端口 {args.port} 上已有空闲服务 (PID: {status.get('pid')})，正在优雅停止旧实例以重新启动...")
            request_remote_stop(args.host, args.port, force=False)
            time.sleep(1.0)

    open_b = not args.no_browser and os.environ.get("NO_BROWSER") != "1"
    start_server(host=args.host, start_port=args.port, open_browser=open_b)
