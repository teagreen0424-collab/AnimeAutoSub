import os
import re

p_jaraw = re.compile(r'["\']ja_raw["\']')
p_ja = re.compile(r'["\']ja["\']')
p_ch = re.compile(r'chinese\.json')

for root, dirs, files in os.walk('.'):
    if any(x in root for x in ['.git', '.venv', 'venv', 'work_tasks', 'work_ko', 'output', 'bench', 'logs']):
        continue
    for f in files:
        if f.endswith(('.py', '.js', '.html')):
            fpath = os.path.join(root, f)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                    for idx, line in enumerate(fp, 1):
                        if p_jaraw.search(line) or p_ch.search(line):
                            print(f"{fpath}:{idx}: {line.strip()[:100]}")
            except Exception:
                pass
