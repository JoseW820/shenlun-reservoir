#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日抓取入库。

抓到的每一条都写进索引（index.sqlite），**永不删除**。
清单脚本（weekly_digest.py）每周从索引里挑 15 条浮上来。

这样「筛选」不再等于「丢失」：没被挑中的仍留在库里，可检索、可回看。
同时因为每天都抓，快照型源（人民日报电子版、求是网理论文选这类
feed 只含 1-2 天的源）不会再丢 6/7 的内容。

用法：
    python fetch_daily.py                   # 正常抓取
    python fetch_daily.py --dry-run         # 只报告，不写索引
    python fetch_daily.py --only banyuetan-jicengzhili,people-paper
    python fetch_daily.py --keep-running    # 跑完不关 RSSHub
    python fetch_daily.py --stats           # 只看索引现状，不抓取
    python fetch_daily.py --check-routes    # 源健康体检（改配置后跑一次）
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gk_core as wd   # noqa: E402  共享核心：抓取/解析/去重/摘要/索引/Zotero


def check_routes(cfg):
    """源健康体检：探测配置里所有路由（含停用源）的可用性，不写索引。

    替代原 test-routes.ps1 —— 复用同一套 feed 抓取/解析逻辑，
    不再用 PowerShell 重复实现。结果同时写 tools/route-test-results.json。
    """
    base = str(cfg['baseUrl']).rstrip('/')
    timeout = int(cfg.get('timeoutSec', 120))
    sources = list(cfg['sources'])

    proc, started = wd.start_rsshub(cfg)
    if not wd.port_open('127.0.0.1', 1200):
        wd.log('RSSHub 不可用，终止', 'err')
        return 1

    def probe(src):
        t0 = time.time()
        ms = lambda: int((time.time() - t0) * 1000)
        try:
            raw = wd.fetch_bytes(base + str(src['path']), timeout)
            items = wd.parse_feed(raw)
            avg = 0
            if items:
                lens = [len(wd.strip_html(it.get('raw') or '')) for it in items[:5]]
                lens = [n for n in lens if n]
                avg = sum(lens) // len(lens) if lens else 0
            return src, ('ok' if items else 'empty'), len(items), avg, ms(), ''
        except urllib.error.HTTPError as exc:
            return src, 'error', 0, 0, ms(), 'HTTP %s' % exc.code
        except Exception as exc:
            return src, 'error', 0, 0, ms(), str(exc)[:60]

    try:
        with ThreadPoolExecutor(max_workers=min(8, len(sources))) as ex:
            results = [f.result() for f in as_completed(
                [ex.submit(probe, s) for s in sources])]
    finally:
        if started:
            wd.stop_rsshub(proc)

    order = {s['id']: i for i, s in enumerate(sources)}
    results.sort(key=lambda r: order[r[0]['id']])

    print()
    print('%-5s %-22s %-26s %-6s %4s %6s %7s  %s'
          % ('类型', '来源', '路径', '状态', '条目', '均正文', '耗时ms', '备注'))
    print('-' * 96)
    ok_n = 0
    report = []
    for src, status, n, avg, ms, err in results:
        if status == 'ok':
            ok_n += 1
        enabled = '' if src.get('enabled') else '[已停用] '
        hint = err or ('路由疑似失效（官网改版）' if status != 'ok' else '')
        print('%-5s %-22s %-26s %-6s %4d %6d %7d  %s%s'
              % (src['type'], src['name'], src['path'], status, n, avg, ms,
                 enabled, hint))
        report.append({'id': src['id'], 'name': src['name'], 'type': src['type'],
                       'path': src['path'], 'enabled': bool(src.get('enabled')),
                       'status': status, 'itemCount': n, 'avgBodyChars': avg,
                       'elapsedMs': ms, 'error': err or None})
    print('-' * 96)
    print('汇总: %d/%d 可用' % (ok_n, len(results)))

    out = HERE / 'tools' / 'route-test-results.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('结果文件: %s' % out)
    return 0 if ok_n else 2


def backup_index(cfg, keep=4):
    """索引是「永不删除」的唯一存储层 —— 所以它自己必须有备份。

    每次成功抓取后复制一份到 backups/（按天命名，同一天多次跑只留一份），
    保留最近 keep 份。
    """
    src = Path(wd.index_path(cfg))
    bdir = HERE / 'backups'
    bdir.mkdir(exist_ok=True)
    dst = bdir / ('index-%s.sqlite' % datetime.now().strftime('%Y%m%d'))
    shutil.copy2(src, dst)
    olds = sorted(bdir.glob('index-*.sqlite'),
                  key=lambda f: f.stat().st_mtime)[:-keep]
    for f in olds:
        try:
            f.unlink()
        except OSError:
            pass
    return dst


