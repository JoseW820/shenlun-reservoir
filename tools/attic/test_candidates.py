# -*- coding: utf-8 -*-
"""批量实测候选源：条目数、日期跨度、本周产出、首条标题。"""
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WD = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('wd', WD / 'weekly_digest.py')
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)
cfg = json.loads((WD / 'sources.json').read_text(encoding='utf-8-sig'))

CANDIDATES = [
    # --- 乡村振兴 / 农业 ---
    ('农业农村部·动态',   '/gov/moa/suburl/xw/zwdt/'),
    ('农业信息网·全国联播', '/agri/zx/xxlb'),
    ('农业信息网·乡村资讯', '/agri/xxh/zgxczx'),
    ('农业信息网·农业要闻', '/agri/zx/nyyw'),
    ('农业信息网·生产动态', '/agri/sc/scdt'),
    # --- 科技创新 / 产业 ---
    ('科技日报电子版',    '/stdaily/digitalpaper'),
    ('求是网·科教',      '/qstheory/science'),
    ('人民网·科技',      '/people/scitech'),
    ('人民网·财经',      '/people/finance'),
    # --- 文化 / 文旅 ---
    ('半月谈·文化',      '/banyuetan/wenhua'),
    ('人民网·文化',      '/people/culture'),
    ('人民网·旅游',      '/people/travel'),
    ('求是网·文化',      '/qstheory/culture'),
    # --- 其他可能有用 ---
    ('人民网·社会',      '/people/society'),
    ('半月谈·评论',      '/banyuetan/banyuetanpinglun'),
]

proc, started = wd.start_rsshub(cfg)
if not wd.port_open('127.0.0.1', 1200):
    print('RSSHub 不可用'); sys.exit(1)

now = datetime.now(timezone.utc)
print()
print('%-20s %-32s %4s %6s %5s %7s %s' % ('名称', '路径', '条目', '有日期', '本周', '跨度天', '首条标题'))
print('-' * 128)
try:
    for name, path in CANDIDATES:
        try:
            raw = wd.fetch_bytes(cfg['baseUrl'] + path, int(cfg.get('timeoutSec', 120)))
            items = wd.parse_feed(raw)
        except Exception as e:
            print('%-20s %-32s  FAIL  %s' % (name, path, str(e)[:45]))
            continue
        dates = [d.astimezone(timezone.utc) for d in
                 (wd.parse_date(it['date']) for it in items) if d]
        dates.sort(reverse=True)
        n7 = sum(1 for d in dates if (now - d).days < 7)
        span = (dates[0] - dates[-1]).days if len(dates) >= 2 else 0
        first = (items[0]['title'] or '')[:40] if items else ''
        print('%-20s %-32s %4d %6d %5d %7d %s'
              % (name, path, len(items), len(dates), n7, span, first))
finally:
    if started:
        wd.stop_rsshub(proc)
