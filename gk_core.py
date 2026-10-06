#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公考素材工作流 · 共享核心库。

抓取（fetch_daily.py）与出清单（weekly_digest.py）共用的全部逻辑：
  日志 / feed 抓取与解析 / 摘要提取 / URL 与标题指纹 / 通稿过滤 /
  RSSHub 生命周期 / Zotero 三级读取 / SQLite 索引层 / 模糊判重。

两个 CLI 只做自己的流程编排，不重复实现这里的任何函数。
"""

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATOM_NS = '{http://www.w3.org/2005/Atom}'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) weekly-digest/1.0'


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

_LOG_FILE = None


def setup_logfile(name, keep_days=14):
    """stdout 之外同时写 logs/<name>-YYYYMMDD.log。

    计划任务是隐藏运行的，失败时只能看到退出码 —— 文件日志是唯一的现场。
    保留最近 keep_days 天。
    """
    global _LOG_FILE
    d = HERE / 'logs'
    d.mkdir(exist_ok=True)
    cutoff = time.time() - keep_days * 86400
    for f in d.glob('%s-*.log' % name):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass
    path = d / ('%s-%s.log' % (name, datetime.now().strftime('%Y%m%d')))
    _LOG_FILE = open(path, 'a', encoding='utf-8')
    return path


def log(msg, level='info'):
    stamp = datetime.now().strftime('%H:%M:%S')
    prefix = {'info': '  ', 'ok': '✓ ', 'warn': '! ', 'err': '✗ '}.get(level, '  ')
    line = f'[{stamp}] {prefix}{msg}'
    print(line, flush=True)
    if _LOG_FILE:
        try:
            _LOG_FILE.write(line + '\n')
            _LOG_FILE.flush()
        except Exception:
            pass


def fetch_bytes(url, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_html(raw):
    """HTML -> 纯文本。"""
    if not raw:
        return ''
    s = raw
    s = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', s)
    s = re.sub(r'(?i)<br\s*/?>', '\n', s)
    s = re.sub(r'(?i)</(p|div|li|tr|h[1-6]|td)>', '\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = (s.replace('&nbsp;', ' ').replace('&ldquo;', '“').replace('&rdquo;', '”')
          .replace('&mdash;', '—').replace('&hellip;', '…').replace('&amp;', '&')
          .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
          .replace('&#39;', "'").replace('&middot;', '·'))
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else '', s)
    s = re.sub(r'[ \t　]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n', s)
    return s.strip()


# 摘要里要剥掉的页面噪音（行首）
NOISE_PATTERNS = [
    r'^\s*(来源|文章来源|稿源)[:：]\s*\S+\s*',
    r'^\s*(责任编辑|责编|编辑|作者)[:：]\s*\S+\s*',
    r'^\s*(扫一扫在手机打开当前页|分享到|打印本页|关闭窗口|返回顶部|【字体[:：][^】]*】)\s*',
    r'^\s*(发布时间|发布日期|时间)[:：]\s*[\d年月日\-/: ]+\s*',
    r'^\s*(原标题)[:：]\s*',
    r'^\s*[·•\-—]{2,}\s*',
    # 通讯社电头：新华社北京9月30日电 / 题：
    r'^\s*(新华社|人民日报|光明日报|经济日报|中新社)[一-龥]{0,8}\d{1,2}月\d{1,2}日电\s*(题[:：])?\s*',
    r'^\s*本报讯\s*',
]

# 整行就是署名的行（半月谈等把署名单独放在一个 <p> 里）。
# 只剔除「整行皆为署名」的行，避免贪婪吃掉正文。
SIGNATURE_LINE = re.compile(
    r'^\s*(?:来源|稿源|文|记者|作者|责任编辑|责编|编辑)?\s*[:：/]?\s*'
    r'(?:新华社|人民日报|半月谈|光明日报|经济日报|中国青年报|中新社|央视新闻|澎湃新闻)?\s*'
    r'(?:记者|通讯员|作者)\s*'
    r'[一-龥·]{2,3}(?:[ 　]+[一-龥·]{2,3})*'
    r'\s*(?:[（(][^）)]{0,20}[)）])?\s*$'
)

# 行内署名（新华社电头那种：新华社记者余贤红在……）。
# 姓名限 2-3 字且后面不接空格续名，否则会吃掉正文首词。
INLINE_SIGNATURE_PATTERNS = [
    # 行内电头：新华网银川8月29日电（记者杨植森）
    r'(?:新华网|新华社|人民网|中国新闻网|央视网|光明网|中国经济网)[一-龥]{0,8}'
    r'\d{1,2}月\d{1,2}日电\s*(?:[（(]\s*记者[^）)]{0,20}[)）])?',
    # 括号署名：（记者张三）、（通讯员李四、王五）
    r'[（(]\s*(?:记者|通讯员)\s*[一-龥·]{2,3}'
    r'(?:\s*[、,，]\s*[一-龥·]{2,3})*\s*[)）]',
    r'(?:新华社|人民日报|半月谈|光明日报|经济日报|中国青年报|中新社|央视新闻)\s*记者\s*'
    r'[一-龥·]{2,3}(?:\s+[一-龥·]{2,3}){0,2}',
    r'[（(]\s*作者[:：]?\s*[一-龥·]{2,6}\s*[)）]',
    r'作者[:：]\s*[一-龥·]{2,6}',
]



def drop_signature_lines(text):
    """剔除整行皆为署名的行。"""
    kept = [ln for ln in text.split('\n') if not (ln.strip() and SIGNATURE_LINE.match(ln.strip()))]
    return '\n'.join(kept)



def collapse_adjacent_repeats(text, min_len=10, max_len=120):
    """把紧邻重复的片段折叠掉（A A B -> A B）。"""
    changed = True
    while changed:
        changed = False
        for k in range(max_len, min_len - 1, -1):
            m = re.search(r'(.{%d})\1' % k, text, re.S)
            if m:
                text = text[:m.start()] + m.group(1) + text[m.end():]
                changed = True
                break
    return text


def drop_prefix_repeat(text, min_len=8, max_len=70):
    """去掉「开头若干字又在后面原样重复」的尾巴（A B A' -> A B）。"""
    n = len(text)
    for k in range(min(max_len, n // 2), min_len - 1, -1):
        head = text[:k]
        idx = text.find(head, k)
        if idx != -1:
            return text[:idx] + text[idx + k:]
    return text



def make_summary(description_html, limit, max_source_chars):
    """从正文 HTML 提取一句话摘要。"""
    text = strip_html(description_html)
    if not text:
        return ''
    text = text[:max_source_chars]
    # 1) 去掉行首页面噪音（可能连续出现多段）
    for _ in range(6):
        before = text
        for pat in NOISE_PATTERNS:
            text = re.sub(pat, '', text, count=1, flags=re.I)
        text = text.lstrip()
        if text == before:
            break
    # 2) 先按行剔除独占一段的署名，再处理行内署名
    text = drop_signature_lines(text)
    for pat in INLINE_SIGNATURE_PATTERNS:
        text = re.sub(pat, '', text)
    # 3) 压平换行，再折叠重复（导语与正文首句常常一字不差）
    flat = re.sub(r'\s*\n\s*', '', text)
    flat = flat[:limit * 4]
    flat = collapse_adjacent_repeats(flat)
    flat = drop_prefix_repeat(flat)
    flat = collapse_adjacent_repeats(flat)
    flat = re.sub(r'([。！？；，、：])\1+', r'\1', flat)
    flat = re.sub(r'。\s*。+', '。', flat)
    # 源站自带的截断符（如「休闲..度假」「五个全..社会」）：仅当夹在汉字之间才去掉
    flat = re.sub(r'(?<=[一-龥])\.{2,}(?=[一-龥])', '', flat)
    flat = re.sub(r'(?<=[一-龥])…+(?=[一-龥])', '', flat)
    flat = re.sub(r'\.{2,}', '', flat)

    if len(flat) <= limit:
        return flat
    head = flat[:limit]
    # 尽量在句末标点处断句
    cut = max(head.rfind(c) for c in '。！？；')
    if cut >= limit * 0.5:
        return head[:cut + 1]
    return head.rstrip('，、,') + '…'



# --------------------------------------------------------------------------
# RSSHub 生命周期
# --------------------------------------------------------------------------

def port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_rsshub(cfg):
    """返回 (Popen 或 None, 是否由本脚本启动)。"""
    if port_open('127.0.0.1', 1200):
        log('RSSHub 已在运行，直接复用', 'ok')
        return None, False

    rsshub_dir = Path(cfg['rsshubDir'])
    if not rsshub_dir.is_dir():
        log(f'RSSHub 目录不存在: {rsshub_dir}', 'err')
        return None, False

    built = (rsshub_dir / 'dist' / 'index.mjs').exists()
    script = 'start' if built else 'dev'
    log(f'启动 RSSHub（corepack pnpm {script}，{"生产模式" if built else "开发模式"}）…')

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    # corepack 首次下载 pnpm 会有交互式确认，隐藏运行/计划任务场景必须禁问
    env = dict(os.environ)
    env['COREPACK_ENABLE_DOWNLOAD_PROMPT'] = '0'
    env['CI'] = '1'
    # 启动输出写日志而不是 DEVNULL —— 否则启动失败时没有任何现场可查
    (HERE / 'logs').mkdir(exist_ok=True)
    boot_log = open(HERE / 'logs' / 'rsshub-boot.log', 'a',
                    encoding='utf-8', errors='replace')
    boot_log.write('\n===== %s 启动（%s 模式）=====\n'
                   % (datetime.now().isoformat(timespec='seconds'),
                      '生产' if built else '开发'))
    boot_log.flush()
    proc = subprocess.Popen(
        f'corepack pnpm {script}',
        cwd=str(rsshub_dir),
        shell=True,
        stdout=boot_log,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=creationflags,
    )
    for i in range(60):
        if port_open('127.0.0.1', 1200):
            log(f'RSSHub 就绪（等待 {i * 2}s）', 'ok')
            return proc, True
        if proc.poll() is not None:
            log('RSSHub 进程已退出，启动失败', 'err')
            return None, False
        time.sleep(2)
    log('RSSHub 启动超时（120s），启动输出见 logs\\rsshub-boot.log', 'err')
    stop_rsshub(proc)
    return None, False


def stop_rsshub(proc):
    if proc is None:
        return
    log('关闭 RSSHub…')
    try:
        subprocess.run(f'taskkill /F /T /PID {proc.pid}', shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# --------------------------------------------------------------------------
# feed 解析
# --------------------------------------------------------------------------

def _text(el, *names):
    for n in names:
        child = el.find(n)
        if child is not None and child.text:
            return child.text.strip()
    return ''


def parse_feed(xml_bytes):
    """解析 RSS 2.0 / Atom，返回条目列表。"""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        log(f'XML 解析失败: {exc}', 'warn')
        return items

    tag = root.tag
    if tag.endswith('rss') or root.find('channel') is not None:
        channel = root.find('channel')
        if channel is None:
            return items
        for it in channel.findall('item'):
            link = _text(it, 'link')
            if not link:
                guid = it.find('guid')
                if guid is not None and guid.text and guid.text.startswith('http'):
                    link = guid.text.strip()
            items.append({
                'title': _text(it, 'title'),
                'link': link,
                'date': _text(it, 'pubDate'),
                'raw': _text(it, 'description') or _text(it, '{http://purl.org/rss/1.0/modules/content/}encoded'),
            })
    else:
        # Atom
        entries = root.findall(f'{ATOM_NS}entry') or root.findall('entry')
        for it in entries:
            link = ''
            for ln in (it.findall(f'{ATOM_NS}link') + it.findall('link')):
                if ln.get('rel') in (None, 'alternate') and ln.get('href'):
                    link = ln.get('href')
                    break
            items.append({
                'title': _text(it, f'{ATOM_NS}title', 'title'),
                'link': link,
                'date': _text(it, f'{ATOM_NS}updated', 'updated', f'{ATOM_NS}published', 'published'),
                'raw': _text(it, f'{ATOM_NS}content', 'content', f'{ATOM_NS}summary', 'summary'),
            })
    return items


def parse_date(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


# --------------------------------------------------------------------------
# 过滤 / 去重 / 分类
# --------------------------------------------------------------------------

def title_blocked(title, tf):
    """返回 (是否剔除, 原因)。"""
    for kw in tf.get('hardBlock', []):
        if kw in title:
            return True, f'通稿:{kw}'
    for kw in tf.get('softBlock', []):
        if kw in title:
            if any(sig in title for sig in tf.get('policySignals', [])):
                return False, ''
            return True, f'通稿:{kw}'
    return False, ''


TRACKING = re.compile(r'(?i)^(utm_|spm|from|share|ref|_|wx)')
GENERIC_TITLES = {'', '无标题', 'untitled'}


def norm_url(u):
    """URL 指纹：统一 http/https、去掉 www.、去锚点与跟踪参数、去尾部斜杠。"""
    if not u:
        return ''
    u = u.strip()
    u = re.sub(r'#.*$', '', u)
    m = re.match(r'(?i)^(https?)://([^/]+)(/.*)?$', u)
    if not m:
        return u.lower()
    host = m.group(2).lower()
    if host.startswith('www.'):
        host = host[4:]
    path = m.group(3) or '/'
    if '?' in path:
        base, qs = path.split('?', 1)
        kept = [p for p in qs.split('&') if p and not TRACKING.match(p.split('=')[0])]
        path = base + ('?' + '&'.join(kept) if kept else '')
    path = re.sub(r'/+$', '', path) or '/'
    # scheme 统一成 https：同一页面在 http/https 下视为同一条
    return f'https://{host}{path}'


# 标题指纹：剥掉来源后缀、栏目后缀、装饰性括号，再去掉所有标点空白
_TITLE_SUFFIX = re.compile(
    r'\s*[-–—_|｜]\s*(求是网|中国政府网|国家统计局|人民网|新华网|半月谈|央视网|光明网|'
    r'中国经济网|中国新闻网|人民日报|新华每日电讯)\s*$'
)
_TITLE_COLUMN = re.compile(
    r'[_|｜]\s*(政策解读|政策文件|要闻|时政|观点|评论|国际|经济|社会|文化|科技|'
    r'教育|生态|党建|国防|原创|头条|理论|调研|地方|滚动)\s*$'
)
_TITLE_DECOR = re.compile(
    r'[（(【\[](组图|图集|视频|双语|图解|H5|海报|微视频|现场|实录|全文|名单|专题)[)）】\]]'
)

# 形态标记：官媒常把同一份文件做成多种形态。这些词只表示呈现方式，不代表内容不同。
# 只剥开头/结尾，避免误伤标题中间的词义。
_TITLE_FORM_HEAD = re.compile(r'^(?:一图读懂|一图速览|图说|图解|解读|速览|划重点|要点|收藏)\s*[:：]?\s*')
_TITLE_FORM_TAIL = re.compile(r'\s*(?:一图读懂|一图速览|图说|图解|解读|全文|速览|划重点|要点|收藏)$')


def norm_title(t):
    """标题指纹，用于识别「同一篇文章、不同 URL / 不同措辞」的重复。"""
    if not t:
        return ''
    s = t
    for _ in range(3):
        before = s
        s = _TITLE_SUFFIX.sub('', s).strip()
        s = _TITLE_COLUMN.sub('', s).strip()
        s = _TITLE_FORM_HEAD.sub('', s).strip()
        s = _TITLE_FORM_TAIL.sub('', s).strip()
        if s == before:
            break
    s = _TITLE_DECOR.sub('', s)
    s = re.sub(r'[^\w一-鿿]', '', s)
    return s.lower()


def title_digits(t):
    """标题里的数字串（按出现顺序）。用于拦住「同模板不同月份/日期」这类假重复。"""
    return tuple(re.findall(r'\d+(?:\.\d+)?', t or ''))


def digits_compatible(d1, d2):
    """两边都有数字且不同 → 判定为不同文章。

    实测依据：索引里相似度 ≥0.6 的 67 组中，数字不同的 8 组全部是
    「8月发布会 vs 7月发布会」「8月28日油价 vs 8月14日油价」这类不同事件。
    """
    if not d1 or not d2:
        return True      # 一方没有数字，不构成否决理由
    return d1 == d2


def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def title_similarity(a, b):
    """字符二元组 Dice 系数。中文标题上比编辑距离更稳。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


# 判定为「同一篇」的相似度阈值。实测校准：
#   0.889 习近平出席…欢迎宴会 / …在白宫举行的欢迎仪式  → 该合
#   0.824 一图读懂《X》 / 《X》解读                    → 该合（已被形态词归一化提前接住）
#   0.786 如何发挥企业在基础研究中的作用 / 发挥企业在基础研究中的重要作用 → 该合
#   0.733 《轻工纺织…规划》一图读懂 / 《医药工业…规划》一图读懂 → 不该合（低于阈值）
FUZZY_THRESHOLD = 0.78


ZOTERO_API = 'http://127.0.0.1:23119/api/users/0/items/top'


def _zotero_from_api(timeout=8):
    """Zotero 本地 HTTP API（Zotero 运行时最可靠，需已开启本地 API）。"""
    urls, titles = set(), set()
    start, total = 0, None
    while True:
        req = urllib.request.Request(
            f'{ZOTERO_API}?limit=100&start={start}',
            headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if total is None:
                total = int(resp.headers.get('Total-Results') or 0)
            batch = json.loads(resp.read().decode('utf-8'))
        if not batch:
            break
        for it in batch:
            d = it.get('data') or {}
            if d.get('url'):
                nu = norm_url(d['url'])
                if nu:
                    urls.add(nu)
            nt = norm_title(d.get('title') or '')
            if nt:
                titles.add(nt)
        start += len(batch)
        if (total and start >= total) or len(batch) < 100:
            break
    return urls, titles


def _zotero_from_db(db_path):
    """直接读 zotero.sqlite。三级尝试：

      1. mode=ro                —— Zotero 关闭时可用，读到最新
      2. 复制 .sqlite + -wal + -shm 到临时目录后按普通方式打开
                                —— Zotero 运行时 mode=ro 会被锁，这是**正确**的退路：
                                   连 WAL 一起复制，所以能看到最近的改动
      3. mode=ro&immutable=1    —— 最后的保底，但它**忽略 WAL**，会读到旧数据

    为什么不能只用 3：Zotero 的 WAL 可能很大（实测主库 5.5 MB、WAL 16.4 MB），
    忽略 WAL 会漏掉大量最近存的条目，导致去重失效、已存过的素材再次出现。
    """
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(db_path)

    def read(con):
        cur = con.cursor()
        urls, titles = set(), set()
        for (val,) in cur.execute('''select v.value from itemData d
                join itemDataValues v on v.valueID = d.valueID
                join fields f on f.fieldID = d.fieldID
                where f.fieldName = 'url' '''):
            if val:
                nu = norm_url(val)
                if nu:
                    urls.add(nu)
        for (val,) in cur.execute('''select v.value from itemData d
                join itemDataValues v on v.valueID = d.valueID
                join fields f on f.fieldID = d.fieldID
                where f.fieldName = 'title' '''):
            nt = norm_title(val or '')
            if nt:
                titles.add(nt)
        return urls, titles

    # --- 1. 直接只读打开 ---
    try:
        con = sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True, timeout=8)
        urls, titles = read(con)
        con.close()
        return urls, titles, '只读'
    except Exception as exc:
        first = exc

    # --- 2. 连 WAL 一起复制后读（Zotero 运行时的正确退路）---
    tmpdir = None
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix='zotero-ro-'))
        dst = tmpdir / p.name
        shutil.copy2(p, dst)
        for suffix in ('-wal', '-shm'):
            side = Path(str(p) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(dst) + suffix))
        con = sqlite3.connect(f'file:{dst.as_posix()}?mode=ro', uri=True, timeout=8)
        urls, titles = read(con)
        con.close()
        return urls, titles, '复制含WAL'
    except Exception:
        pass
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # --- 3. 保底：快照（忽略 WAL，可能偏旧）---
    try:
        con = sqlite3.connect(f'file:{p.as_posix()}?mode=ro&immutable=1', uri=True, timeout=8)
        urls, titles = read(con)
        con.close()
        return urls, titles, '快照(可能偏旧)'
    except Exception:
        raise first


def load_zotero_keys(db_path):
    """返回 (urls, titles, ok)。三级降级：本地 API → 数据库只读 → 数据库快照。
    ok=False 表示完全读不到，此时无法按 Zotero 去重。"""
    try:
        urls, titles = _zotero_from_api()
        if urls or titles:
            log(f'Zotero 本地 API 读取成功：{len(urls)} 个 URL / {len(titles)} 个标题', 'ok')
            return urls, titles, True
    except Exception as exc:
        log(f'Zotero 本地 API 不可用（{str(exc)[:44]}）', 'warn')
    try:
        urls, titles, how = _zotero_from_db(db_path)
        log(f'Zotero {how}读取成功：{len(urls)} 个 URL / {len(titles)} 个标题', 'ok')
        return urls, titles, True
    except Exception as exc:
        log(f'⚠ 读不到 Zotero（{str(exc)[:44]}）', 'err')
        log('⚠ 本次不做 Zotero 去重 —— 你已存过的条目可能会再次出现！', 'err')
        return set(), set(), False


def pick_collection(title, src, rules):
    for rule in rules:
        for kw in rule.get('keywords', []):
            if kw in title:
                return rule['collection']
    return src.get('suggestCollection') or '00收件箱'


def type_sequence(cfg):
    """清单里的类型顺序与分节，全部由配置的 typeCaps 决定，不写死在代码里。
    新增/删除类型只需改 sources.json。"""
    caps = cfg.get('typeCaps') or {}
    ordered = [k for k in caps if not str(k).startswith('_')]
    if not ordered:
        ordered = [str(s.get('type')) for s in cfg.get('sources', [])
                   if s.get('enabled') and s.get('type')]
        seen, tmp = set(), []
        for t in ordered:
            if t not in seen:
                seen.add(t)
                tmp.append(t)
        ordered = tmp
    return ordered


# 标题指纹最短长度：太短的标题（如「宏观数据」「通知」）容易误判，
# 只做 URL 去重，不做标题去重，避免把不同文章错当成重复而漏掉。
MIN_TITLE_FP = 8


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


# --------------------------------------------------------------------------
# 索引层（SQLite）
#
# 设计要点：抓到的每一条都入库，永不删除。清单只是从库里「挑 15 条浮上来」，
# 没被挑中的仍然在库，可检索、可回看。这样「筛选」不再等于「丢失」。
# --------------------------------------------------------------------------

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nurl       TEXT UNIQUE NOT NULL,   -- URL 指纹，唯一键
    ntitle     TEXT,                   -- 标题指纹
    title      TEXT NOT NULL,          -- 原始标题
    url        TEXT NOT NULL,          -- 原始链接
    source_id  TEXT,
    source     TEXT,
    type       TEXT,                   -- 案例型 / 论述型
    published  TEXT,                   -- ISO 时间
    fetched    TEXT NOT NULL,          -- 首次抓到时间
    summary    TEXT,
    collection TEXT,                   -- 建议归入的 Zotero 集合
    status     TEXT NOT NULL DEFAULT 'new',   -- new / shown / in_zotero / junk / dup / stale / archived
    shown_at   TEXT,
    list_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_status    ON items(status);
CREATE INDEX IF NOT EXISTS idx_ntitle    ON items(ntitle);
CREATE INDEX IF NOT EXISTS idx_published ON items(published);
CREATE INDEX IF NOT EXISTS idx_source    ON items(source_id);
"""


def index_path(cfg):
    p = cfg.get('indexPath')
    return Path(p) if p else (HERE / 'index.sqlite')


def open_index(cfg):
    path = index_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=20)
    con.executescript(INDEX_SCHEMA)
    con.commit()
    return con


def index_keys(con):
    """已入库的 (nurl 集合, ntitle 集合)，用于抓取判重。"""
    urls = {r[0] for r in con.execute('SELECT nurl FROM items')}
    titles = {r[0] for r in con.execute(
        "SELECT ntitle FROM items WHERE ntitle IS NOT NULL AND ntitle <> ''")}
    titles.discard('')
    return urls, titles


def index_insert(con, rows, fetched_at):
    """插入新条目（nurl 冲突则跳过），返回新增条数。"""
    cur = con.cursor()
    added = 0
    for r in rows:
        cur.execute(
            """INSERT OR IGNORE INTO items
               (nurl, ntitle, title, url, source_id, source, type, published,
                fetched, summary, collection, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'new')""",
            (r['nurl'], r.get('ntitle') or '', r['title'], r['url'],
             r.get('source_id'), r.get('source'), r.get('type'),
             r['date'].isoformat() if r.get('date') else None,
             fetched_at, r.get('summary') or '', r.get('collection') or ''))
        added += cur.rowcount
    con.commit()
    return added


def _row_to_dict(row):
    (iid, nurl, ntitle, title, url, sid, source, typ, pub, fetched,
     summary, coll) = row
    d = None
    if pub:
        try:
            d = datetime.fromisoformat(pub)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
        except Exception:
            d = None
    return {'id': iid, 'nurl': nurl, 'ntitle': ntitle, 'title': title, 'url': url,
            'source_id': sid, 'source': source, 'type': typ, 'date': d,
            'fetched': fetched, 'summary': summary, 'collection': coll}


INDEX_COLS = ('id, nurl, ntitle, title, url, source_id, source, type, '
              'published, fetched, summary, collection')


def index_candidates(con, status='new'):
    """取出待展示的候选条目。"""
    cur = con.execute(
        f'SELECT {INDEX_COLS} FROM items WHERE status = ? ORDER BY published DESC',
        (status,))
    return [_row_to_dict(r) for r in cur.fetchall()]


def index_report(con):
    """索引概览：(总数, 各状态计数, 最早/最新发布时间)。"""
    total = con.execute('SELECT COUNT(*) FROM items').fetchone()[0]
    by_status = dict(con.execute(
        'SELECT status, COUNT(*) FROM items GROUP BY status').fetchall())
    span = con.execute(
        'SELECT MIN(published), MAX(published) FROM items').fetchone()
    return total, by_status, span


def index_mark(con, ids, status, list_id=None, when=None):
    if not ids:
        return 0
    cur = con.cursor()
    cur.executemany(
        'UPDATE items SET status=?, shown_at=?, list_id=? WHERE id=?',
        [(status, when, list_id, i) for i in ids])
    con.commit()
    return cur.rowcount


def index_age_out(con, stale_after_days, enabled_ids, now, by_type=None):
    """积压治理（只改状态、不删数据，把 status 改回 'new' 即可恢复）：

      1. 超龄未展示的 -> 'stale'
         挑选按日期倒序、每源只取最新 quota 条，只要源还在更新，
         老条目数学上永远浮不上来 —— 不如明确标出来，别冒充「待展示」。
         阈值按类型分：stale_after_days 是默认天数，by_type 可按类型覆盖
         （案例素材不过时给 90 天，政策类有时效给 28 天）。
      2. 停用源的存量 -> 'archived'
         源停用后这些条目被永久冻结：不展示、不清理。

    返回 {'stale': [id...], 'archived': [id...]}，由调用方决定是否落库（--dry-run 不落）。
    """
    out = {'stale': [], 'archived': []}
    by_type = by_type or {}
    cutoffs = {}
    for typ, days in by_type.items():
        if days > 0:
            cutoffs[typ] = (now - timedelta(days=days)).isoformat(timespec='seconds')
    default_cutoff = ((now - timedelta(days=stale_after_days)).isoformat(timespec='seconds')
                      if stale_after_days > 0 else None)
    if default_cutoff or cutoffs:
        for rid, typ, pub in con.execute(
                "SELECT id, type, COALESCE(published, fetched) FROM items "
                "WHERE status='new'"):
            cutoff = cutoffs.get(typ, default_cutoff)
            if cutoff and pub and pub < cutoff:
                out['stale'].append(rid)
    if enabled_ids:
        marks = ','.join('?' * len(enabled_ids))
        out['archived'] = [r[0] for r in con.execute(
            "SELECT id FROM items WHERE status='new' "
            "AND (source_id IS NULL OR source_id NOT IN (%s))" % marks,
            tuple(enabled_ids))]
    return out


# --------------------------------------------------------------------------
# 模糊判重（跨源改写版标题）
# --------------------------------------------------------------------------

def _grams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def fuzzy_add(known, fp, digits, row):
    """把一条标题加进阻塞索引。known = {'grams': {bigram: [pos]}, 'items': [...]}"""
    pos = len(known['items'])
    known['items'].append((fp, digits, row))
    for g in _grams(fp):
        known['grams'].setdefault(g, []).append(pos)


def fuzzy_lookup(known, fp, digits, skip_nurl=None):
    """在已知标题里找「相似度够高且数字兼容」的一条。返回那条 row，找不到返回 None。

    两步过滤，避免全表两两比较：
      1) bigram 阻塞：只比共享至少一个二元组的标题
      2) 长度差过滤：长度相差过大不可能达到阈值
    """
    cand = set()
    for g in _grams(fp):
        cand.update(known['grams'].get(g, ()))
    for pos in cand:
        kfp, kdigits, row = known['items'][pos]
        if skip_nurl and row.get('nurl') == skip_nurl:
            continue                      # 别跟自己比
        if abs(len(kfp) - len(fp)) > max(4, int(len(fp) * 0.45)):
            continue
        if not digits_compatible(digits, kdigits):
            continue
        if title_similarity(fp, kfp) >= FUZZY_THRESHOLD:
            return row
    return None


def index_all_titles(con, exclude_status='new'):
    """把索引里有标题指纹的条目装进阻塞索引，用于模糊判重。

    默认**排除 status='new'**：那些正是本次要判的候选，若一开始就放进来，
    两条互为改写版的候选会互相判重、双双被删。正确做法是只放「已展示过的」，
    再按排名顺序边判边把留下的候选加进去 —— 这样每组只留排名最前的一条。
    """
    sql = ("SELECT nurl, title, ntitle, source, url, status FROM items "
           "WHERE ntitle IS NOT NULL AND ntitle <> ''")
    args = ()
    if exclude_status:
        sql += ' AND status <> ?'
        args = (exclude_status,)
    known = {'grams': {}, 'items': []}
    for nurl, title, ntitle, source, url, status in con.execute(sql, args):
        if len(ntitle) < MIN_TITLE_FP:
            continue
        fuzzy_add(known, ntitle, title_digits(title),
                  {'nurl': nurl, 'title': title, 'source': source,
                   'url': url, 'status': status})
    return known
