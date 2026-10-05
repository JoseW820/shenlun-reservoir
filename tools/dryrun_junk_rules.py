# -*- coding: utf-8 -*-
"""确定性剔除规则干跑：列出每条规则会剔掉哪些候选，供人工核对有无误杀。"""
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / 'index.sqlite'
con = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
rows = con.execute("SELECT source, title FROM items WHERE status='new'").fetchall()
con.close()

RULES = [
    ('① 报刊版面责任署名', re.compile(r'^(?:\d+版|本版|第\d+版)?\s*责编\s*[：:]|'
                                  r'[一二三四五六七八九十\d]+版责编\s*[：:]')),
    ('② 无正文形态（单独成题）', re.compile(r'^(?:图片报道|图片新闻|组图|图集|视频|图解|海报|'
                                     r'H5|微视频|直播|图片|专题片|短片|动漫)$')),
    ('③ 图解页（开头即"一图读懂"类）', re.compile(r'^(?:一图读懂|一图速览|图说|图解)\s*')),
    ('④ 节日祝贺/问候（礼节性）', re.compile(r'致以.{0,12}(?:祝贺|问候|节日)')),
    ('⑤ 纯目录/要目', re.compile(r'^(?:目录|本期目录|要目|总目录|导读)$')),
    ('⑥ 纯活动预告（"将于…启幕/举办"结尾）',
     re.compile(r'(?:将于|即将|拟于).{0,20}(?:启幕|启动|举行|举办|开幕|上线)\s*$')),
]

print('候选总数：%d' % len(rows))
print()
total_removed = 0
for name, pat in RULES:
    hits = [(s, t) for s, t in rows if pat.search(t or '')]
    total_removed += len(hits)
    print('=' * 100)
    print('%s  →  命中 %d 条' % (name, len(hits)))
    print('=' * 100)
    for s, t in hits:
        print('   [%s] %s' % ((s or '')[:12], (t or '')[:74]))
    if not hits:
        print('   （无）')
    print()

# 合并后的净剔除数（去重）
removed = set()
for name, pat in RULES:
    for s, t in rows:
        if pat.search(t or ''):
            removed.add(t)
print('=' * 100)
print('合并后净剔除：%d 条 / %d = %.1f%%' % (len(removed), len(rows),
                                      len(removed) * 100 / len(rows)))
print('=' * 100)
for t in sorted(removed):
    print('   ' + t[:80])
