# -*- coding: utf-8 -*-
"""关键测量：索引里「已展示过」的条目，你实际存进 Zotero 的有多少？按源/类型拆开。

这决定 P2 该做「打分规则」还是「反馈闭环」。
"""
import importlib.util
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

WD = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('wd', WD / 'weekly_digest.py')
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)
cfg = json.loads((WD / 'sources.json').read_text(encoding='utf-8-sig'))

zot_urls, zot_titles, ok = wd.load_zotero_keys(
    cfg.get('zoteroDb', str(Path.home() / 'Zotero' / 'zotero.sqlite')))
print('Zotero 读取：%s（%d URL / %d 标题）' % ('成功' if ok else '失败',
                                            len(zot_urls), len(zot_titles)))

con = sqlite3.connect(f'file:{(WD / "index.sqlite").as_posix()}?mode=ro', uri=True)
rows = con.execute(
    "SELECT source, type, title, nurl, ntitle, status, list_id FROM items").fetchall()
con.close()

print('索引共 %d 条' % len(rows))
st = defaultdict(int)
for r in rows:
    st[r[5]] += 1
print('  状态分布:', dict(st))

shown = [r for r in rows if r[5] == 'shown']
print()
print('=' * 84)
print('已展示过的 %d 条里，有多少现在躺在你的 Zotero 里？' % len(shown))
print('=' * 84)


def in_zotero(r):
    _, _, title, nurl, ntitle, _, _ = r
    if nurl in zot_urls:
        return True
    nt = ntitle or ''
    return bool(nt) and len(nt) >= wd.MIN_TITLE_FP and nt in zot_titles


hit = [r for r in shown if in_zotero(r)]
print('  命中 %d / %d = %.1f%%' % (len(hit), len(shown),
                                   len(hit) * 100 / max(1, len(shown))))

print()
print('按来源：')
d = defaultdict(lambda: [0, 0])
for r in shown:
    d[r[0] or '?'][1] += 1
    if in_zotero(r):
        d[r[0] or '?'][0] += 1
for s, (h, t) in sorted(d.items(), key=lambda x: -(x[1][0] / max(1, x[1][1]))):
    print('   %-22s %2d/%2d = %3d%%' % (s[:20], h, t, h * 100 // max(1, t)))

print()
print('按类型：')
d2 = defaultdict(lambda: [0, 0])
for r in shown:
    d2[r[1] or '?'][1] += 1
    if in_zotero(r):
        d2[r[1] or '?'][0] += 1
for s, (h, t) in d2.items():
    print('   %-8s %2d/%2d = %3d%%' % (s, h, t, h * 100 // max(1, t)))

print()
print('按清单文件（看不同期次）：')
d3 = defaultdict(lambda: [0, 0])
for r in shown:
    d3[(r[6] or '?')[:28]][1] += 1
    if in_zotero(r):
        d3[(r[6] or '?')[:28]][0] += 1
for s, (h, t) in sorted(d3.items()):
    print('   %-30s %2d/%2d' % (s, h, t))
