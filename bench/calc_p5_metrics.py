"""
[STATUS: REJECTED / 已废止 - 归档脚本]
统计 P5 算法核心指标（因长集严重退化，P5 整体已废止）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
from animeautosub.core.comparator import levenshtein_distance

with open("bench/p5_final_eval_report.json", "r", encoding="utf-8") as f:
    data = json.load(f)

short_frames = data["short_15_frames"]["frames"]

# 分析短集 15 帧中双行/漏行/截断的分布
# 真值中实际属于多行或长句包含双行特征的帧：
# 帧 02: 2 行 ("つまり今日の家事は、拓斗の面倒を見ながら/しなくてはいけないようだ。")
# 帧 04: 2 行 ("拓斗「えー？じゃあ、/手伝ったらお昼ご飯、俺の好きなやつ作ってくれる？」")
# 帧 06: 2 行 ("枝彌「いい加減にしなさい。あなた、もう何日も帰ってないんでしょう？/今どこにいるの？」")
# 帧 08: 2 行 ("恵麻「……うっざ。/別にいいでしょ、私がどうしようがさ」")
# 帧 09: 2 行 ("恵麻「とぼける気？まあ別にいいけど。/でもさ、男遊びがどうとか、お母さんに言う権利、なくない？」")
# 帧 10: 2 行 ("恵麻「あーもう、だからほっといてってば！/あの子たちが心配なら勝手にして！」")

double_line_fids = [2, 4, 6, 8, 9, 10]

print("=== P5 核心指标统计 (15 帧短集) ===")
# 1. 双行合并正确率
correct_merges = 0
for fid in double_line_fids:
    frame = next(f for f in short_frames if f["id"] == fid)
    # 判定双行是否按正确顺序合并（没有出现上下行倒错或中间插塞）
    # 帧 02: つまり念日の家家事は、拓斗の面倒を見ながらしなくてほいけないようだ。 -> 顺序正确
    # 帧 04: 拓斗しゃあ、手伝ったらお昼ご飯、俺の好きなやつ作ってくれる?」 -> 顺序正确
    # 帧 06: 枝彌「いい加減にしなさい。あなた、もう何日もも帰ってないんでしょう？今どごにいるの？」 -> 顺序正确
    # 帧 08: 惠麻80xうっざ。別にいいでしよ、私がどうしようがさ」 -> 顺序正确
    # 帧 10: 惠麻あの子「あ一もう、だからほたちが心配なら勝手に -> 部分倒错
    txt = frame["txt_p5"]
    print(f"双行帧 {fid:02d}: lines={frame['num_lines']} | text={txt}")

# 2. 截断类错误数与漏行类错误数在 P5 前后对比
# 重新计算 short 15 帧在 P5 后的逐帧编辑
print("\n逐帧对比:")
for f in short_frames:
    print(f"帧 {f['id']:02d}: Base_dist={f['dist_base']:2d} -> P5_dist={f['dist_p5']:2d}")
