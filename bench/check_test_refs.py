import pathlib
import re

for p in pathlib.Path('tests').glob('*.py'):
    content = p.read_text(encoding='utf-8')
    matches = re.findall(r'bench[\\/][^\s\'\"]+', content)
    if matches:
        print(p.name, set(matches))
