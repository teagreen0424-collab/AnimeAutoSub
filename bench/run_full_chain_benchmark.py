import sys
import os
import time
import json
import logging
import threading
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animeautosub._env
import pipeline_ocr
import config_ocr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class VRAMMonitor:
    def __init__(self, interval_sec=1.0):
        self.interval = interval_sec
        self.running = False
        self.peak_vram = 0
        self.current_stage = "idle"
        self.stage_peaks = {}
        self.thread = None

    def _monitor(self):
        while self.running:
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=2
                )
                val = int(out.strip().splitlines()[0])
                if val > self.peak_vram:
                    self.peak_vram = val
                cur_peak = self.stage_peaks.get(self.current_stage, 0)
                if val > cur_peak:
                    self.stage_peaks[self.current_stage] = val
            except Exception:
                pass
            time.sleep(self.interval)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def set_stage(self, stage_name):
        self.current_stage = stage_name
        if stage_name not in self.stage_peaks:
            self.stage_peaks[stage_name] = 0

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)

def run_chain_b_benchmark(video_path: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "v5_chain_b_benchmark_report.json"

    monitor = VRAMMonitor(interval_sec=1.0)
    monitor.start()

    t_total_start = time.time()
    stage_timings = {}

    logging.info("=" * 70)
    logging.info(f"  Chain B (Hardsub OCR Pipeline) 全量生产基线重测 (V5)")
    logging.info(f"  素材: {video_path} (69分15秒)")
    logging.info(f"  产物目录: {output_dir}")
    logging.info("=" * 70)

    # ---------------- Stage 1: OCR Extraction ----------------
    monitor.set_stage("Stage 1: OCR Extraction")
    logging.info("\n>>> [Stage 1/5] 抽帧与画面 OCR (RapidOCR + HEURISTIC)...")
    t0 = time.time()
    segments = pipeline_ocr.extract_hardsub_from_video(video_path, output_dir)
    stage_timings["stage1_ocr_s"] = round(time.time() - t0, 2)
    logging.info(f">>> Stage 1 完成，耗时: {stage_timings['stage1_ocr_s']:.2f}s，提取字幕: {len(segments)} 句")

    # ---------------- Stage 2: Translation & N5 Sanitization ----------------
    monitor.set_stage("Stage 2: Translation (Sakura-14B)")
    logging.info("\n>>> [Stage 2/5] Sakura-14B 翻译与局部乱码智能切除...")
    t0 = time.time()
    translated = pipeline_ocr.translate_segments(segments, output_dir)
    stage_timings["stage2_translate_s"] = round(time.time() - t0, 2)
    logging.info(f">>> Stage 2 完成，耗时: {stage_timings['stage2_translate_s']:.2f}s，翻译完成: {len(translated)} 句")

    # ---------------- Stage 3: Subtitles & Adaptive Mask ----------------
    monitor.set_stage("Stage 3: Subtitles & Layout")
    logging.info("\n>>> [Stage 3/5] 自适应排版与遮罩生成 (ASS/SRT)...")
    t0 = time.time()
    ass_path, srt_path = pipeline_ocr.generate_subtitles(translated, output_dir)
    stage_timings["stage3_subtitles_s"] = round(time.time() - t0, 2)
    logging.info(f">>> Stage 3 完成，耗时: {stage_timings['stage3_subtitles_s']:.2f}s")

    # ---------------- Stage 4: Soft Subtitle Muxing ----------------
    monitor.set_stage("Stage 4: MKV Muxing")
    logging.info("\n>>> [Stage 4/5] 封装软字幕 MKV...")
    t0 = time.time()
    mkv_out = output_dir / f"{video_path.stem}_中文字幕.mkv"
    pipeline_ocr.mux_mkv(video_path, ass_path, mkv_out)
    stage_timings["stage4_mux_mkv_s"] = round(time.time() - t0, 2)
    logging.info(f">>> Stage 4 完成，耗时: {stage_timings['stage4_mux_mkv_s']:.2f}s")

    # ---------------- Stage 5: Hardcode MP4 Encoding ----------------
    monitor.set_stage("Stage 5: Hardcode MP4")
    logging.info("\n>>> [Stage 5/5] 压制硬字幕 MP4...")
    t0 = time.time()
    mp4_out = output_dir / f"{video_path.stem}_中文字幕.mp4"
    pipeline_ocr.hardcode_mp4(video_path, ass_path, mp4_out)
    stage_timings["stage5_hardcode_mp4_s"] = round(time.time() - t0, 2)
    logging.info(f">>> Stage 5 完成，耗时: {stage_timings['stage5_hardcode_mp4_s']:.2f}s")

    t_total = time.time() - t_total_start
    monitor.stop()

    # Load rejection report
    rej_data = {}
    rej_path = output_dir / "n5_rejection_report.json"
    if rej_path.exists():
        with open(rej_path, "r", encoding="utf-8") as f:
            rej_data = json.load(f)

    # Load Stage 1 timing report
    st1_data = {}
    st1_path = output_dir / "stage1_production_timing_report.json"
    if st1_path.exists():
        with open(st1_path, "r", encoding="utf-8") as f:
            st1_data = json.load(f)

    final_report = {
        "video": str(video_path),
        "duration_min": 69.25,
        "total_wall_time_s": round(t_total, 2),
        "total_wall_time_min": round(t_total / 60.0, 2),
        "historical_baseline_s": 4003.3,
        "historical_baseline_min": 66.72,
        "speedup_ratio": round(4003.3 / max(0.1, t_total), 2),
        "time_saved_s": round(4003.3 - t_total, 2),
        "time_saved_min": round((4003.3 - t_total) / 60.0, 2),
        "stage_timings_sec": stage_timings,
        "peak_vram_mb": monitor.peak_vram,
        "stage_peak_vram_mb": monitor.stage_peaks,
        "artifacts": {
            "japanese_json": str(output_dir / "japanese.json"),
            "chinese_json": str(output_dir / "chinese.json"),
            "subtitle_ass": str(ass_path),
            "subtitle_srt": str(srt_path),
            "mkv": str(mkv_out),
            "mp4": str(mp4_out),
            "mkv_size_mb": round(mkv_out.stat().st_size / 1024 / 1024, 2) if mkv_out.exists() else 0,
            "mp4_size_mb": round(mp4_out.stat().st_size / 1024 / 1024, 2) if mp4_out.exists() else 0
        },
        "rejection_summary": rej_data,
        "stage1_timing_summary": st1_data.get("timings_sec", {})
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)

    logging.info("=" * 70)
    logging.info(f"  ✓ Chain B 69 分钟全片全链路压制完成！")
    logging.info(f"  总耗时: {final_report['total_wall_time_s']}s ({final_report['total_wall_time_min']} 分钟)")
    logging.info(f"  对比 4003.3s 历史基线: 净节省 {final_report['time_saved_min']} 分钟 (加速比: {final_report['speedup_ratio']}x)")
    logging.info(f"  峰值显存: {monitor.peak_vram} MB")
    logging.info(f"  报告已保存: {report_file}")
    logging.info("=" * 70)

if __name__ == "__main__":
    v_path = Path("ocr_input/114877-720p.mp4")
    out_dir = Path("ocr_output/114877-720p")
    run_chain_b_benchmark(v_path, out_dir)
