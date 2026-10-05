#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周公考素材清单生成器（薄 CLI，共享逻辑全在 gk_core.py）。

只读索引、不抓取：从 index.sqlite 取 status='new' 的候选 ->
积压治理 -> 确定性剔除 -> Zotero/模糊判重 -> 配额 + 回填 ->
生成 HTML/MD/JSON -> 标记已展示。

用法：
    python weekly_digest.py                 # 正常跑
    python weekly_digest.py --dry-run       # 只统计筛选结果，不写文件、不改索引
    python weekly_digest.py --date 2026-10-11
    python weekly_digest.py --config other.json
"""

import argparse
import json
import re
import sys

from gk_core import *   # noqa: F401,F403  （日志/索引层/判重/摘要/类型顺序等全部共享逻辑）
from gk_core import HERE, MIN_TITLE_FP


# --------------------------------------------------------------------------
# 确定性剔除 / 降序
#
# 只处理「形态层面」的明确噪音，不做主题或质量判断 —— 因此不存在误判好素材的风险。
# 剔除的条目标记为 status='junk'（不是删除），随时可以改回来。
# --------------------------------------------------------------------------

JUNK_PATTERNS = [
    # 报刊版面责任署名。人民日报电子版整版抓取时会带出这些行。
    (r'^(?:\d+版|本版|第\d+版)?\s*责编\s*[：:]', '版面署名'),
    (r'[一二三四五六七八九十\d]+版责编\s*[：:]', '版面署名'),
    # 整条标题就是无正文的形态
    (r'^(?:图片报道|图片新闻|组图|图集|视频|图解|海报|H5|微视频|直播|图片|专题片|短片|动漫)$',
     '无正文形态'),
    # 礼节性节日祝贺/问候（通稿黑名单里漏掉的表述）
    (r'致以.{0,12}(?:祝贺|问候|节日)', '礼节问候'),
    # 版面目录
    (r'^(?:目录|本期目录|要目|总目录|导读)$', '目录'),
    # 纯活动预告。窄化到「活动/仪式/大会」类词，避免误伤
    # 「《XX法》将于明年施行」这种有政策含义的表述。
    (r'(?:活动|仪式|典礼|大会|论坛|展会|赛事|晚会).{0,12}'
     r'(?:将于|即将|拟于).{0,16}(?:启幕|启动|举行|举办|开幕|上线|召开)\s*$', '活动预告'),
]
JUNK_RE = [(re.compile(p), why) for p, why in JUNK_PATTERNS]

# 无正文形态开头标记：不剔除，只降序 —— 保证「文字版」优先赢得去重，
# 否则一图读懂《X》与《X》解读被判重复时，可能留下没有正文的那一条。
GRAPHIC_RE = re.compile(r'^(?:一图读懂|一图速览|图说|图解|视频|组图|图集|海报|H5|微视频)')


def junk_reason(title):
    """命中的话返回原因，否则返回空串。"""
    for rx, why in JUNK_RE:
        if rx.search(title or ''):
            return why
    return ''


def graphic_rank(title):
    """0 = 有正文的普通条目，1 = 图解/视频类。排序时 0 在前。"""
    return 1 if GRAPHIC_RE.search(title or '') else 0


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='每周公考素材清单生成器')
    ap.add_argument('--config', default=str(HERE / 'sources.json'))
    ap.add_argument('--dry-run', action='store_true', help='不写文件、不改索引')
    ap.add_argument('--date', default='', help='覆盖清单日期，格式 YYYY-MM-DD')
    args = ap.parse_args()

    # 用 utf-8-sig 读取：记事本等编辑器保存的 JSON 可能带 BOM
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    setup_logfile('weekly')
    target = int(cfg.get('listTarget', 30))
    rules = cfg.get('collectionRules', [])
    out_dir = Path(cfg['outputDir'])

    sources = [s for s in cfg['sources'] if s.get('enabled')]
    if not sources:
        log('没有启用的源', 'err')
        return 1

    now = datetime.now()
    if args.date:
        now = datetime.strptime(args.date, '%Y-%m-%d')
    iso_year, iso_week, _ = now.isocalendar()
    week_tag = f'{iso_year}-W{iso_week:02d}'

    log(f'清单周期 {week_tag} ｜ 启用源 {len(sources)} 个 ｜ 目标 {target} 条')

    # ---- 从索引取候选 ----
    # 抓取由 fetch_daily.py 每天做；这里只负责「从库里挑 15 条浮上来」。
    # 没被挑中的仍留在库里，可检索、可回看 —— 所以筛选不再等于丢失。
    zotero_urls, zotero_titles, zotero_ok = load_zotero_keys(
        cfg.get('zoteroDb') or os.path.expanduser(r'~\Zotero\zotero.sqlite'))
    con = open_index(cfg)
    total, by_status, span = index_report(con)
    log('索引共 %d 条：%s' % (total, ' '.join(f'{k}={v}' for k, v in sorted(by_status.items()))))
    if span and span[0]:
        log('　发布时间跨度 %s ~ %s' % (str(span[0])[:10], str(span[1])[:10]))

    # 索引新鲜度：抓取连续失败时清单照样出（用的是旧内容），必须醒目提示，
    # 否则坏一周你都毫无感知。
    index_stale_warn = None
    last_fetched = con.execute('SELECT MAX(fetched) FROM items').fetchone()[0]
    if last_fetched:
        try:
            age_h = (now - datetime.fromisoformat(str(last_fetched))).total_seconds() / 3600
            if age_h > 48:
                index_stale_warn = (
                    '索引最新抓取是 %.0f 小时前（%s）—— 每日抓取任务可能已连续失败，'
                    '本清单用的是旧内容。请先手动跑一次 fetch_daily.py。'
                    % (age_h, str(last_fetched)[:16]))
                log(index_stale_warn, 'warn')
        except ValueError:
            pass

    cands = index_candidates(con, 'new')
    log('待展示候选 %d 条（已展示过的不会再出现）' % len(cands))

    # ---- 积压治理：超龄标 stale，停用源存量标 archived（只改状态，可改回）----
    backlog_cfg = cfg.get('backlog') or {}
    stale_days = int(backlog_cfg.get('staleAfterDays', 28))
    enabled_ids = [s['id'] for s in cfg['sources'] if s.get('enabled')]
    aged = index_age_out(con, stale_days, enabled_ids, now)
    for kind in ('stale', 'archived'):
        ids = aged[kind]
        if not ids:
            continue
        if not args.dry_run:
            index_mark(con, ids, kind, when=now.isoformat(timespec='seconds'))
        drop = set(ids)
        cands = [r for r in cands if r['id'] not in drop]
        why = ('超过 %d 天未展示' % stale_days) if kind == 'stale' else '来源已停用'
        log('积压治理：%d 条标记 %s（%s）' % (len(ids), kind, why), 'warn')

    # ---- 确定性剔除：形态层面的明确噪音 ----
    # 只标 status='junk'，不删数据；随时可以改回 'new'。
    junk = [(r['id'], junk_reason(r['title'])) for r in cands if junk_reason(r['title'])]
    if junk:
        if not args.dry_run:
            index_mark(con, [i for i, _ in junk], 'junk',
                       when=now.isoformat(timespec='seconds'))
        js = {i for i, _ in junk}
        cands = [r for r in cands if r['id'] not in js]
        kinds = {}
        for _, why in junk:
            kinds[why] = kinds.get(why, 0) + 1
        log('确定性剔除 %d 条（%s）'
            % (len(junk), '、'.join('%s×%d' % (k, v) for k, v in kinds.items())), 'warn')

    # 展示前再对一次 Zotero：抓取之后你可能又存了一些
    hit = [r['id'] for r in cands if (
        r['nurl'] in zotero_urls
        or (r['ntitle'] and len(r['ntitle']) >= MIN_TITLE_FP
            and r['ntitle'] in zotero_titles))]
    if hit:
        if not args.dry_run:
            index_mark(con, hit, 'in_zotero', when=now.isoformat(timespec='seconds'))
        hs = set(hit)
        cands = [r for r in cands if r['id'] not in hs]
        log('其中 %d 条已在 Zotero，剔除（标记 in_zotero）' % len(hit), 'warn')

    # 跨源重复处理：官媒常把同一篇稿子改个标题、换个链接再发一遍。
    # 归一化后精确相等的在抓取时已挡住；这里处理「相似但不完全相同」的。
    # 判定 = 相似度 ≥ FUZZY_THRESHOLD 且 数字串兼容。
    type_seq = type_sequence(cfg)
    order_idx = {t: i for i, t in enumerate(type_seq)}
    # 第三键 graphic_rank：同一批里让「有正文的版本」排在前，
    # 这样它先被保留，图解版被判重 —— 否则可能留下没有正文的那一条。
    cands.sort(key=lambda r: (order_idx.get(r['type'], len(type_seq)),
                              graphic_rank(r['title']),
                              -(r['date'].timestamp() if r['date'] else 0)))
    known = index_all_titles(con)          # 含已展示的，防止旧条目的改写版再冒出来
    dup_ids = []
    fresh = []
    fuzzy_hits = []
    for r in cands:
        fp = r.get('ntitle') or ''
        dg = title_digits(r['title'])
        match = None
        if len(fp) >= MIN_TITLE_FP:
            match = fuzzy_lookup(known, fp, dg, skip_nurl=r.get('nurl'))
        if match:
            dup_ids.append(r['id'])
            fuzzy_hits.append((r, match))
            continue
        fresh.append(r)
        if len(fp) >= MIN_TITLE_FP:
            fuzzy_add(known, fp, dg, r)
    if dup_ids:
        if not args.dry_run:
            index_mark(con, dup_ids, 'dup', when=now.isoformat(timespec='seconds'))
        log('判定为跨源重复 %d 条（标记 dup，不再展示）' % len(dup_ids), 'warn')
        for r, m in fuzzy_hits[:6]:
            log('   · %s' % r['title'][:44])
            log('     与【%s】%s 重复' % (m['source'], m['title'][:44]))
    cands = fresh

    # 按源分组，套用各源配额
    src_by_id = {s['id']: s for s in cfg['sources']}
    by_src = {}
    for r in cands:
        by_src.setdefault(r['source_id'], []).append(r)

    stats = {'candidates': len(cands) + len(dup_ids) + len(junk) + len(hit),
             'zotero_hit': len(hit), 'junk': len(junk),
             'dup_fuzzy': len(dup_ids), 'kept': 0, 'zotero_ok': zotero_ok,
             'stale': len(aged['stale']), 'archived': len(aged['archived']),
             'index_stale_warn': index_stale_warn}
    picked = []
    per_source = []
    for sid, rows in by_src.items():
        s = src_by_id.get(sid)
        if not s or not s.get('enabled'):
            continue
        # 有正文的版本优先于图解/视频类
        rows.sort(key=lambda r: (graphic_rank(r['title']),
                                 -(r['date'].timestamp() if r['date'] else 0)))
        q = int(s.get('quota', 0))
        kept = rows[:q]
        picked.extend(kept)
        per_source.append((s['name'], len(rows), len(kept), ''))
        log('%-22s 索引待展示 %3d 条 -> 取 %d 条' % (s['name'], len(rows), len(kept)), 'ok')

    # 裁剪：先按「类型优先 + 时间倒序」排序，再套用各类型上限与总量上限
    type_seq = type_sequence(cfg)
    order_idx = {t: i for i, t in enumerate(type_seq)}
    picked.sort(key=lambda r: (order_idx.get(r['type'], len(type_seq)),
                               -(r['date'].timestamp() if r['date'] else 0)))
    type_caps = {k: v for k, v in (cfg.get('typeCaps') or {}).items()
                 if not str(k).startswith('_')}
    final, counts = [], {}
    for r in picked:
        cap = type_caps.get(r['type'])
        if cap is not None and counts.get(r['type'], 0) >= cap:
            continue
        counts[r['type']] = counts.get(r['type'], 0) + 1
        final.append(r)
        if len(final) >= target:
            break
    trimmed = len(picked) - len(final)
    picked = final

    # 回填：某源本周没有新内容时，它的配额名额不该浪费 —— 从各源配额之外的
    # 剩余候选里按「类型优先 + 时间倒序」补满，只受类型上限约束（那是配比安全网）。
    backfilled = 0
    if len(picked) < target:
        chosen_ids = {r['id'] for r in picked}
        pool = []
        for sid, rows in by_src.items():
            s = src_by_id.get(sid)
            if not s or not s.get('enabled'):
                continue
            pool.extend(r for r in rows if r['id'] not in chosen_ids)
        pool.sort(key=lambda r: (order_idx.get(r['type'], len(type_seq)),
                                 graphic_rank(r['title']),
                                 -(r['date'].timestamp() if r['date'] else 0)))
        for r in pool:
            if len(picked) >= target:
                break
            cap = type_caps.get(r['type'])
            if cap is not None and counts.get(r['type'], 0) >= cap:
                continue
            counts[r['type']] = counts.get(r['type'], 0) + 1
            picked.append(r)
            backfilled += 1
        if backfilled:
            log('配额之外回填 %d 条：有源本周无新内容，已从剩余候选补满' % backfilled, 'ok')
    stats['backfilled'] = backfilled

    # 「建议归入」按**当前配置**重算，而不是用入库时写死的值。
    # 否则你改了 sources.json 里的集合名之后，老条目会一直显示旧名字 ——
    # 实测索引里会同时存在三代命名，同一份清单里出现三种风格的「建议归入」。
    regrouped = 0
    for r in picked:
        s = src_by_id.get(r['source_id'])
        if s:
            want = pick_collection(r['title'], s, rules)
            if want != r.get('collection'):
                r['collection'] = want
                regrouped += 1
    if regrouped:
        log('按当前配置重算「建议归入」：%d 条与入库时不同' % regrouped, 'warn')

    stats['kept'] = len(picked)
    stats['per_source'] = per_source
    stats['trimmed'] = trimmed
    log('合计入清单 %d 条（被类型上限/总量裁掉 %d 条，它们仍在索引里）'
        % (len(picked), trimmed))

    if args.dry_run:
        log('--dry-run：不写文件、不改索引')
        for r in picked:
            log(f"  [{r['type']}] {r['title'][:52]}  <- {r['source']}")
            log(f"        摘要: {r['summary'] or '(空！)'}")
        print_summary(per_source, stats)
        con.close()
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    # 输出格式由配置控制（默认 html + md + json）
    formats = [str(f).lower() for f in (cfg.get('outputFormats') or ['html', 'md', 'json'])]
    base = f'{week_tag}_素材清单'

    # 不覆盖已有清单：同一周重复运行会生成 (2)、(3) …，
    # 因为索引层已去重，重复运行得到的是「补充清单」而不是同一份。
    def paths_for(n):
        suffix = '' if n == 1 else f'({n})'
        return {f: out_dir / f'{base}{suffix}.{f}' for f in formats}

    seq = 1
    chosen = paths_for(seq)
    while any(p.exists() for p in chosen.values()):
        seq += 1
        chosen = paths_for(seq)

    # HTML 是主要阅读界面，优先保证
    if 'html' in chosen:
        chosen['html'].write_text(render_html(week_tag, now, picked, stats, cfg), encoding='utf-8')
    if 'md' in chosen:
        chosen['md'].write_text(
            render_markdown(week_tag, now, picked, per_source, stats, cfg), encoding='utf-8')
    if 'json' in chosen:
        chosen['json'].write_text(json.dumps({
            'week': week_tag, 'generated': now.isoformat(timespec='seconds'),
            'stats': stats, 'items': [
                {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
                for r in picked
            ],
        }, ensure_ascii=False, indent=2), encoding='utf-8')

    # 在索引里把这次展示的条目标记为 shown —— 这就是跨周去重的依据
    list_id = chosen.get('html') or chosen.get('md')
    index_mark(con, [r['id'] for r in picked], 'shown',
               list_id=list_id.name if list_id else week_tag,
               when=now.isoformat(timespec='seconds'))
    total2, by_status2, _ = index_report(con)
    con.close()

    log(f'清单已生成: {chosen.get("html") or chosen.get("md")}', 'ok')
    for fmt, p in chosen.items():
        log(f'  · {fmt.upper():<4} {p.name}  ({p.stat().st_size / 1024:.1f} KB)')
    log('索引已更新：共 %d 条（%s）' % (
        total2, ' '.join(f'{k}={v}' for k, v in sorted(by_status2.items()))), 'ok')
    print_summary(per_source, stats)
    return 0


def _stats_extra(stats):
    """统计行里的可选段：积压治理与配额回填，没发生就不显示。"""
    parts = []
    if stats.get('stale') or stats.get('archived'):
        parts.append('积压治理 %d' % (stats.get('stale', 0) + stats.get('archived', 0)))
    if stats.get('backfilled'):
        parts.append('配额回填 %d' % stats['backfilled'])
    return (' ｜ ' + ' ｜ '.join(parts)) if parts else ''


def print_summary(per_source, stats):
    print()
    print('源选取明细（候选来自索引）')
    print('-' * 66)
    for label, avail, kept, err in per_source:
        flag = f'  [{err}]' if err else ''
        print(f'  {label:<20} 索引待展示 {avail:>4}  取 {kept:>2}{flag}')
    print('-' * 66)
    print('  索引候选 %d 条 ｜ 确定性剔除 %d 条 ｜ 已在 Zotero %d 条 ｜ 跨源重复 %d 条 ｜ 入清单 %d 条%s'
          % (stats.get('candidates', 0), stats.get('junk', 0), stats.get('zotero_hit', 0),
             stats.get('dup_fuzzy', 0), stats.get('kept', 0), _stats_extra(stats)))
    if stats.get('trimmed'):
        print('  被类型上限/总量裁掉 %d 条 —— 它们仍在索引里，不会丢失'
              % stats['trimmed'])


def render_markdown(week_tag, generated, items, per_source, stats, cfg):
    read_limit = cfg.get('weeklyReadLimit', 20)
    type_seq = type_sequence(cfg)
    breakdown = ' · '.join(f'{t} {sum(1 for r in items if r["type"] == t)}' for t in type_seq)

    out = []
    out.append(f'# {week_tag} 素材清单')
    out.append('')
    out.append(f'生成时间 {generated.strftime("%Y-%m-%d %H:%M")} ｜ 共 **{len(items)}** 条 '
               f'｜ {breakdown} ｜ 每周阅读上限 {read_limit} 篇')
    out.append('')
    if not stats.get('zotero_ok', True):
        out.append('> ⚠ **本次没能读取 Zotero**，因此没有按「你已存过的条目」去重，'
                   '清单里可能出现重复。请打开 Zotero 后重新运行一次。')
        out.append('')
    if stats.get('index_stale_warn'):
        out.append('> ⚠ **%s**' % stats['index_stale_warn'])
        out.append('')
    out.append('> 挑中的条目点链接 → Zotero 浏览器插件保存 → 存入「建议归入」所指的集合。')
    out.append('> 不需要的条目直接忽略即可；下周不会再出现同一条。')
    out.append('')

    for tname in type_sequence(cfg):
        group = [r for r in items if r['type'] == tname]
        if not group:
            continue
        out.append(f'## {tname}（{len(group)}）')
        out.append('')
        by_source = {}
        for r in group:
            by_source.setdefault(r['source'], []).append(r)
        for src_name, rows in by_source.items():
            out.append(f'### {src_name}')
            out.append('')
            for r in rows:
                date = r['date'].strftime('%Y-%m-%d') if r['date'] else '日期未知'
                # 标题本身做成链接：Markdown 预览里可点
                out.append(f'- [ ] **[{r["title"]}]({r["url"]})**')
                out.append(f'      `{date}` ｜ 建议归入 `{r["collection"]}`')
                if r['summary']:
                    out.append(f'      {r["summary"]}')
                else:
                    out.append('      （无文字正文，多为图解/图片页，需点开查看）')
                # 单独一行放裸链接（不加尖括号）：VS Code 等编辑器可 Ctrl+点击
                out.append(f'      {r["url"]}')
                out.append('')
        out.append('')

    out.append('---')
    out.append('')
    out.append('## 本次统计')
    out.append('')
    out.append('| 源 | 索引待展示 | 本次取 | 备注 |')
    out.append('|---|---:|---:|---|')
    for label, avail, kept, err in per_source:
        out.append(f'| {label} | {avail} | {kept} | {err} |')
    out.append('')
    out.append(f"索引候选 {stats.get('candidates', 0)} ｜ "
               f"确定性剔除 {stats.get('junk', 0)} ｜ "
               f"已在 Zotero {stats.get('zotero_hit', 0)} ｜ "
               f"跨源重复剔除 {stats.get('dup_fuzzy', 0)} ｜ "
               f"入清单 {stats.get('kept', 0)} ｜ "
               f"被类型上限裁掉 {stats.get('trimmed', 0)}（仍在索引里）"
               f"{_stats_extra(stats)}")
    out.append('')
    return '\n'.join(out)


def render_html(week_tag, generated, items, stats, cfg):
    """生成可直接双击打开、链接可点的 HTML 清单。"""
    read_limit = cfg.get('weeklyReadLimit', 20)
    type_seq = type_sequence(cfg)
    counts = {t: sum(1 for r in items if r['type'] == t) for t in type_seq}
    pill_cls = {'案例型': 'case', '论述型': 'disc', '数据型': 'data'}
    pills_html = '\n  '.join(
        f'<span class="pill {pill_cls.get(t, "")}">{esc(t)} {counts[t]}</span>'
        for t in type_seq if counts[t])
    if not pills_html:
        pills_html = '<span class="pill">无条目</span>'
    # Zotero 读不到时，去重会失效，必须在清单顶部显著提示
    warn_html = ''
    if not stats.get('zotero_ok', True):
        warn_html = ('<div class="hint" style="background:#fdecea;border-left-color:#c0392b;'
                     'color:#7f1d1d"><b>注意：本次没能读取 Zotero</b>，'
                     '因此没有按「你已存过的条目」去重，清单里可能出现重复。'
                     '请打开 Zotero 后重新运行一次。</div>')
    if stats.get('index_stale_warn'):
        warn_html += ('<div class="hint" style="background:#fff7e6;border-left-color:#d48806;'
                      'color:#7c4a03"><b>注意：</b>%s</div>' % esc(stats['index_stale_warn']))

    parts = []
    parts.append(f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(week_tag)} 素材清单</title>
<style>
  :root {{
    --bg:#f7f7f5; --card:#fff; --line:#e3e3df; --ink:#1f2328; --dim:#6b7280;
    --accent:#c0392b; --case:#0f766e; --disc:#7c3aed; --data:#0369a1;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:32px 20px 80px; background:var(--bg); color:var(--ink);
    font:16px/1.75 -apple-system,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
  }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:.5px; }}
  .sub {{ color:var(--dim); font-size:14px; margin-bottom:4px; }}
  .hint {{ background:#fff8e6; border-left:4px solid #e0a800; padding:10px 14px;
           border-radius:0 6px 6px 0; font-size:14px; color:#6b5b00; margin:18px 0 26px; }}
  .bar {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center;
          margin:14px 0 26px; font-size:13px; }}
  .pill {{ padding:3px 10px; border-radius:999px; background:#ececea; color:#444; }}
  .pill.case {{ background:#e6f4f1; color:var(--case); }}
  .pill.disc {{ background:#f1ebfd; color:var(--disc); }}
  .pill.data {{ background:#e6f1f9; color:var(--data); }}
  .pill.done {{ background:#e8f5e9; color:#2e7d32; }}
  h2 {{ font-size:19px; margin:34px 0 4px; padding-bottom:8px; border-bottom:2px solid var(--line); }}
  h2 .n {{ color:var(--dim); font-weight:400; font-size:15px; }}
  h3 {{ font-size:14px; color:var(--dim); font-weight:600; margin:22px 0 10px;
        letter-spacing:.4px; }}
  .item {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:14px 16px; margin-bottom:10px; transition:.15s; }}
  .item:hover {{ border-color:#c9c9c4; box-shadow:0 2px 10px rgba(0,0,0,.05); }}
  .item.seen {{ opacity:.5; }}
  .item.seen .t::after {{ content:" ✓ 已点开"; font-size:12px; color:#2e7d32; margin-left:8px;
                          font-weight:400; }}
  .t {{ font-size:16px; font-weight:600; color:var(--ink); text-decoration:none;
        display:block; margin-bottom:6px; }}
  .t:hover {{ color:var(--accent); text-decoration:underline; }}
  .t:visited {{ color:#8250df; }}
  .row {{ font-size:13px; color:var(--dim); margin-bottom:6px; }}
  .coll {{ background:#f0f0ee; padding:2px 8px; border-radius:4px; font-family:Consolas,monospace;
           font-size:12px; color:#333; }}
  .sum {{ font-size:14px; color:#3c4043; }}
  .none {{ font-size:14px; color:#b06a00; font-style:italic; }}
  .url {{ font-size:12px; color:#9aa0a6; word-break:break-all; margin-top:6px; }}
  .stats {{ margin-top:44px; font-size:13px; color:var(--dim); }}
  .stats table {{ border-collapse:collapse; width:100%; margin-top:10px; }}
  .stats th,.stats td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; }}
  .stats th {{ background:#f0f0ee; font-weight:600; }}
  .stats td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
</style>
</head>
<body>
<div class="wrap">
<h1>{esc(week_tag)} 素材清单</h1>
<div class="sub">生成时间 {generated.strftime('%Y-%m-%d %H:%M')} ｜ 共 {len(items)} 条 ｜ 每周阅读上限 {read_limit} 篇</div>
<div class="bar">
  {pills_html}
  <span class="pill done" id="doneCount">已点开 0 条</span>
</div>
<div class="hint">
  <b>怎么用：</b>点标题 → 打开官网原文 → 用 Zotero 浏览器插件保存 → 存入下面标出的「建议归入」集合。<br>
  不需要的条目直接忽略；下周不会重复出现同一条。<b>点过的条目会自动变淡</b>（记录在本机浏览器里，换浏览器会重置）。
</div>
{warn_html}
''')

    for tname in type_seq:
        group = [r for r in items if r['type'] == tname]
        if not group:
            continue
        parts.append(f'<h2>{esc(tname)} <span class="n">（{len(group)}）</span></h2>')
        by_source = {}
        for r in group:
            by_source.setdefault(r['source'], []).append(r)
        for src_name, rows in by_source.items():
            parts.append(f'<h3>{esc(src_name)}</h3>')
            for r in rows:
                date = r['date'].strftime('%Y-%m-%d') if r['date'] else '日期未知'
                if r['summary']:
                    body = f'<div class="sum">{esc(r["summary"])}</div>'
                else:
                    body = '<div class="none">（无文字正文，多为图解/图片页，需点开查看）</div>'
                parts.append(f'''<div class="item" data-key="{esc(r['url'])}">
  <a class="t" href="{esc(r['url'])}" target="_blank" rel="noopener">{esc(r['title'])}</a>
  <div class="row">{esc(date)} ｜ 建议归入 <span class="coll">{esc(r['collection'])}</span></div>
  {body}
  <div class="url">{esc(r['url'])}</div>
</div>''')

    rows_html = '\n'.join(
        f'<tr><td>{esc(lbl)}</td><td class="n">{got}</td><td class="n">{kept}</td>'
        f'<td>{esc(err) if err else ""}</td></tr>'
        for lbl, got, kept, err in stats.get('per_source', [])
    )
    parts.append(f'''<div class="stats">
  <b>本次统计</b>
  <table>
    <tr><th>源</th><th>索引待展示</th><th>本次取</th><th>备注</th></tr>
    {rows_html}
  </table>
  <p>索引候选 {stats.get('candidates', 0)}
     ｜ 确定性剔除 {stats.get('junk', 0)}
     ｜ 已在 Zotero {stats.get('zotero_hit', 0)}
     ｜ 跨源重复剔除 {stats.get('dup_fuzzy', 0)}
     ｜ 入清单 {stats.get('kept', 0)}
     ｜ 被类型上限裁掉 {stats.get('trimmed', 0)}（<b>仍在索引里，不会丢失</b>）{_stats_extra(stats)}</p>
</div>
</div>
<script>
(function () {{
  var KEY = 'gk-seen-items';
  var seen;
  try {{ seen = JSON.parse(localStorage.getItem(KEY) || '[]'); }} catch (e) {{ seen = []; }}
  var set = new Set(seen);
  var items = document.querySelectorAll('.item');
  function refresh() {{
    var n = document.querySelectorAll('.item.seen').length;
    document.getElementById('doneCount').textContent = '已点开 ' + n + ' 条';
  }}
  items.forEach(function (el) {{
    if (set.has(el.dataset.key)) el.classList.add('seen');
    el.querySelector('.t').addEventListener('click', function () {{
      set.add(el.dataset.key);
      el.classList.add('seen');
      try {{ localStorage.setItem(KEY, JSON.stringify(Array.from(set))); }} catch (e) {{}}
      refresh();
    }});
  }});
  refresh();
}})();
</script>
</body>
</html>''')

    return '\n'.join(parts)


if __name__ == '__main__':
    sys.exit(main())
