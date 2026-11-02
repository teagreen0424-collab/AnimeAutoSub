import json
import re
from pathlib import Path

transcript_path = Path(r"C:\Users\10932\.gemini\antigravity\brain\c1431835-b8d6-4e48-8544-6afb74257c21\.system_generated\logs\transcript.jsonl")

keywords = ["remove", "unlink", "del ", "rm ", "ocr_input", "recycle", "trash", "$r"]

with open(transcript_path, "r", encoding="utf-8") as f:
    for line_idx, line in enumerate(f):
        data = json.loads(line)
        step = data.get("step_index", line_idx)
        content = str(data.get("content", ""))
        tool_calls = str(data.get("tool_calls", ""))
        combined = (content + " " + tool_calls).lower()
        
        # Check if ocr_input AND deletion keyword appear
        if "ocr_input" in combined and any(k in combined for k in ["remove", "unlink", "del", "rm", "recycle", "trash"]):
            print(f"Step {step}: (Line {line_idx})")
            if tool_calls:
                print(f"  Tool calls: {tool_calls[:200]}")
            if content:
                print(f"  Content snippet: {content[:200]}")
