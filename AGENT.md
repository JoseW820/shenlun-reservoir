# AGENT.md — 给 AI agent 的安装协议

> 这个文件是写给 **AI 编程助手**看的，不是给人看的。人类的安装说明在 [README](README.md)。
> 如果你是被用户要求「帮我装这个项目」的 agent，**读完本文件再动手**。

## 一句话

克隆仓库 → 跑 `python install.py --yes` → 跑一次 `fetch_daily.py` 验证。别手工编辑配置文件。

## 安装步骤

```bash
git clone https://github.com/JoseW820/shenlun-reservoir.git D:/公考工作流
cd D:/公考工作流
python install.py --yes            # 全自动：探测路径 + 生成配置 + 装 RSSHub + 自检
python fetch_daily.py              # 验证抓取（约 20-90 秒，需联网）
python weekly_digest.py            # 验证出清单（秒级，只读本地索引）
```

装完把这两件事告诉用户：

1. 清单输出目录（`install.py` 会打印，默认是桌面下的 `公考素材`）
2. 日常只有三个动作：打开桌面 HTML → 挑感兴趣的 → `Ctrl+Shift+S` 用 Zotero 存档

## install.py 的常用参数

| 参数 | 用途 |
|---|---|
| `--check` | 只体检依赖和配置，**不写任何文件**。先跑这个看环境 |
| `--yes` | 非交互，全用探测到的默认值。agent 用这个 |
| `--rsshub-dir D:\rsshub-engine` | 指定 RSSHub 目录 |
| `--skip-rsshub` | 已有引擎，只生成配置（用户之前装过 / 复用现有服务时用） |

## 四个硬约束（踩了就装不上）

1. **RSSHub 必须在纯英文路径。** pnpm 生成的 `.bin` 垫片里硬编码了安装时的绝对路径，且 cmd.exe（GBK）解不开中文路径。默认 `D:\rsshub-engine`，脚本会校验，别改成中文路径。工作流本体（`D:\公考工作流`）是中文路径**没问题**，Python 处理得了。
2. **Node.js 要 `^22.22.2 || ^24.15.0`**，装 Node 24 LTS 最稳。版本不对 `pnpm install` 直接报 `EBADENGINE`。
3. **`pnpm install` 要设 `CI=1`**，否则非交互环境报 `NO_TTY`。`install.py` 和 `gk_core.start_rsshub` 都已自动设好。
4. **本项目零第三方依赖**，生产运行不需要 `pip install`。唯一的例外是跑回归测试需要 `pytest`。

## 预期耗时与体积

| 阶段 | 时间 | 体积 |
|---|---|---|
| `git clone` RSSHub（浅克隆） | 1-2 分钟 | ~100 MB |
| `corepack pnpm install` | 5-15 分钟 | ~700 MB |
| `corepack pnpm build` | 2-5 分钟 | — |

**`install.py` 会连 `build` 一起做，别省。** 不 build 就只能以 dev 模式（`tsx watch`）跑，首次启动要现场编译全部路由，实测 120 秒超时；build 过之后启动约 2 秒。

## 按情况选择

- **只想让用户先看看**：跑 `python install.py --check` 展示环境体检结果，别动文件。
- **用户已经有 RSSHub 在跑**（1200 端口被占用）：用 `--skip-rsshub`，`gk_core.start_rsshub` 会检测到端口已开并直接复用。
- **RSSHub 克隆了但没装依赖**：目录里有 `package.json` 没 `node_modules`，`install.py` 会识别为 `broken` 并补装，不用删目录重来。
- **用户环境缺 Node 或 Git**：`install.py` 会明确报出来并返回非 0。先让用户装，别试图绕过。

## 常见失败与处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `pnpm install` 报 `NO_TTY` | 没设 `CI=1` | 用 `install.py`，它已设好 |
| `EBADENGINE` 警告/报错 | Node 版本不符 | 让用户装 Node 24 LTS 后重跑 |
| `install.py` 返回 1 且提示路径含非英文字符 | 违反约束 1 | 换纯英文路径 |
| 所有源都失败（`fetch_daily` 返回 2） | 没联网，或 RSSHub 没起来 | 确认联网；看 `logs/rsshub-boot.log` |
| 某源 `HTTP 503` | 官网改版，RSSHub 选择器匹配 0 条。**不是网络问题** | 该源 `enabled` 设 `false`，或去 RSSHub 提 issue |
| 清单空的 | 索引里没有待展示条目 | `python fetch_daily.py --stats` 看余量 |

## 装完之后

**不要**替用户注册计划任务，除非用户明确要求。用户要求时，定时任务的完整代码在 [docs/使用手册.md 第二节](docs/使用手册.md)，照着建两个任务即可（每天 19:30 抓取 / 每周日 20:00 出清单）。

改过滤或判重规则前先跑回归测试（**必须 cd 进项目目录**）：

```bash
python -m pytest tests -q
```

## 目录速查

```
gk_core.py        共享核心库：抓取/解析/摘要/去重/索引/Zotero。两个 CLI 都依赖它
fetch_daily.py    每日抓取 CLI（每天 19:30）→ 只写索引，不出清单
weekly_digest.py  每周清单 CLI（每周日 20:00）→ 只读索引，不抓取
install.py        一键安装（本文件所述）
sources.json      配置。由 install.py 生成；手改见 sources.example.json 里的注释
index.sqlite      ★ 唯一存储层，抓到的一切都在这里，永不删除
```

**改代码前先读 `gk_core.py` 的模块 docstring**，两个 CLI 只做流程编排，任何公共逻辑都应该加在 `gk_core.py` 里，不要在 CLI 里重复实现。
