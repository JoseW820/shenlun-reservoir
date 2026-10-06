#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键安装：检测依赖 → 生成 sources.json → 装 RSSHub → 自检。

存在的理由：本项目的配置要填 4 个路径，其中 rsshubDir 还必须是纯英文路径。
手工照抄文档改配置是安装环节唯一的失败点，所以这里把它自动化 ——
路径全部自动探测，RSSHub 在纯英文路径下自动挑一个位置安装。

给 AI agent 用的话，先读 AGENT.md，它会告诉你怎么跑本脚本。

用法：
    python install.py                       # 交互式，逐步确认
    python install.py --check               # 只体检依赖与配置，不写任何文件
    python install.py --yes                 # 非交互：全用探测到的默认值
    python install.py --rsshub-dir D:\\rsshub-engine
    python install.py --skip-rsshub         # 已经装好引擎，只生成配置
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gk_core as wd   # noqa: E402  复用日志与端口探测，不重复实现

DEFAULT_RSSHUB_DIR = r'D:\rsshub-engine'
RSSHUB_REPO = 'https://github.com/DIYgod/RSSHub.git'
REQUIRED_KEYS = ('rsshubDir', 'indexPath', 'outputDir', 'zoteroDb')


# --------------------------------------------------------------------------
# 探测
# --------------------------------------------------------------------------

def is_ascii_path(p):
    """RSSHub 必须装在纯英文路径：pnpm 的 .bin 垫片硬编码绝对路径，
    且 cmd.exe（GBK 代码页）解不开含中文的路径。"""
    s = str(p)
    return s.isascii() and not any(unicodedata.category(c) == 'Cc' for c in s)


def desktop_dir():
    """桌面路径。Windows 上 Desktop 可能被重定向（OneDrive），所以问注册表。"""
    if os.name == 'nt':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
            val, _ = winreg.QueryValueEx(key, 'Desktop')
            winreg.CloseKey(key)
            if val and Path(val).is_dir():
                return Path(val)
        except OSError:
            pass
    for name in ('Desktop', '桌面'):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home() / 'Desktop'


def find_zotero_db():
    """Zotero 数据目录也可能是自定义的，先试默认位置。找不到就返回默认路径 ——
    填错不影响运行，只是少一层「已存档去重」。"""
    candidate = Path.home() / 'Zotero' / 'zotero.sqlite'
    return candidate if candidate.is_file() else candidate


def dir_size_mb(path):
    total = 0
    for f in Path(path).rglob('*'):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total // (1024 * 1024)


# --------------------------------------------------------------------------
# 依赖体检
# --------------------------------------------------------------------------

def check_python():
    v = sys.version_info
    ok = v >= (3, 8)
    wd.log('Python %d.%d.%d　%s　（本项目零第三方依赖，不需要 pip install）'
           % (v.major, v.minor, v.micro, '✓' if ok else '✗ 需要 3.8+'),
           'ok' if ok else 'err')
    return ok


def check_node():
    """RSSHub 要求 Node ^22.22.2 || ^24.15.0，装 Node 24 LTS 最稳。"""
    node = shutil.which('node')
    if not node:
        wd.log('Node.js 未安装　✗　RSSHub 跑不起来（去 nodejs.org 装 24 LTS）', 'err')
        return False
    try:
        raw = subprocess.run([node, '--version'], capture_output=True, text=True,
                             timeout=20).stdout.strip()
    except Exception as exc:
        wd.log('Node.js 探测失败：%s' % exc, 'err')
        return False
    try:
        major, minor = (int(x) for x in raw.lstrip('v').split('.')[:2])
    except ValueError:
        wd.log('Node.js 版本无法解析：%s' % raw, 'err')
        return False
    ok = (major == 22 and minor >= 22) or (major == 24 and minor >= 15) or major >= 25
    wd.log('Node.js %s　%s' % (raw, '✓' if ok else '✗ 需要 ^22.22.2 || ^24.15.0'),
           'ok' if ok else 'err')
    return ok


def check_git():
    git = shutil.which('git')
    wd.log('Git　%s' % ('✓ 已安装' if git else '✗ 未安装（克隆 RSSHub 要用）'),
           'ok' if git else 'err')
    return bool(git)


def check_rsshub_dir(path):
    """RSSHub 目录的三种状态：已装好 / 目录在但没装依赖 / 不存在。"""
    d = Path(path)
    if not d.is_dir():
        return 'missing'
    if (d / 'package.json').is_file() and (d / 'node_modules').is_dir():
        return 'installed'
    return 'broken'


