"""
AnimeAutoSub 流水线调度引擎与 CLI 入口 (core/pipeline.py)

硬性契约:
  - 严格三元组跳过检查 (manifest.json)
  - GPU 阶段自动获取 GPU 独占租约
  - 幂等、可取消、阶段错误阻断
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import List, Optional

from lang import get_language, SUPPORTED_LANGUAGES
from .context import PipelineContext, CancelToken
from .stage import Stage
from .manifest import ManifestManager, compute_files_sha256
from .gpu_lease import acquire_gpu_lease

from .stages.ocr_extract import OcrExtractStage
from .stages.asr import AsrStage
from .stages.translate import TranslateStage
from .stages.layout_ass import LayoutAssStage
from .stages.burn_subtitles import BurnSubtitlesStage
from .stages.verify_metrics import VerifyMetricsStage


def setup_pipeline_logging(work_dir: Path) -> logging.Logger:
    log = logging.getLogger("AnimeAutoSub")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    log.addHandler(ch)

    fh = logging.FileHandler(str(work_dir / "pipeline.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    log.addHandler(fh)
    return log


def get_tool_version(stage: Stage) -> str:
    """获取该阶段依赖的核心工具版本"""
    if stage.name == "ocr_extract":
        return "RapidOCR_v3.10_ONNX_HEURISTIC"
    elif stage.name == "translate":
        return "Sakura14B_Ollama_v1"
    elif stage.name == "layout_ass":
        return "Layout_Adaptive_v2"
    elif stage.name == "burn_subtitles":
        return "FFmpeg_libx264_crf20"
    return "v1.0"


def check_environment(log: logging.Logger, ctx: Optional[PipelineContext] = None) -> bool:
    """环境自检与 Ollama 服务自愈 (仅当使用本地 Ollama 引擎时才触发检查)"""
    import requests
    import subprocess

    # 若当前任务使用的是云端 API 翻译引擎，则无需唤醒本地 Ollama
    if ctx and hasattr(ctx, "engine_id") and ctx.engine_id:
        try:
            from .translation_engine import get_engine_config
            eng = get_engine_config(ctx.engine_id)
            if eng.type != "ollama":
                return True
        except Exception:
            pass

    ollama_ok = False
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if r.status_code == 200:
            ollama_ok = True
    except Exception:
        pass

    if not ollama_ok:
        ollama_exe = Path(r"D:\Dev\ollama\ollama.exe")
        if ollama_exe.exists():
            log.info("  → 检测到 Ollama 未运行，正在后台自动拉起...")
            env = os.environ.copy()
            env["OLLAMA_MODELS"] = r"D:\Dev\ollama\models"
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS if os.name == 'nt' else 0
            )
            time.sleep(3)
            return True
        else:
            log.error("  ✗ 无法连接 Ollama 且本地未找到 ollama.exe")
            return False
    return True


class Pipeline:
    def __init__(self, ctx: PipelineContext, stages: Optional[List[Stage]] = None):
        self.ctx = ctx
        self.manifest = ManifestManager(ctx.work_dir)
        self.log = setup_pipeline_logging(ctx.work_dir)
        check_environment(self.log, self.ctx)

        if stages is not None:
            self.stages = stages
        else:
            if ctx.mode == "ocr":
                self.stages = [
                    OcrExtractStage(),
                    TranslateStage(),
                    LayoutAssStage(),
                    BurnSubtitlesStage(),
                    VerifyMetricsStage()
                ]
            else:
                # ASR 模式
                self.stages = [
                    AsrStage(),
                    TranslateStage(),
                    LayoutAssStage(),
                    BurnSubtitlesStage(),
                    VerifyMetricsStage()
                ]

    def _get_upstream_hash(self, stage: Stage) -> str:
        """获取当前阶段上游依赖产物的联合 SHA256"""
        stage_idx = self.stages.index(stage)
        upstream_paths = []
        for prev_stage in self.stages[:stage_idx]:
            for p_name in prev_stage.produces:
                p_file = self.ctx.get_product_path(p_name)
                if p_file.exists():
                    upstream_paths.append(p_file)
        if not upstream_paths:
            # 第一阶段以上游原视频元数据作为输入
            return f"video_{self.ctx.video_path.name}_{self.ctx.video_path.stat().st_size}"
        return compute_files_sha256(upstream_paths)

    def run(self) -> bool:
        self.log.info("=" * 60)
        self.log.info(f"  AnimeAutoSub 启动 (语言: [{self.ctx.lang.name}], 模式: [{self.ctx.mode}])")
        self.log.info(f"  输入片源: {self.ctx.video_path}")
        self.log.info(f"  工作目录: {self.ctx.work_dir}")
        self.log.info("=" * 60)

        for stage in self.stages:
            stage.ctx = self.ctx
            if self.ctx.cancel_token.is_cancelled():
                self.log.warning(f"  ⚠ 任务已取消: {self.ctx.cancel_token.reason}")
                return False

            tool_version = get_tool_version(stage)
            upstream_hash = self._get_upstream_hash(stage)

            # 硬性三元组跳过校验: 参数指纹 + 上游产物哈希 + 工具版本
            if self.manifest.should_skip(stage, self.ctx, upstream_hash, tool_version):
                self.log.info(f"  ⚡ [{stage.name}] 三元组校验命中（指纹/上游哈希/工具版本完全一致），安全跳过")
                continue

            self.log.info(f"  ▶ [{stage.name}] 开始执行 (GPU需求: {stage.requires_gpu})...")
            self.manifest.record_stage_start(stage)

            try:
                if stage.requires_gpu:
                    with acquire_gpu_lease(required_vram_mb=1200):
                        stage.run(self.ctx, self.log, self.ctx.cancel_token)
                else:
                    stage.run(self.ctx, self.log, self.ctx.cancel_token)

                if self.ctx.cancel_token.is_cancelled():
                    self.log.warning(f"  ⚠ [{stage.name}] 在执行中被中断取消")
                    return False

                if not stage.verify(self.ctx):
                    err = f"阶段产物校验失败: {stage.produces}"
                    self.manifest.record_stage_failed(stage, err)
                    raise RuntimeError(err)

                self.manifest.record_stage_completed(stage, self.ctx, upstream_hash, tool_version)
                self.log.info(f"  ✓ [{stage.name}] 阶段执行成功并完成产物核验")

            except Exception as e:
                self.log.error(f"  ✗ [{stage.name}] 执行异常崩溃: {e}", exc_info=True)
                self.manifest.record_stage_failed(stage, str(e))
                raise

        self.log.info("=" * 60)
        self.log.info(f"  🎉 全部阶段执行完毕！最终成片位于: {self.ctx.get_product_path('output.mp4')}")
        self.log.info("=" * 60)
        return True


def main():
    parser = argparse.ArgumentParser(description="AnimeAutoSub 结构解耦主线入口")
    parser.add_argument("video", type=str, help="输入视频文件路径")
    parser.add_argument("--lang", type=str, default="ja", choices=list(SUPPORTED_LANGUAGES.keys()), help="源语言")
    parser.add_argument("--mode", type=str, default="ocr", choices=["ocr", "asr"], help="提取模式")
    parser.add_argument("--work-dir", type=str, default=None, help="临时工作目录")
    parser.add_argument("--output-dir", type=str, default="output", help="成片产物目录")

    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        print(f"错误: 找不到视频文件 {video_path}")
        sys.exit(1)

    lang_plugin = get_language(args.lang)
    work_dir = Path(args.work_dir) if args.work_dir else Path(f"work_{video_path.stem}_{args.mode}")
    output_dir = Path(args.output_dir)

    ctx = PipelineContext(
        video_path=video_path,
        work_dir=work_dir,
        output_dir=output_dir,
        lang=lang_plugin,
        mode=args.mode
    )

    pipeline = Pipeline(ctx)
    success = pipeline.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
