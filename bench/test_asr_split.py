import sys
sys.path.insert(0, ".")
import animeautosub._env
from faster_whisper import WhisperModel
import json

model = WhisperModel(r"D:\Dev\huggingface\models--faster-whisper-large-v3", device="cuda", compute_type="float16")
segments, info = model.transcribe(
    "input/simulated_ko_asr_20.mp3",
    language="ko",
    beam_size=5,
    vad_filter=True,
    word_timestamps=True
)

res = []
for s in segments:
    words = list(s.words or [])
    cur_words = []
    for w in words:
        cur_words.append(w)
        if w.word.strip().endswith((".", "?", "!")):
            text_sub = "".join(x.word for x in cur_words).strip()
            res.append({
                "start": round(cur_words[0].start, 2),
                "end": round(cur_words[-1].end, 2),
                "text": text_sub
            })
            cur_words = []
    if cur_words:
        text_sub = "".join(x.word for x in cur_words).strip()
        res.append({
            "start": round(cur_words[0].start, 2),
            "end": round(cur_words[-1].end, 2),
            "text": text_sub
        })

print(f"Sentence split count: {len(res)}")
for idx, r in enumerate(res):
    print(f"#{idx+1:02d}: [{r['start']}s - {r['end']}s] {r['text']}")

with open("bench/asr_split_20.json", "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
