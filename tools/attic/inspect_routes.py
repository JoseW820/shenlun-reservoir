# -*- coding: utf-8 -*-
"""看几个通用/候选路由的参数与用法。"""
import io
import os
import re

ROOT = r'D:\rsshub-engine\lib\routes'
TARGETS = [
    'people/index.ts',
    'stdaily/digitalpaper.tsx',
    'agri/index.ts',
    'gov/moa/moa.ts',
    'lifeweek/index.ts',
]

for rel in TARGETS:
    p = os.path.join(ROOT, rel.replace('/', os.sep))
    if not os.path.exists(p):
        print('!!! 不存在', rel); continue
    t = io.open(p, encoding='utf-8').read()
    print('=' * 100)
    print('##', rel)
    print('=' * 100)
    for k in ['path', 'example', 'name', 'url']:
        m = re.search(r"\b%s:\s*'([^']*)'" % k, t)
        if m:
            print('  %-8s %s' % (k, m.group(1)))
    m = re.search(r'parameters:\s*\{(.*?)\n\s*\},', t, re.S)
    if m:
        print('  parameters:')
        for line in m.group(1).split('\n'):
            if line.strip():
                print('     ', line.strip()[:110])
    m = re.search(r'description:\s*`(.*?)`', t, re.S)
    if m:
        print('  description（表格部分）:')
        for line in m.group(1).split('\n'):
            if line.strip().startswith('|'):
                print('     ', line.strip()[:150])
    # 关键代码：它怎么拼 URL / 选择器
    print('  关键代码:')
    for line in t.split('\n'):
        s = line.strip()
        if re.match(r'(const\s+(url|rootUrl|baseUrl|domain)|.*originDomain)', s) or \
           'load(' in s and '$(' in s:
            print('     ', s[:110])
    print()
