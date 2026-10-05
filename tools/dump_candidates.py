# -*- coding: utf-8 -*-
"""把候选标题全部列出来，人工找出「确定性噪音」形态。"""
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / 'index.sqlite'
con = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
rows = con.execute(
    "SELECT source, title FROM items WHERE status='new' ORDER BY source, published DESC"
).fetchall()
con.close()

by = defaultdict(list)
for s, t in rows:
    by[s or '?'].append(t or '')

for s in sorted(by, key=lambda x: -len(by[x])):
    print('=' * 100)
    print('【%s】%d 条' % (s, len(by[s])))
    print('=' * 100)
    for t in by[s]:
        print('  ' + t)
    print()
