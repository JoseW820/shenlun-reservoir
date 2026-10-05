# -*- coding: utf-8 -*-
"""核对：配置里用的集合名  vs  Zotero 里实际存在的集合。

**读取顺序很重要**：优先本地 API（实时，能看到刚做的改动），
再退到只读 SQLite，最后才用快照。
早先这个工具直接用 `immutable=1` 读数据库 —— 那会忽略 WAL 日志，
在你刚改过分类树之后会读到**旧结构**，从而误报「找不到」。
"""
import json
import re
import sqlite3
import urllib.request
from collections import defaultdict
from pathlib import Path

WD = Path(__file__).resolve().parent.parent
CFG = WD / 'sources.json'
API = 'http://127.0.0.1:23119/api/users/0'


def _build(rows):
    """rows = [(id, name, parent_id)] -> 完整路径列表"""
    kids = defaultdict(list)
    for cid, name, pid in rows:
        kids[pid].append((cid, name))
    out = []

    def walk(pid, prefix):
        for cid, name in sorted(kids.get(pid, []), key=lambda x: x[1]):
            full = (prefix + '/' + name) if prefix else name
            out.append(full)
            walk(cid, full)

    walk(None, '')
    return out or None


def from_api():
    """本地 API（实时）。"""
    try:
        req = urllib.request.Request(API + '/collections?limit=200',
                                     headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            cols = json.loads(r.read().decode('utf-8'))
    except Exception:
        return None
    kids = defaultdict(list)
    for c in cols:
        kids[c['data'].get('parentCollection')].append(c)
    out = []

    def walk(parent, prefix):
        for c in sorted(kids.get(parent, []), key=lambda x: x['data']['name']):
            name = c['data']['name']
            full = (prefix + '/' + name) if prefix else name
            out.append(full)
            walk(c['key'], full)

    walk(False, '')
    walk(None, '')
    return out or None


def from_db(immutable):
    """从数据库读。immutable=True 会忽略 WAL，可能读到旧结构。"""
    cfg = json.loads(CFG.read_text(encoding='utf-8-sig'))
    db = Path(cfg.get('zoteroDb') or str(Path.home() / 'Zotero' / 'zotero.sqlite'))
    if not db.exists():
        return None
    uri = f'file:{db.as_posix()}?mode=ro' + ('&immutable=1' if immutable else '')
    try:
        con = sqlite3.connect(uri, uri=True, timeout=8)
        rows = con.execute(
            'SELECT collectionID, collectionName, parentCollectionID FROM collections'
        ).fetchall()
        con.close()
    except Exception:
        return None
    return _build(rows)


tree, how = None, ''
for fn, label in ((from_api, '本地 API（实时）'),
                  (lambda: from_db(False), '只读 SQLite'),
                  (lambda: from_db(True), '快照 SQLite（可能过期）')):
    try:
        tree = fn()
    except Exception:
        tree = None
    if tree:
        how = label
        break

if not tree:
    print('读不到 Zotero 分类树。请确认 Zotero 正在运行，或 zoteroDb 路径正确。')
    raise SystemExit(1)

print('=' * 88)
print('一、Zotero 里的集合（读自 %s，共 %d 个）' % (how, len(tree)))
print('=' * 88)
for p in sorted(tree):
    print('  ' + p)
if '过期' in how:
    print()
    print('  ⚠ 这是快照读取，可能看不到刚做的改动。启动 Zotero 能读到实时结构。')

cfg = json.loads(CFG.read_text(encoding='utf-8-sig'))
used = []
for s in cfg['sources']:
    c = s.get('suggestCollection')
    if c and c not in used:
        used.append(c)
for r in cfg.get('collectionRules', []):
    c = r.get('collection')
    if c and c not in used:
        used.append(c)

print()
print('=' * 88)
print('二、配置里用的集合名（%d 个）' % len(used))
print('=' * 88)
for n in used:
    print('  ' + n)

real = set(tree)
by_leaf = {p.split('/')[-1]: p for p in tree}
by_nonum = {re.sub(r'^\d+', '', p.split('/')[-1]): p for p in tree}

print()
print('=' * 88)
print('三、能否对上？（叶子名去掉前导编号后再比）')
print('=' * 88)
ok, bad = [], []
for n in used:
    leaf = n.split('/')[-1]
    if n in real:
        ok.append((n, n, '精确匹配'))
    elif leaf in by_leaf:
        ok.append((n, by_leaf[leaf], '去掉上级后匹配'))
    elif re.sub(r'^\d+', '', leaf) in by_nonum:
        ok.append((n, by_nonum[re.sub(r'^\d+', '', leaf)], '去掉编号后匹配'))
    else:
        bad.append(n)

for n, match, why in ok:
    flag = '' if why == '精确匹配' else '   ⚠ 名称不完全一致'
    print('  ✓ %-38s -> %s（%s）%s' % (n, match, why, flag))
for n in bad:
    print('  ✗ %-38s 在 Zotero 里【找不到】' % n)

print()
print('  可匹配 %d / %d    找不到 %d' % (len(ok), len(used), len(bad)))
if bad:
    print()
    print('  处理原则：**改配置去迁就你的树**，而不是让树迁就配置。')
    print('  改法：编辑 sources.json 里各源的 suggestCollection 字段。')