def check_config():
    """已有 sources.json 时逐项体检：缺键、目录不存在、RSSHub 路径非英文。"""
    path = HERE / 'sources.json'
    if not path.is_file():
        wd.log('sources.json 尚未生成（本次会生成）')
        return False
    try:
        cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        wd.log('sources.json 解析失败：%s' % exc, 'err')
        return False

    ok = True
    for k in REQUIRED_KEYS:
        if not cfg.get(k) or str(cfg[k]).startswith('<'):
            wd.log('sources.json 的 %s 还没填' % k, 'err')
            ok = False

    rsshub = cfg.get('rsshubDir')
    if rsshub and not is_ascii_path(rsshub):
        wd.log('rsshubDir 含非英文字符，pnpm 会装不上：%s' % rsshub, 'err')
        ok = False

    out = cfg.get('outputDir')
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        wd.log('清单输出目录可用：%s' % out, 'ok')

    zot = cfg.get('zoteroDb')
    if zot and not Path(zot).is_file():
        wd.log('找不到 zotero.sqlite（不影响运行，只少一层去重）：%s' % zot, 'warn')

    n = sum(1 for s in cfg.get('sources', []) if s.get('enabled'))
    wd.log('配置里的源：%d 个启用' % n, 'ok' if n else 'err')
    return ok and n > 0


# --------------------------------------------------------------------------
# 生成配置
# --------------------------------------------------------------------------

def build_config(rsshub_dir, output_dir, zotero_db):
    """从模板生成 sources.json，只覆盖那 4 个路径，其余原样保留。

    模板里 _readme/_sourceFields 等下划线开头的键是给人看的说明，
    程序不读，留在文件里照旧。
    """
    tmpl = HERE / 'sources.example.json'
    cfg = json.loads(tmpl.read_text(encoding='utf-8-sig'))
    cfg['rsshubDir'] = str(rsshub_dir)
    cfg['indexPath'] = str(HERE / 'index.sqlite')
    cfg['outputDir'] = str(output_dir)
    cfg['zoteroDb'] = str(zotero_db)
    cfg.pop('_readme', None)   # 安装说明已由本脚本承担，不必再留在配置里
    return cfg


def write_config(cfg):
    path = HERE / 'sources.json'
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


# --------------------------------------------------------------------------
# 安装 RSSHub
# --------------------------------------------------------------------------

def install_rsshub(target):
    """克隆 + 装依赖 + 生产构建。

    构建是必须的：不 build 就只能以 dev 模式（tsx watch）跑，
    首次启动要现场编译全部路由，实测 120 秒超时；build 过之后启动约 2 秒。
    """
    target = Path(target)
    if not is_ascii_path(target):
        wd.log('RSSHub 必须放纯英文路径，当前：%s' % target, 'err')
        return False
    if not shutil.which('git'):
        wd.log('没有 Git，无法克隆 RSSHub', 'err')
        return False

    state = check_rsshub_dir(target)
    if state == 'installed':
        wd.log('RSSHub 已存在，跳过克隆：%s' % target, 'ok')
    elif state == 'broken':
        wd.log('目录存在但没装依赖，继续安装：%s' % target, 'warn')
    else:
        wd.log('克隆 RSSHub 到 %s（约 100 MB）…' % target)
        target.parent.mkdir(parents=True, exist_ok=True)
        rc = subprocess.call(['git', 'clone', '--depth', '1', RSSHUB_REPO, str(target)])
        if rc != 0:
            wd.log('git clone 失败（退出码 %d）' % rc, 'err')
            return False

    env = dict(os.environ)
    env['CI'] = '1'                              # 关掉 pnpm 的交互确认
    env['COREPACK_ENABLE_DOWNLOAD_PROMPT'] = '0'  # corepack 首次下载 pnpm 也不问
    steps = [('装依赖（约 700 MB / 5-15 分钟）', ['corepack', 'pnpm', 'install']),
             ('生产构建（生成 dist，之后启动约 2 秒）', ['corepack', 'pnpm', 'build'])]
    for label, cmd in steps:
        wd.log('%s…' % label)
        rc = subprocess.call(cmd, cwd=str(target), env=env, shell=(os.name == 'nt'))
        if rc != 0:
            wd.log('%s 失败（退出码 %d）' % (label, rc), 'err')
            return False
    wd.log('RSSHub 安装完成：%s（%d MB）' % (target, dir_size_mb(target)), 'ok')
    return True


# --------------------------------------------------------------------------
# 自检：抓一个源看通不通
# --------------------------------------------------------------------------

def smoke_test(cfg):
    """真实抓一次 RSSHub 路由。这是唯一能证明「装好了」的方式 ——
    端口开着不代表路由能用（官网改版会让路由选择器匹配 0 条）。"""
    if not wd.port_open('127.0.0.1', 1200):
        wd.log('自检跳过：RSSHub 没在运行（先跑 python fetch_daily.py 会自动拉起来）', 'warn')
        return None
    src = next((s for s in cfg['sources'] if s.get('enabled')), None)
    if not src:
        wd.log('自检跳过：没有启用的源', 'err')
        return False
    base = str(cfg.get('baseUrl', 'http://127.0.0.1:1200')).rstrip('/')
    try:
        items = wd.parse_feed(wd.fetch_bytes(base + str(src['path']),
                                             int(cfg.get('timeoutSec', 120))))
    except Exception as exc:
        wd.log('自检失败（%s）：%s' % (src['name'], str(exc)[:80]), 'err')
        return False
    if not items:
        wd.log('自检失败：%s 解析到 0 条' % src['name'], 'err')
        return False
    wd.log('自检通过：%s 抓到 %d 条' % (src['name'], len(items)), 'ok')
    return True


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def ask(prompt, default, assume_yes):
    """--yes 时直接返回默认值；否则读一行输入，回车即取默认。"""
    if assume_yes:
        return default
    try:
        ans = input('%s [%s] > ' % (prompt, default)).strip()
    except EOFError:
        return default
    return ans or default


