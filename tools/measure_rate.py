# -*- coding: utf-8 -*-
"""只读测量：各源的产出频率，判断「本周窗口」能否装下。

不改任何配置、不写任何文件。
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

WD = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('wd', WD / 'weekly_digest.py')
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

cfg = json.loads((WD / 'sources.json').read_text(encoding='utf-8-sig'))

proc, started = wd.start_rsshub(cfg)
if not wd.port_open('127.0.0.1', 1200):
    print('RSSHub 不可用'); raise SystemExit(1)

now = datetime.now(timezone.utc)
rows = []
try:
    for src in cfg['sources']:
        if not src.get('enabled'):
            continue
        try:
            raw = wd.fetch_bytes(cfg['baseUrl'] + src['path'], int(cfg.get('timeoutSec', 120)))
            items = wd.parse_feed(raw)
        except Exception as e:
            print('%-22s 抓取失败 %s' % (src['name'], str(e)[:40])); continue
        dates = []
        for it in items:
            d = wd.parse_date(it['date'])
            if d:
                dates.append(d.astimezone(timezone.utc))
        dates.sort(reverse=True)
        n7 = sum(1 for d in dates if (now - d).days < 7)
        n14 = sum(1 for d in dates if (now - d).days < 14)
        if len(dates) >= 2:
            span = (dates[0] - dates[-1]).days or 1
            rate = len(dates) / span * 7
        else:
            span, rate = 0, 0
        rows.append({
            'name': src['name'], 'type': src['type'], 'quota': src['quota'],
            'feed': len(items), 'dated': len(dates),
            'newest': dates[0].strftime('%m-%d') if dates else '-',
            'oldest': dates[-1].strftime('%m-%d') if dates else '-',
            'span': span, 'n7': n7, 'n14': n14, 'rate': rate,
        })
finally:
    if started:
        wd.stop_rsshub(proc)

print()
print('各源产出频率（按当前时间 %s 计算）' % now.strftime('%Y-%m-%d'))
print('=' * 104)
print('%-20s %-5s %5s %6s %5s %5s %5s %8s %10s' % (
    '来源', '配额', 'feed', '有日期', '本周', '两周', '跨度', '约条/周', '本周是否超配额'))
print('-' * 104)
for r in rows:
    over = '✓ 装得下' if r['n7'] <= r['quota'] else '✗ 超 %d 条' % (r['n7'] - r['quota'])
    print('%-20s %-5d %5d %6d %5d %5d %4d天 %8.1f %10s' % (
        r['name'][:18], r['quota'], r['feed'], r['dated'],
        r['n7'], r['n14'], r['span'], r['rate'], over))

print()
tot7 = sum(r['n7'] for r in rows)
totq = sum(r['quota'] for r in rows)
print('汇总：本周（7 天内）各源合计 %d 条，而配额合计 %d 条' % (tot7, totq))
print('      如果只看本周，会丢弃 %d 条（%.0f%%）' % (
    max(0, tot7 - totq), (max(0, tot7 - totq) / tot7 * 100) if tot7 else 0))
