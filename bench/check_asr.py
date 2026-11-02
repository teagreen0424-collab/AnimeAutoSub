import json

with open('work_ko_asr_final/asr_raw.json', 'r', encoding='utf-8') as f:
    asr = json.load(f)

print(f"--- ASR Segments Count: {len(asr)} ---")
for s in asr:
    print(f"[{s['start']} - {s['end']}] {s['text']}")