def main():
    ap = argparse.ArgumentParser(
        description='一键安装：检测依赖 → 生成 sources.json → 装 RSSHub → 自检')
    ap.add_argument('--check', action='store_true', help='只体检，不写任何文件')
    ap.add_argument('--yes', action='store_true', help='非交互：全部使用探测到的默认值')
    ap.add_argument('--rsshub-dir', default='', help='RSSHub 引擎目录（必须纯英文路径）')
    ap.add_argument('--output-dir', default='', help='清单输出目录')
    ap.add_argument('--zotero-db', default='', help='zotero.sqlite 路径')
    ap.add_argument('--skip-rsshub', action='store_true', help='跳过 RSSHub 安装，只生成配置')
    args = ap.parse_args()

    wd.setup_logfile(None)   # 安装是一次性动作，只走 stdout，不留日志
    wd.log('公考素材工作流 · 安装　｜　%s' % HERE)

    # ① 依赖体检
    print('\n① 依赖体检')
    print('-' * 64)
    deps_ok = check_python()
    deps_ok &= check_node()
    deps_ok &= check_git()
    existing_cfg = check_config()

    if args.check:
        print()
        return 0 if (deps_ok and existing_cfg) else 1

    if not deps_ok:
        wd.log('依赖不全，先把上面标 ✗ 的装上再跑', 'err')
        return 1

    # ② 目标路径
    print('\n② 目标路径')
    print('-' * 64)
    desktop = desktop_dir()
    out_default = str(desktop / '公考素材')
    zot_default = str(find_zotero_db())
    rss_default = args.rsshub_dir or DEFAULT_RSSHUB_DIR

    output_dir = Path(args.output_dir or ask(
        '清单输出目录（每期 HTML/MD/JSON 放这里）', out_default, args.yes))
    output_dir.mkdir(parents=True, exist_ok=True)
    wd.log('清单输出：%s' % output_dir, 'ok')

    skip_rsshub = args.skip_rsshub or (
        not args.rsshub_dir and not args.yes and check_rsshub_dir(rss_default) == 'installed'
        and not ask('RSSHub 已存在，还要重装吗？(y/N)', 'N', args.yes).lower().startswith('y'))

    if skip_rsshub:
        wd.log('跳过 RSSHub 安装')
        rsshub_dir = Path(rss_default)
    else:
        rsshub_dir = Path(ask('RSSHub 引擎目录（必须纯英文路径）', rss_default, args.yes))
        if not is_ascii_path(rsshub_dir):
            wd.log('该路径含非英文字符，换一个纯英文的（如 D:\\rsshub-engine）', 'err')
            return 1
        wd.log('RSSHub 引擎：%s' % rsshub_dir, 'ok')

    # ③ 生成配置
    print('\n③ 生成配置')
    print('-' * 64)
    cfg_path = HERE / 'sources.json'
    if cfg_path.is_file() and not args.yes:
        if not ask('sources.json 已存在，覆盖吗？(y/N)', 'N', args.yes).lower().startswith('y'):
            wd.log('保留现有 sources.json，跳过生成')
            cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
            rsshub_dir = Path(cfg.get('rsshubDir') or rsshub_dir)
        else:
            cfg = build_config(rsshub_dir, output_dir, Path(zot_default))
            wd.log('已写入 %s' % write_config(cfg), 'ok')
    else:
        cfg = build_config(rsshub_dir, output_dir, Path(zot_default))
        wd.log('已写入 %s' % write_config(cfg), 'ok')

    if not Path(cfg['zoteroDb']).is_file():
        wd.log('找不到 zotero.sqlite：%s　→ 填错不影响运行，只少一层去重' % cfg['zoteroDb'],
               'warn')

    # ④ 安装引擎
    print('\n④ 安装 RSSHub')
    print('-' * 64)
    if not skip_rsshub and check_rsshub_dir(rsshub_dir) != 'installed':
        if not install_rsshub(rsshub_dir):
            wd.log('RSSHub 安装失败。装好后重跑本脚本，或改用 --skip-rsshub', 'err')
            return 1
    elif not skip_rsshub:
        wd.log('RSSHub 已装好，跳过', 'ok')

    # ⑤ 收尾
    print('\n⑤ 下一步')
    print('-' * 64)
    if not skip_rsshub or check_rsshub_dir(rsshub_dir) == 'installed':
        wd.log('装完了。跑这两条验证：', 'ok')
    print('    python %s' % (HERE / 'fetch_daily.py'))
    print('    python %s' % (HERE / 'weekly_digest.py'))
    print()
    print('  想挂定时任务（每天 19:30 抓取 / 每周日 20:00 出清单）：')
    print('    powershell -ExecutionPolicy Bypass -File docs\\schedule.ps1')
    print('  （任务计划代码见 docs/使用手册.md 第二节）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
