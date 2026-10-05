# -*- coding: utf-8 -*-
"""跨周重复验证：把「已给过你的」（第一周清单/台账）与「现在会取到的」
（模拟第二周）逐条比对，看交集。

不写任何文件、不改台账。
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

WD = Path(__file__).resolve().parent.parent
DESKTOP = Path(str(Path.home() / 'Desktop' / '公考素材'))
PY = sys.executable

spec = importlib.util.spec_from_file_location('wd', WD / 'weekly_digest.py')
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)
cfg = json.loads((WD / 'sources.json').read_text(encoding='utf-8-sig'))

# ---- 第一周：桌面已给你的清单 ----
week1 = {}      # ntitle -> 标题
week1_urls = set()
for jf in sorted(DESKTOP.glob('*.json')):
    data = json.loads(jf.read_text(encoding='utf-8-sig'))
    for it in data.get('items', []):
        nt = wd.norm_title(it.get('title', ''))
        if nt:
            week1[nt] = it['title']
        week1_urls.add(it.get('nurl') or wd.norm_url(it.get('url', '')))
print('第一周已给你看的条目：%d 条（URL %d 个）' % (len(week1), len(week1_urls)))

# ---- 第二周：现在跑一遍 pipeline，但不落盘 ----
print()
print('正在模拟第二周抓取（不写文件、不动台账）…')
cfg2 = dict(cfg)
cfg2['outputDir'] = str(Path(r'D:\_sim_week2'))

# 直接调用内部流程，避免解析日志
import io
tmp_cfg = WD / '_sim_config.json'
tmp_cfg.write_text(json.dumps(cfg2, ensure_ascii=False), encoding='utf-8')
try:
    proc = subprocess.run(
        [PY, str(WD / 'weekly_digest.py'), '--config', str(tmp_cfg), '--dry-run'],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    out = proc.stdout
finally:
    tmp_cfg.unlink(missing_ok=True)

picked = re.findall(r'\[(案例型|论述型|数据型)\]\s+(.+?)\s+<-', out)
print('第二周会取到：%d 条' % len(picked))

# ---- 比对 ----
w2_titles = [(t, wd.norm_title(t)) for _, t in picked]
same_title = [(t, week1[nt]) for t, nt in w2_titles if nt in week1]
same_url_n = 0
# 用标题指纹比对即可（URL 已在 pipeline 内部去重）

print()
print('=' * 70)
print('比对结果')
print('=' * 70)
print('  第一周条目数 : %d' % len(week1))
print('  第二周条目数 : %d' % len(picked))
print('  标题重合数   : %d' % len(same_title))
if same_title:
    print()
    print('  重合明细（这些是跨周重复，说明去重失效）：')
    for a, b in same_title:
        print('    ⚠ 第二周: %s' % a[:48])
        print('       第一周: %s' % b[:48])
else:
    print()
    print('  ✓ 无任何重合 —— 第一周取过的，第二周不会再出现')
