# -*- coding: utf-8 -*-
"""盘点本地 RSSHub 仓库里哪些 namespace 覆盖了用户列出的来源。"""
import os, re, json, io, sys

ROOT = r'D:\RSShub\RSSHub\lib\routes'
ns_files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    for fn in filenames:
        if fn == 'namespace.ts':
            ns_files.append(os.path.join(dirpath, fn))

def field(text, key):
    m = re.search(r"\b%s:\s*'([^']*)'" % key, text)
    if m:
        return m.group(1)
    m = re.search(r'\b%s:\s*"([^"]*)"' % key, text)
    return m.group(1) if m else ''

entries = []
for p in ns_files:
    rel = os.path.relpath(p, ROOT).replace('\\', '/')
    ns = rel[:-len('/namespace.ts')] if rel.endswith('/namespace.ts') else rel[:-len('namespace.ts')].rstrip('/')
    try:
        txt = io.open(p, encoding='utf-8').read()
    except Exception:
        continue
    entries.append({'ns': ns, 'name': field(txt, 'name'), 'url': field(txt, 'url')})

print('namespace 总数 =', len(entries))

# 用户列出的来源 -> 关键词
targets = [
    ('中国政府网 / 国务院', ['gov.cn', '中国政府网', '国务院']),
    ('求是网',            ['qstheory', '求是']),
    ('国家统计局',        ['stats.gov.cn', '国家统计局']),
    ('国家发展改革委',    ['ndrc.gov.cn', '发展改革', '发改委']),
    ('工信部',            ['miit.gov.cn', '工业和信息化']),
    ('农业农村部',        ['moa.gov.cn', '农业农村']),
    ('天津市',            ['tianjin.gov.cn', '天津']),
    ('人民网',            ['people.com.cn', '人民网']),
    ('新华网',            ['xinhuanet', 'news.cn', '新华']),
    ('半月谈',            ['banyuetan', '半月谈']),
    ('地方政府',          ['gov.cn', '政府']),
    ('研究机构',          ['nifd', 'cass', '研究']),
    ('行业协会',          ['协会', '学会', '联合会']),
    ('微信公众号',        ['weixin', 'wechat', '公众号', '微信']),
]

for label, keys in targets:
    hits = []
    for e in entries:
        blob = (e['ns'] + ' ' + e['name'] + ' ' + e['url']).lower()
        if any(k.lower() in blob for k in keys):
            hits.append(e)
    print()
    print('### %s   -> %d 个 namespace' % (label, len(hits)))
    for e in sorted(hits, key=lambda x: x['ns'])[:18]:
        print('   %-34s %-16s %s' % (e['ns'], e['name'][:16], e['url']))
    if len(hits) > 18:
        print('   ... 还有 %d 个' % (len(hits) - 18))

# 顶层 namespace 一览
tops = sorted({e['ns'].split('/')[0] for e in entries})
print()
print('=== 顶层 namespace 共 %d 个 ===' % len(tops))
print(' '.join(tops))
