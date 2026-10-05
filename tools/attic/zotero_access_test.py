# -*- coding: utf-8 -*-
"""测试 Zotero 运行中，各种读取方式是否可用。"""
import shutil
import sqlite3
import tempfile
import time
import urllib.request
from pathlib import Path

DB = Path(str(Path.home() / 'Zotero' / 'zotero.sqlite'))
print('数据库:', DB, '大小 %.1f MB' % (DB.stat().st_size / 1024 / 1024))
print('同目录文件:', [p.name for p in DB.parent.iterdir() if p.name.startswith('zotero.sqlite')])
print()

Q = "select count(*) from items"


def try_read(label, uri, **kw):
    t0 = time.time()
    try:
        con = sqlite3.connect(uri, uri=True, **kw)
        n = con.execute(Q).fetchone()[0]
        con.close()
        print('  ✓ %-34s items=%d  (%.2fs)' % (label, n, time.time() - t0))
        return True
    except Exception as e:
        print('  ✗ %-34s %s  (%.2fs)' % (label, str(e)[:52], time.time() - t0))
        return False


print('1) 直接只读打开')
for to in (5, 20):
    try_read('mode=ro, timeout=%ds' % to, f'file:{DB.as_posix()}?mode=ro', timeout=to)

print()
print('2) immutable 模式（绕过锁）')
try_read('mode=ro&immutable=1', f'file:{DB.as_posix()}?mode=ro&immutable=1', timeout=5)

print()
print('3) 复制一份再读')
try:
    tmp = Path(tempfile.gettempdir()) / 'zotero_copy_test.sqlite'
    shutil.copy2(DB, tmp)
    try_read('复制后读副本', f'file:{tmp.as_posix()}?mode=ro', timeout=5)
    tmp.unlink(missing_ok=True)
except Exception as e:
    print('  ✗ 复制失败:', str(e)[:60])

print()
print('4) Zotero 本地 HTTP API')
for path in ('/api/users/0/items?limit=1', '/connector/ping', '/api/users/0/collections?limit=1'):
    url = 'http://127.0.0.1:23119' + path
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read(200)
        print('  ✓ %-34s HTTP %d  %s' % (path, r.status, body[:60]))
    except Exception as e:
        print('  ✗ %-34s %s' % (path, str(e)[:52]))

print()
print('5) 端口 23119 是否在监听')
import socket
for port in (23119,):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(('127.0.0.1', port)); print('  ✓ 端口 %d 可连接' % port)
    except Exception as e:
        print('  ✗ 端口 %d %s' % (port, e))
    finally:
        s.close()
