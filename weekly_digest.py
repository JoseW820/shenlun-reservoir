#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每周公考素材清单生成器

流程：启动 RSSHub（按需） -> 抓取各源 feed -> 通稿过滤 -> 去重 -> 提取摘要
      -> 按配额与上限裁剪 -> 生成 markdown 清单 -> 标记已展示 -> 关闭 RSSHub

用法：
    python weekly_digest.py                 # 正常跑
    python weekly_digest.py --dry-run       # 只统计筛选结果，不写文件、不改索引
    python weekly_digest.py --keep-running  # 跑完不关闭 RSSHub
    python weekly_digest.py --only banyuetan-jicengzhili,people-paper
    python weekly_digest.py --config other.json
"""

import argparse
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATOM_NS = '{http://www.w3.org/2005/Atom}'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) weekly-digest/1.0'


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def log(msg, level='info'):
    stamp = datetime.now().strftime('%H:%M:%S')
    prefix = {'info': '  ', 'ok': '✓ ', 'warn': '! ', 'err': '✗ '}.get(level, '  ')
    print(f'[{stamp}] {prefix}{msg}', flush=True)


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
    s = re.sub(r'[ \t\u3000]+', ' ', s)
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
    r'^\s*(新华社|人民日报|光明日报|经济日报|中新社)[\u4e00-\u9fa5]{0,8}\d{1,2}月\d{1,2}日电\s*(题[:：])?\s*',
    r'^\s*本报讯\s*',
]

# 整行就是署名的行（半月谈等把署名单独放在一个 <p> 里）。
# 只剔除「整行皆为署名」的行，避免贪婪吃掉正文。
SIGNATURE_LINE = re.compile(
    r'^\s*(?:来源|稿源|文|记者|作者|责任编辑|责编|编辑)?\s*[:：/]?\s*'
    r'(?:新华社|人民日报|半月谈|光明日报|经济日报|中国青年报|中新社|央视新闻|澎湃新闻)?\s*'
    r'(?:记者|通讯员|作者)\s*'
    r'[\u4e00-\u9fa5·]{2,3}(?:[ \u3000]+[\u4e00-\u9fa5·]{2,3})*'
    r'\s*(?:[（(][^）)]{0,20}[)）])?\s*$'
)

# 行内署名（新华社电头那种：新华社记者余贤红在……）。
# 姓名限 2-3 字且后面不接空格续名，否则会吃掉正文首词。
INLINE_SIGNATURE_PATTERNS = [
    # 行内电头：新华网银川8月29日电（记者杨植森）
    r'(?:新华网|新华社|人民网|中国新闻网|央视网|光明网|中国经济网)[\u4e00-\u9fa5]{0,8}'
    r'\d{1,2}月\d{1,2}日电\s*(?:[（(]\s*记者[^）)]{0,20}[)）])?',
    # 括号署名：（记者张三）、（通讯员李四、王五）
    r'[（(]\s*(?:记者|通讯员)\s*[\u4e00-\u9fa5·]{2,3}'
    r'(?:\s*[、,，]\s*[\u4e00-\u9fa5·]{2,3})*\s*[)）]',
    r'(?:新华社|人民日报|半月谈|光明日报|经济日报|中国青年报|中新社|央视新闻)\s*记者\s*'
    r'[\u4e00-\u9fa5·]{2,3}(?:\s+[\u4e00-\u9fa5·]{2,3}){0,2}',
    r'[（(]\s*作者[:：]?\s*[\u4e00-\u9fa5·]{2,6}\s*[)）]',
    r'作者[:：]\s*[\u4e00-\u9fa5·]{2,6}',
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
    flat = re.sub(r'(?<=[\u4e00-\u9fa5])\.{2,}(?=[\u4e00-\u9fa5])', '', flat)
    flat = re.sub(r'(?<=[\u4e00-\u9fa5])…+(?=[\u4e00-\u9fa5])', '', flat)
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
    proc = subprocess.Popen(
        f'corepack pnpm {script}',
        cwd=str(rsshub_dir),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    log('RSSHub 启动超时（120s）', 'err')
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
    s = re.sub(r'[^\w\u4e00-\u9fff]', '', s)
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
    return src.get('suggestCollection') or '00_收件箱'


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

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
    status     TEXT NOT NULL DEFAULT 'new',   -- new / shown / in_zotero
    shown_at   TEXT,
    list_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_status    ON items(status);
CREATE INDEX IF NOT EXISTS idx_ntitle    ON items(ntitle);
CREATE INDEX IF NOT EXISTS idx_published ON items(published);
CREATE INDEX IF NOT EXISTS idx_source    ON items(source_id);

-- 独立的标题指纹表：用于「只知道标题、配不上具体条目」的情况
-- （历史遗留：早期迁移进来的标题，url 和 title 曾是两份独立映射）
CREATE TABLE IF NOT EXISTS seen_titles (
    ntitle  TEXT PRIMARY KEY,
    seen_at TEXT
);
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
    """已入库的 (nurl 集合, ntitle 集合)，用于抓取判重。
    标题集合 = items 表里的标题 ∪ 独立标题表。"""
    urls = {r[0] for r in con.execute('SELECT nurl FROM items')}
    titles = {r[0] for r in con.execute(
        "SELECT ntitle FROM items WHERE ntitle IS NOT NULL AND ntitle <> ''")}
    titles |= {r[0] for r in con.execute('SELECT ntitle FROM seen_titles')}
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


def record_title(con, ntitle, when):
    if not ntitle or len(ntitle) < MIN_TITLE_FP:
        return 0
    cur = con.cursor()
    cur.execute('INSERT OR IGNORE INTO seen_titles(ntitle, seen_at) VALUES (?,?)',
                (ntitle, when))
    con.commit()
    return cur.rowcount


def main():
    ap = argparse.ArgumentParser(description='每周公考素材清单生成器')
    ap.add_argument('--config', default=str(HERE / 'sources.json'))
    ap.add_argument('--dry-run', action='store_true', help='不写文件、不改索引')
    ap.add_argument('--keep-running', action='store_true', help='跑完不关闭 RSSHub')
    ap.add_argument('--only', default='', help='只跑指定 id，逗号分隔')
    ap.add_argument('--date', default='', help='覆盖清单日期，格式 YYYY-MM-DD')
    args = ap.parse_args()

    # 用 utf-8-sig 读取：记事本等编辑器保存的 JSON 可能带 BOM
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    base = str(cfg['baseUrl']).rstrip('/')
    timeout = int(cfg.get('timeoutSec', 120))
    summary_cfg = cfg.get('summary', {})
    limit = int(summary_cfg.get('chars', 110))
    max_src = int(summary_cfg.get('maxSourceChars', 20000))
    target = int(cfg.get('listTarget', 30))
    tf = cfg.get('titleFilter', {})
    rules = cfg.get('collectionRules', [])
    out_dir = Path(cfg['outputDir'])

    only = {x.strip() for x in args.only.split(',') if x.strip()}
    sources = [s for s in cfg['sources']
               if s.get('enabled') and (not only or s['id'] in only)]
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
        cfg.get('zoteroDb', str(Path.home() / 'Zotero' / 'zotero.sqlite')))
    con = open_index(cfg)
    total, by_status, span = index_report(con)
    log('索引共 %d 条：%s' % (total, ' '.join(f'{k}={v}' for k, v in sorted(by_status.items()))))
    if span and span[0]:
        log('　发布时间跨度 %s ~ %s' % (str(span[0])[:10], str(span[1])[:10]))

    cands = index_candidates(con, 'new')
    log('待展示候选 %d 条（已展示过的不会再出现）' % len(cands))

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

    stats = {'candidates': len(cands) + len(dup_ids) + len(junk),
             'zotero_hit': len(hit), 'junk': len(junk),
             'dup_fuzzy': len(dup_ids), 'kept': 0, 'zotero_ok': zotero_ok}
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
    # 顺便把标题指纹也补进独立标题表（防止同文异链再次出现）
    for r in picked:
        record_title(con, r.get('ntitle') or '', now.strftime('%Y-%m-%d'))
    total2, by_status2, _ = index_report(con)
    con.close()

    log(f'清单已生成: {chosen.get("html") or chosen.get("md")}', 'ok')
    for fmt, p in chosen.items():
        log(f'  · {fmt.upper():<4} {p.name}  ({p.stat().st_size / 1024:.1f} KB)')
    log('索引已更新：共 %d 条（%s）' % (
        total2, ' '.join(f'{k}={v}' for k, v in sorted(by_status2.items()))), 'ok')
    print_summary(per_source, stats)
    return 0


def print_summary(per_source, stats):
    print()
    print('源选取明细（候选来自索引）')
    print('-' * 66)
    for label, avail, kept, err in per_source:
        flag = f'  [{err}]' if err else ''
        print(f'  {label:<20} 索引待展示 {avail:>4}  取 {kept:>2}{flag}')
    print('-' * 66)
    print('  索引候选 %d 条 ｜ 确定性剔除 %d 条 ｜ 已在 Zotero %d 条 ｜ 跨源重复 %d 条 ｜ 入清单 %d 条'
          % (stats.get('candidates', 0), stats.get('junk', 0), stats.get('zotero_hit', 0),
             stats.get('dup_fuzzy', 0), stats.get('kept', 0)))
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
               f"被类型上限裁掉 {stats.get('trimmed', 0)}（仍在索引里）")
    out.append('')
    return '\n'.join(out)


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


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
     ｜ 被类型上限裁掉 {stats.get('trimmed', 0)}（<b>仍在索引里，不会丢失</b>）</p>
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