def show_index(cfg):
    con = wd.open_index(cfg)
    total, by_status, span = wd.index_report(con)
    print()
    print('索引：%s' % wd.index_path(cfg))
    print('  总计     : %d 条' % total)
    for k, v in sorted(by_status.items()):
        label = {'new': '待展示', 'shown': '已展示', 'in_zotero': '已在Zotero',
                 'junk': '形态噪音', 'dup': '跨源重复',
                 'stale': '超龄积压', 'archived': '停用源存量'}.get(k, k)
        print('  %-9s: %d 条' % (label, v))
    if span and span[0]:
        print('  时间跨度 : %s ~ %s' % (str(span[0])[:10], str(span[1])[:10]))
    rows = con.execute(
        "SELECT source, COUNT(*) FROM items WHERE status='new' "
        "GROUP BY source ORDER BY 2 DESC").fetchall()
    if rows:
        print()
        print('  待展示按来源分布:')
        for name, n in rows:
            print('    %-24s %d' % (name, n))
    con.close()


def main():
    ap = argparse.ArgumentParser(description='每日抓取入库（只写索引，不生成清单）')
    ap.add_argument('--config', default=str(HERE / 'sources.json'))
    ap.add_argument('--dry-run', action='store_true', help='只报告，不写索引')
    ap.add_argument('--keep-running', action='store_true', help='跑完不关 RSSHub')
    ap.add_argument('--only', default='', help='只跑指定 id，逗号分隔')
    ap.add_argument('--stats', action='store_true', help='只看索引现状，不抓取')
    ap.add_argument('--check-routes', action='store_true',
                    help='源健康体检：探测全部路由可用性（含停用源），不写索引')
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    wd.setup_logfile('fetch')

    if args.stats:
        show_index(cfg)
        return 0
    if args.check_routes:
        return check_routes(cfg)

    base = str(cfg['baseUrl']).rstrip('/')
    timeout = int(cfg.get('timeoutSec', 120))
    summary_cfg = cfg.get('summary', {})
    limit = int(summary_cfg.get('chars', 110))
    max_src = int(summary_cfg.get('maxSourceChars', 20000))
    tf = cfg.get('titleFilter', {})
    rules = cfg.get('collectionRules', [])

    only = {x.strip() for x in args.only.split(',') if x.strip()}
    sources = [s for s in cfg['sources']
               if s.get('enabled') and (not only or s['id'] in only)]
    if not sources:
        wd.log('没有启用的源', 'err')
        return 1

    now = datetime.now()
    fetched_at = now.isoformat(timespec='seconds')
    wd.log('每日抓取 ｜ %s ｜ 启用源 %d 个' % (now.strftime('%Y-%m-%d %H:%M'), len(sources)))

    # 判重基准：Zotero + 索引
    zot_urls, zot_titles, zot_ok = wd.load_zotero_keys(
        cfg.get('zoteroDb') or os.path.expanduser(r'~\Zotero\zotero.sqlite'))
    con = wd.open_index(cfg)
    idx_urls, idx_titles = wd.index_keys(con)
    total0, status0, _ = wd.index_report(con)
    wd.log('判重基准：Zotero %d URL/%d 标题　索引 %d 条（%s）　→ 去重集合 %d URL/%d 标题'
           % (len(zot_urls), len(zot_titles), total0,
              ' '.join(f'{k}={v}' for k, v in sorted(status0.items())),
              len(zot_urls | idx_urls), len(zot_titles | idx_titles)))

    known_urls = zot_urls | idx_urls
    known_titles = zot_titles | idx_titles

    proc, started = wd.start_rsshub(cfg)
    if not wd.port_open('127.0.0.1', 1200):
        wd.log('RSSHub 不可用，终止', 'err')
        con.close()
        return 1

    stats = {'seen': 0, 'blocked': 0, 'dup_zotero': 0, 'dup_zotero_title': 0,
             'dup_index': 0, 'dup_index_title': 0, 'dup_internal': 0,
             'dup_internal_title': 0, 'added': 0}
    new_rows = []
    per_source = []
    seen_urls, seen_titles = set(), set()

    try:
        # 抓取是网络 IO，串行要 ~80 秒；并行后瓶颈只剩最慢的那个源。
        # 去重/写库仍在主线程串行做，判定逻辑与串行版完全一致。
        def _fetch_one(src):
            try:
                raw = wd.fetch_bytes(base + str(src['path']), timeout)
                return src['id'], wd.parse_feed(raw), None
            except urllib.error.HTTPError as exc:
                return src['id'], None, 'HTTP %s' % exc.code
            except Exception as exc:
                return src['id'], None, str(exc)[:60]

        fetched_map = {}
        with ThreadPoolExecutor(max_workers=min(8, len(sources))) as ex:
            futs = [ex.submit(_fetch_one, s) for s in sources]
            for fut in as_completed(futs):
                sid, items, err = fut.result()
                fetched_map[sid] = (items, err)

        for src in sources:
            label = src['name']
            items, err = fetched_map.get(src['id'], (None, '未执行'))
            if err is not None:
                note = ('路由疑似失效（解析到 0 条，RSSHub 返回 503）'
                        if err == 'HTTP 503' else '')
                wd.log('%s: %s %s' % (label, err, note), 'err')
                per_source.append((label, 0, 0, err))
                continue

            stats['seen'] += len(items)
            fresh = []
            for it in items:
                title = (it['title'] or '').strip()
                if not title or title.lower() in wd.GENERIC_TITLES:
                    continue
                blocked, _ = wd.title_blocked(title, tf)
                if blocked:
                    stats['blocked'] += 1
                    continue
                nurl = wd.norm_url(it['link'])
                if not nurl:
                    continue
                ntitle = wd.norm_title(title)
                use_title = bool(ntitle) and len(ntitle) >= wd.MIN_TITLE_FP

                if nurl in zot_urls:
                    stats['dup_zotero'] += 1
                    continue
                if use_title and ntitle in zot_titles:
                    stats['dup_zotero_title'] += 1
                    continue
                if nurl in idx_urls:
                    stats['dup_index'] += 1
                    continue
                if use_title and ntitle in idx_titles:
                    stats['dup_index_title'] += 1
                    continue
                if nurl in seen_urls:
                    stats['dup_internal'] += 1
                    continue
                if use_title and ntitle in seen_titles:
                    stats['dup_internal_title'] += 1
                    continue
                seen_urls.add(nurl)
                if use_title:
                    seen_titles.add(ntitle)

                fresh.append({
                    'source_id': src['id'], 'source': label, 'type': src['type'],
                    'title': title, 'url': it['link'], 'nurl': nurl, 'ntitle': ntitle,
                    'date': wd.parse_date(it['date']),
                    'summary': wd.make_summary(it['raw'], limit, max_src),
                    'collection': wd.pick_collection(title, src, rules),
                })

            new_rows.extend(fresh)
            per_source.append((label, len(items), len(fresh), ''))
            wd.log('%-22s 抓到 %3d 条 -> 新增 %2d 条' % (label, len(items), len(fresh)), 'ok')
    finally:
        if started and not args.keep_running:
            wd.stop_rsshub(proc)

    if args.dry_run:
        wd.log('--dry-run：不写索引（本次会新增 %d 条）' % len(new_rows))
    else:
        stats['added'] = wd.index_insert(con, new_rows, fetched_at)
        wd.log('已写入索引 %d 条' % stats['added'], 'ok')

    total1, status1, span1 = wd.index_report(con)
    con.close()

    if not args.dry_run:
        try:
            dst = backup_index(cfg)
            wd.log('索引已备份 -> %s' % dst, 'ok')
        except Exception as exc:
            wd.log('索引备份失败：%s' % exc, 'warn')

    print()
    print('源抓取明细')
    print('-' * 64)
    for label, got, fresh, err in per_source:
        flag = '  [%s]' % err if err else ''
        print('  %-22s 抓到 %3d  新增 %2d%s' % (label, got, fresh, flag))
    print('-' * 64)
    print('  抓到合计 %d ｜ 通稿剔除 %d ｜ 索引已有 %d ｜ Zotero 已有 %d ｜ 本次内部重复 %d'
          % (stats['seen'], stats['blocked'],
             stats['dup_index'] + stats['dup_index_title'],
             stats['dup_zotero'] + stats['dup_zotero_title'],
             stats['dup_internal'] + stats['dup_internal_title']))
    print('  索引现共 %d 条（%s）'
          % (total1, ' '.join('%s=%s' % (k, v) for k, v in sorted(status1.items()))))
    if not zot_ok:
        print('  ⚠ 本次没读到 Zotero —— 已存过的条目可能被重复入库')

    # 所有源都失败 = 几乎可以肯定是没联网（或 RSSHub 没起来）。
    # 返回非 0，让计划任务的「上次运行结果」能反映出问题，而不是静默成功。
    ok_count = sum(1 for _, got, _, _ in per_source if got > 0)
    if ok_count == 0:
        print()
        print('  ✗ 所有源都抓取失败，索引没有新增。最可能的原因：')
        print('      1. 电脑没联网')
        print('         （RSSHub 跑在本机，但它要去上游网站取内容，所以必须联网）')
        print('      2. RSSHub 没起来')
        print('         手动验证：cd D:\\rsshub-engine; $env:CI="true"; corepack pnpm dev')
        print('      3. 抓取时段正好全站在维护（很少见）')
        return 2
    wd.log('本次 %d/%d 个源成功' % (ok_count, len(per_source)),
           'ok' if ok_count == len(per_source) else 'warn')
    return 0


if __name__ == '__main__':
    sys.exit(main())
