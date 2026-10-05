# Open-Source Tooling for a Chinese Policy-News Study Pipeline
### Verified GitHub survey — Windows 11, no Docker, no WSL, no paid APIs
**Survey date:** 2026-10-01 · **`gh` version:** 2.101.0 (authenticated `gh` CLI — full 5000/hr core quota, no anonymous-search limitation)
**Method:** every repo below was checked with `gh api repos/OWNER/REPO` for `stargazers_count`, `pushed_at`, `language`, `license.spdx_id`, `archived`. `pushed_at` is used as the last-commit proxy (the REST API does not expose a per-commit date in one call) — labelled `age=` throughout. Capability claims were verified by reading manifests, source files, and deploy docs in-repo, not README blurbs. Live feeds were actually fetched from this machine.

---

## Executive summary

The most important discovery is that **your existing RSSHub routes are the right foundation, but you should stop using `rsshub.app` and either self-host or use a specific working mirror**. I tested this directly:

| Endpoint | Result from this machine |
|---|---|
| `rsshub.app/gov/cn/news/gwy` | **timeout** (confirms your experience) |
| `rsshub.rssforever.com`, `hub.slarker.me` | timeout |
| `rsshub.ktachibana.party` | HTTP 200, ~11 s |
| `rss.owo.nz` | **HTTP 200, ~6 s — fastest** |
| `rsshub.woodland.cafe` | HTTP 200, ~20 s |

`rss.owo.nz/gov/cn/news/gwy` returned **25 real items** with the correct channel title `中国政府网 - 国务院信息`, full article HTML in `<description>`, and working `gov.cn` links — e.g. 《国务院办公厅关于发展体育赛事激发消费活力的意见》→ `https://www.gov.cn/zhengce/content/202609/content_7082492.htm`. That is a usable zero-install path **today**.

But route health varies per route, and one failure is **not** an instance glitch. I verified the root cause of `/gov/zhengce/zuixin`: the live page `https://www.gov.cn/zhengce/zuixin/` now contains only **one** `<h4` and **zero** `subtitle` elements, while RSSHub's `lib/routes/gov/zhengce/index.ts` selects `h4 a, div.subtitle a[title]` → **0 matches**. This is upstream selector drift, so that route is broken everywhere until RSSHub patches it. Meanwhile `/gov/cn/news/gwy` still worked on 4 separate attempts, and `/qstheory/toutiao` returned 50 items.

**The 5 projects worth your time**

1. **[DIYgod/RSSHub](https://github.com/DIYgod/RSSHub)** — 46,383★, AGPL-3.0, pushed today. Self-host it (pnpm path, no Docker needed; your Node v24.16.0 satisfies `^22.22.2 || ^24.15.0`) *or* point your reader at `rss.owo.nz`. Solves step 1 outright.
2. **[amatya-aditya/obsidian-rss-dashboard](https://github.com/amatya-aditya/obsidian-rss-dashboard)** — 670★, MIT, pushed today. The only maintained Obsidian RSS plugin. Explicitly supports **folders and subfolders**, saving to vault as Markdown with **templates, frontmatter variables, and automatic tagging**. This is your step 3 and much of step 2.
3. **[urschrei/pyzotero](https://github.com/urschrei/pyzotero)** — 1,422★, pushed today. Now ships a **local-API CLI** with `createitem --collection --tag`, `createcollection --parent`, and `addtocollection`. Reads need no auth; one-time `pyzotero authorize` covers writes. This is the single biggest accelerator for your step 4.
4. **[obsidianmd/obsidian-clipper](https://github.com/obsidianmd/obsidian-clipper)** — 5,272★, MIT, pushed 8 days ago. The official Web Clipper; the cleanest way to capture a policy page into a chosen vault folder with YAML frontmatter.
5. **[dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io)** — 34,714★, Apache-2.0, pushed 2 days ago. The fallback for any page RSSHub cannot serve; the README documents a **Windows** install path and a Python-pip path, so it is not Docker-only.

**The honest bad news:** for **step 2 (auto-classify into your tree)** there is no maintained, free, Windows-native, policy-domain classifier worth installing. Every credible Chinese text-classification repo on GitHub is an academic training framework (you supply labelled data + torch). Realistically step 2 is either (a) a ~100-line keyword-rule script you own, or (b) the RSS Dashboard's auto-tagging. I found nothing better, and I looked.

---

## Category 1 — Self-hosted RSS/news aggregators, Windows-native feasibility

| Repo | Stars | Last push (age) | Lang | License | Archived | Windows-native? | Fit verdict |
|---|---|---|---|---|---|---|---|
| [FreshRSS/FreshRSS](https://github.com/FreshRSS/FreshRSS) | 16,194 | 2026-10-01 (1 d) | PHP | AGPL-3.0 | no | **No** — needs PHP + MySQL/SQLite + web server | Excellent aggregator, wrong platform. PHP stack on Windows is high-maintenance. |
| [miniflux/v2](https://github.com/miniflux/v2) | 9,761 | 2026-10-01 (1 d) | Go | Apache-2.0 | no | **No** — requires PostgreSQL | Great and fast, but Postgres on Windows is infra you don't want. |
| [tt-rss/tt-rss](https://github.com/tt-rss/tt-rss) | 852 | 2026-10-01 (1 d) | PHP | GPL-3.0 | no | **No** — PHP + Postgres | Same verdict as above. |
| [Athou/commafeed](https://github.com/Athou/commafeed) | 3,627 | 2026-09-24 (6 d) | Java | Apache-2.0 | no | **Partial** — JVM + DB | Java runtime + database; heavier than your problem. |
| [fossar/selfoss](https://github.com/fossar/selfoss) | 2,474 | 2026-09-28 (2 d) | PHP | GPL-3.0 | no | **No** — PHP | Largely superseded by FreshRSS/Miniflux. |
| [martinrotter/rssguard](https://github.com/martinrotter/rssguard) | 2,782 | 2026-10-01 (1 d) | C++ | GPL-3.0 | no | **Yes — native Win .exe, zero server** | **Best pure reader if you drop the aggregator model.** Qt desktop app, no DB server, no Docker. |
| [yang991178/fluent-reader](https://github.com/yang991178/fluent-reader) | 9,686 | 2026-09-16 (14 d) | TypeScript | BSD-3-Clause | no | **Yes** — Electron, ships Windows builds | Very popular, but it's a *reader*, not a filing pipeline; no Obsidian folder output. |
| [newsboat/newsboat](https://github.com/newsboat/newsboat) | 3,917 | 2026-09-26 (4 d) | C++ | MIT | no | **No** — POSIX terminal, no native Windows build | Excellent tool, wrong OS. |
| [sissbruecker/linkding](https://github.com/sissbruecker/linkding) | 11,267 | 2026-09-18 (12 d) | Python | MIT | no | Partial — Python, but it's bookmarks not feeds | Adjacent only; does not ingest RSS feeds into a study inbox. |

**Verified evidence.** FreshRSS/miniflux/tt-rss/selfoss/commafeed were judged on their documented runtime stacks (PHP, Go+Postgres, PHP+Postgres, PHP, Java+DB) — none offer a Windows-native serverless mode. `rssguard` and `fluent-reader` are the only two in this table that are **installable as a normal Windows application with no database server**, which is why they are the only credible "no-Docker" readers here. Neither writes into Obsidian, so neither advances step 3.

> **Judgement:** for your 4-step flow the aggregator question is close to a distraction. A reader like RSSGuard solves "scheduled fetching" but lands items inside its own UI, not your vault. The vault is the destination that matters.

---

## Category 2 — HTML-to-RSS / scraping-to-feed generators

| Repo | Stars | Last push (age) | Lang | License | Archived | Windows-native? | Fit verdict |
|---|---|---|---|---|---|---|---|
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | 46,383 | 2026-10-01 (1 d) | TypeScript | AGPL-3.0 | no | **Yes** — Node; pnpm clone/build documented; needs no Docker | **Top pick.** Already covers your gov.cn / qstheory / stats.gov.cn / mof.gov.cn routes. |
| [RSS-Bridge/rss-bridge](https://github.com/RSS-Bridge/rss-bridge) | 9,260 | 2026-09-30 (0 d) | PHP | Unlicense | no | **No** — PHP | Good coverage, but PHP on Windows is the blocker. |
| [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 34,714 | 2026-09-28 (2 d) | Python | Apache-2.0 | no | **Yes** — documented **Windows** guide + Python-pip install | **Best RSSHub fallback.** Watches a page, emits change notifications/feeds, no Docker required. |
| [CaoMeiYouRen/rsshub-never-die](https://github.com/CaoMeiYouRen/rsshub-never-die) | 63 | 2026-09-30 (0 d) | TypeScript | MIT | no | **Yes** — `pnpm i && pnpm build && pnpm start` (Node ≥18) | Load-balances/fails over across public RSSHub instances. Niche but directly addresses flaky mirrors. |
| [DIYgod/RSSHub-Radar](https://github.com/DIYgod/RSSHub-Radar) | 7,354 | 2026-09-01 (29 d) | TypeScript | AGPL-3.0 | no | Yes — browser extension | Useful for *discovering* that a page has a feed; not a pipeline component. |
| [huginn/huginn](https://github.com/huginn/huginn) | 50,017 | 2026-09-26 (4 d) | Ruby | MIT | no | **No** — Docker is the primary path; manual route is Ruby-on-Rails | Very powerful, abruptly wrong for a Windows student with no Ruby. |
| [html2rss/html2rss](https://github.com/html2rss/html2rss) | 165 | 2026-10-01 (1 d) | Ruby | MIT | no | **No** — Ruby gem | Capable CSS-selector feed builder, but Ruby again; low stars. |
| [stefansundin/rssbox](https://github.com/stefansundin/rssbox) | 815 | 2026-07-15 (77 d) | Ruby | AGPL-3.0 | no | **No** — Ruby, and it's a hosted service | Not self-hostable on Windows. |

**Verified evidence.**
- RSSHub's own `package.json` declares `"engines": {"node": "^22.22.2 || ^24.15.0"}` — **your Node v24.16.0 qualifies**. The `lib/routes/gov/` tree contains **71 entries** including `cn`, `zhengce`, `stats`, `mof`, `ndrc`, `pbc`, `mofcom`, `npc`, `csrc`, plus `qstheory`; `lib/routes/gov/cn/news/index.ts` covers `uid=gwy` (国务院信息) and declares `requirePuppeteer: false`, fetching via plain `got` + cheerio. `lib/routes/gov/stats/index.tsx` declares `example: '/gov/stats/sj/zxfb'` and uses `ofetch` with a cookie handshake. So **no headless browser is needed for your routes** — this is the key reason self-hosting is viable on Windows.
- **Non-Docker install is officially supported** (`RSSNext/rsshub-docs`, `src/zh/deploy/index.md`, 手动部署 section): `git clone https://github.com/DIYgod/RSSHub.git` → `pnpm i` → `pnpm build` → `pnpm start` (or `pm2 start dist/index.mjs --name rsshub`). Note it says **pnpm**, not npm; you have npm 11.13.0 and would first run `npm i -g pnpm`.
- **Warning — the npm package is not a shortcut.** `npm view rsshub` returns version `1.0.0-master.fc008f7` with **no `bin` field** and `engines` matching the repo. It is not a runnable installed app; do not plan around `npm i -g rsshub`.
- changedetection.io's README contains an explicit `### Windows` section pointing to its Windows wiki, and a separate `### Python Pip` section — so the Docker path is *recommended*, not *required*.
- `huginn` README: "The quickest and easiest way to check out Huginn is to use the official Docker image"; the non-Docker route is a Rails manual install.

**Live route health from this machine (instance `rss.owo.nz`, 2026-10-01):**

| Route | Result |
|---|---|
| `/gov/cn/news/gwy` | ✅ 25 items, real content, stable across 4 tries |
| `/qstheory/toutiao` | ✅ 50 items, title `头条 - 求是网` |
| `/gov/zhengce/zuixin` | ❌ 502 on **every** instance — **upstream selector drift confirmed** |
| `/gov/zhengce/jiedu` | ❌ 502 |
| `/gov/stats/sj/zxfb` | ❌ 502 (upstream `stats.gov.cn` itself returns 200 with a `wzws_sessionid` cookie handshake — likely the route's cookie logic or instance egress) |
| `/gov/mof/gss` | ❌ 502 (upstream `gss.mof.gov.cn` returns 200 — instance-side, not upstream) |
| `/gov/cn/news/bm` | ❌ 503 once |

Conclusion: **public instances are good enough to start and too flaky to depend on.** They are also a moving target — `rsshub.pseudoyu.com`, `yangzhi.app`, `rsshub.henry.wang`, `rsshub.speednet.icu` no longer even resolve from here, and `rsshub.pseudoyu.com` is still listed in `rsshub-never-die`'s example instance list.

---

## Category 3 — RSS/news → Obsidian pipelines

| Repo | Stars | Last push (age) | Lang | License | Archived | Windows? | Nested folders + frontmatter? | Fit verdict |
|---|---|---|---|---|---|---|---|---|
| [amatya-aditya/obsidian-rss-dashboard](https://github.com/amatya-aditya/obsidian-rss-dashboard) | 670 | 2026-10-01 (1 d) | TypeScript | MIT | no | Plugin, desktop+mobile | **Yes** — folders/subfolders, templates, frontmatter variables, auto-tagging | **Top pick for steps 2–3.** |
| [obsidianmd/obsidian-clipper](https://github.com/obsidianmd/obsidian-clipper) | 5,272 | 2026-09-22 (8 d) | TypeScript | MIT | no | Browser extension | Yes — per-site templates, folder targeting, frontmatter | **Top pick for ad-hoc capture / step 4 prep.** |
| [kepano/clipper-templates](https://github.com/kepano/clipper-templates) | 1,469 | 2026-03-13 (201 d) | — | MIT | no | n/a (JSON data) | Templates for the above | Useful template library; you'd add a gov.cn template. |
| [SilentVoid13/Templater](https://github.com/SilentVoid13/Templater) | 5,318 | 2026-09-28 (2 d) | TypeScript | AGPL-3.0 | no | Yes | Yes — full programmatic control | Worth installing to normalise frontmatter. |
| [blacksmithgu/obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview) | 9,366 | 2025-11-17 (**317 d**) | TypeScript | MIT | no | Yes | Queries frontmatter | Still the standard for building your inbox/triage views, but noticeably stalling. |
| [Vinzent03/obsidian-git](https://github.com/Vinzent03/obsidian-git) | 12,057 | 2026-09-30 (0 d) | TypeScript | MIT | no | Yes | n/a | Cheap backup/versioning of the vault. Optional. |
| [coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) | 2,981 | 2026-09-30 (0 d) | TypeScript | MIT | no | Yes (`isDesktopOnly: true`) | Yes — arbitrary path writes | The automation hook if you script your own pipeline. Latest release **5.3.1 (2026-09-28)**. |
| [zoni/obsidian-export](https://github.com/zoni/obsidian-export) | 1,336 | 2026-10-01 (1 d) | Rust | NOASSERTION | no | Yes (Rust) | Vault → plain Markdown out | **Wrong direction** for you (export, not import). |
| [deathau/markdownload](https://github.com/deathau/markdownload) | 4,029 | 2025-06-11 (**476 d**) | JavaScript | Apache-2.0 | no | Browser ext | No | Superseded by the official Web Clipper; skip. |
| [joethei/obsidian-rss](https://github.com/joethei/obsidian-rss) | 470 | 2024-10-22 (**708 d**) | TypeScript | GPL-3.0 | **ARCHIVED** | — | — | **Dead end** — archived. Widely recommended online; do not use. |
| [aoout/obsidian-rss-copyist](https://github.com/aoout/obsidian-rss-copyist) | 36 | 2024-11-13 (**686 d**) | TypeScript | MIT | no | Yes | n/a | Stale ~2 years, tiny. Skip. |

**Verified evidence.** All plugin manifests were read directly:
- `obsidian-rss-dashboard` `manifest.json`: `id: rss-dashboard`, `version 2.6.0`, `minAppVersion 1.8.7`, `isDesktopOnly: false`. Its README states: "Create folders and subfolders, add custom tags… Save articles directly to your vault as Markdown. Customize what gets saved with templates, frontmatter variables, and automatic tagging." This is the only materially capable, actively maintained option — note the README is marketing prose, so validate the auto-tagging rules against your own tree once installed.
- `joethei/obsidian-rss` `manifest.json` (`id: rss-reader`, v1.2.2) plus `archived: true` and last push 2024-10-22.
- `obsidian-local-rest-api` `manifest.json`: `version 5.3.1`, `minAppVersion 1.13.1`, `isDesktopOnly: true`, name **"Local REST API with MCP"** — i.e. the REST API and an MCP server ship together.

> **Judgement:** use RSS Dashboard for the routine "feed → nested folder + tags" landing, and the official Web Clipper for one-off policy pages. Do **not** build your own folder-writing script unless you enjoy maintenance — the Local REST API exists if you do, but it's an extra moving part.

---

## Category 4 — Automated classification / tagging, and Obsidian/Zotero MCP servers

### 4a. Classifiers — the weak spot

| Repo | Stars | Last push (age) | Lang | License | Archived | Paid API? | Fit verdict |
|---|---|---|---|---|---|---|---|
| [MaartenGr/BERTopic](https://github.com/MaartenGr/BERTopic) | 7,866 | 2026-09-24 (6 d) | Python | MIT | no | No (local) | Healthy and maintained, but it does **unsupervised** topic discovery, not assignment to *your* fixed tree. Needs embeddings + tuning. Heavy for one student. |
| [649453932/Bert-Chinese-Text-Classification-Pytorch](https://github.com/649453932/Bert-Chinese-Text-Classification-Pytorch) | 4,444 | 2024-06-28 (**824 d**) | Python | MIT | no | No | Academic framework needing labelled data + torch. **Not a product.** |
| [649453932/Chinese-Text-Classification-Pytorch](https://github.com/649453932/Chinese-Text-Classification-Pytorch) | 5,728 | 2020-09-23 (**2,198 d**) | Python | MIT | no | No | **~6 years stale.** Unusable. |
| [thunlp/THUCTC](https://github.com/thunlp/THUCTC) | 217 | 2018-09-30 (**2,922 d**) | Java | MIT | no | No | **~8 years stale.** Dead. |
| [fighting41love/funNLP](https://github.com/fighting41love/funNLP) | 83,605 | 2024-05-10 (**873 d**) | Python | NONE | no | No | Not a tool — a resource index. Still genuinely useful as a **dictionary source for keyword rules**. |

**Honest answer:** I could not find a maintained, free, Windows-native, install-and-go classifier that maps Chinese policy news onto *your* 4-branch tree. The realistic free options are (1) **keyword/regex rules you write yourself** — mapping e.g. 财政/预算/税收 → 宏观经济与财政金融政策, 乡村振兴/农业 → 农业农村与乡村振兴; this is a script of a few dozen lines, fully offline and deterministic; or (2) **RSS Dashboard's auto-tagging** driven by per-feed tags, which is coarser but zero-code. LLM classification is the technically best fit but collides head-on with your no-paid-API constraint unless you run a local model (extra GBs, GPU/RAM, ongoing maintenance — I'd skip it this phase).

### 4b. MCP servers an agent can drive

| Repo | Stars | Last push (age) | Lang | License | Archived | Fit verdict |
|---|---|---|---|---|---|---|
| [MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) | 4,456 | 2026-08-31 (30 d) | Python | MIT | no | Wraps the Local REST API plugin. Solid way to let an agent write notes into folders. |
| [cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) | 689 | 2026-09-23 (7 d) | TypeScript | Apache-2.0 | no | Read/write/search/edit notes, tags, frontmatter. Actively maintained. |
| [aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin) | 464 | 2026-09-28 (2 d) | TypeScript | MIT | no | In-Obsidian plugin exposing MCP. |
| [StevenStavrakis/obsidian-mcp](https://github.com/StevenStavrakis/obsidian-mcp) | 737 | 2026-09-10 (20 d) | TypeScript | MIT | no | Simple direct-vault MCP; fewer moving parts. |
| [jacksteamdev/obsidian-mcp-tools](https://github.com/jacksteamdev/obsidian-mcp-tools) | 831 | 2026-05-13 (140 d) | TypeScript | MIT | **ARCHIVED** | **Dead end** — archived. |
| [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) | 5,209 | 2026-09-30 (0 d) | Python | MIT | no | **Top Zotero choice.** Adds items **by DOI, URL, ISBN, BibTeX or file**, manages collections and tags. Free/MIT. |
| [cookjohn/zotero-mcp](https://github.com/cookjohn/zotero-mcp) | 1,200 | 2026-09-09 (21 d) | TypeScript | MIT | no | Zotero-internal plugin variant; alternative to the above. |
| [kujenga/zotero-mcp](https://github.com/kujenga/zotero-mcp) | 162 | 2026-08-07 (54 d) | Python | MIT | no | Lighter, less featured. |
| [obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) | 2,981 | 2026-09-30 (0 d) | TypeScript | MIT | no | The enabling plugin for every REST-based MCP option above. |

**Verified evidence (critical for you):**
- `54yyyu/zotero-mcp` README states: "**Enable Zotero's local API**: in Zotero 7+, open Settings → Advanced and tick *Allow other applications on this computer to communicate with Zotero*" and "**Writes (optional)**: on **Zotero 10+**, run `zotero-mcp authorize-local` once and choose **Always Allow**. On older Zotero, add `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID` to write through the web API." Also: "Zotero MCP is free and MIT-licensed." → **You can add items by URL into a named collection with no paid API and no web-API key, provided you are on Zotero 10+.**
- `obsidian-local-rest-api` is named **"Local REST API with MCP"** in its manifest, so you get the MCP server without a second plugin.

---

## Category 5 — Zotero automation (making manual filing faster)

| Repo | Stars | Last push (age) | Lang | License | Archived | Fit verdict |
|---|---|---|---|---|---|---|
| [zotero/zotero](https://github.com/zotero/zotero) | 15,448 | 2026-09-30 (0 d) | JavaScript | NOASSERTION | no | The client. Its **local HTTP API on 127.0.0.1** is what everything below builds on. |
| [urschrei/pyzotero](https://github.com/urschrei/pyzotero) | 1,422 | 2026-10-01 (1 d) | Python | NOASSERTION | no | **Top pick.** Local-API CLI + MCP server + `create_items`. See evidence below. |
| [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) | 5,209 | 2026-09-30 (0 d) | Python | MIT | no | Add-by-URL into a collection, agent-friendly. |
| [retorquere/zotero-better-bibtex](https://github.com/retorquere/zotero-better-bibtex) | 7,178 | 2026-09-30 (0 d) | TypeScript | MIT | no | Stable citation keys + BibTeX export. Useful later for citing sources in 申论 essays. |
| [windingwind/zotero-actions-tags](https://github.com/windingwind/zotero-actions-tags) | 2,837 | 2026-08-24 (37 d) | TypeScript | AGPL-3.0 | no | Automates tag/collection actions on save — reduces manual filing clicks. |
| [zotero/translators](https://github.com/zotero/translators) | 1,706 | 2026-09-30 (0 d) | JavaScript | NONE (see note) | no | Site-specific scrapers behind the browser connector. **No gov.cn translator.** |
| [zotero/zotero-connectors](https://github.com/zotero/zotero-connectors) | 750 | 2026-09-21 (9 d) | JavaScript | NOASSERTION | no | The browser "Save to Zotero" button — still the fastest genuine one-click capture. |
| [MuiseDestiny/zotero-style](https://github.com/MuiseDestiny/zotero-style) | 5,283 | 2026-06-07 (115 d) | JavaScript | AGPL-3.0 | no | UI/tagging quality-of-life; 797 open issues, treat as optional. |
| [jbaiter/zotero-cli](https://github.com/jbaiter/zotero-cli) | 348 | 2024-05-15 (**868 d**) | Python | MIT | no | **Dead end** — ~2.4 years stale. |

**Verified evidence — this is the highest-value part of the report.** `pyzotero`'s documentation (v1.15.2) states:
- "Passing `local=True` directs Pyzotero at a running Zotero installation instead of the web API. **Reads do not require authentication; writes require consent via a dialog in Zotero**, and a Zotero version that supports local writes."
- "**Pyzotero includes an optional CLI** for searching your local Zotero library, **adding items to it, and managing its collections.**"
- Concrete commands: `pyzotero authorize --app-name "My tool"` (one-time, choose "Always Allow"); `pyzotero createitem items.json --collection FD9AUNP2 --tag "to read"`; `pyzotero createcollection "Frankenstein Cities" --parent FD9AUNP2`; `pyzotero addtocollection FD9AUNP2 ABC123`; `pyzotero movetocollection`.
- **`--parent` means the CLI can create your nested collection tree** (01_政策与时政 → 民生保障与社会治理) programmatically, and `--collection` files new items straight into a leaf.
- It also ships an **MCP server** (`pyzotero-mcp`), read-only unless started with `--enable-writes`, with write tools `create_item`, `create_collection`, `add_to_collection`, `move_to_collection`, `add_attachment`.
- Requirement nuance: the README says local **writes** need "Zotero >= 7 (>= 10 for local writes)"; the 54yyyu README likewise says Zotero 10+ for local writes. **Check your Zotero version first** — on Zotero 7–9 you can read locally but writes fall back to the web API with a (free) key.

**Important limitation found:** `zotero/translators` — I listed the repo root and searched for government-related translators; only `CNKI.js`, `Data.gov.js`, `clinicaltrials.gov.js`, `govinfo.js` matched. **There is no `gov.cn`, `qstheory.cn`, `stats.gov.cn` or `mof.gov.cn` translator.** Therefore clicking "Save to Zotero" on a policy page will produce a **generic webpage item**, not a rich policy record with issuing agency/document number. Budget for manual metadata cleanup — this is the main reason your "manual filing" instinct is correct. (Note: `zotero/translators` shows license `NONE` via the API; the actual project is AGPL-3.0 with additional terms, so don't read `NONE` as "unlicensed".)

---

## How the top recommendations slot into your 4-step flow

**Step 1 — scheduled fetching.**
Self-host RSSHub: install pnpm (`npm i -g pnpm`), `git clone https://github.com/DIYgod/RSSHub.git`, `pnpm i`, `pnpm build`, `pnpm start` → `http://localhost:1200`. This removes your dependence on rate-limited, half-broken public mirrors and lets you patch a route when gov.cn changes its markup again — which it demonstrably does. **Interim, today:** point your reader at `https://rss.owo.nz/...` and accept that `/gov/zhengce/zuixin` and `/gov/stats/sj/zxfb` are currently 502. *Does not solve:* the upstream selector drift itself — a self-hosted instance will fail on `/gov/zhengce/zuixin` exactly as the mirrors do, because the bug is in the route code, not the host. Budget for occasionally fixing selectors or filing an upstream issue.

**Step 2 — classification.**
RSS Dashboard's automatic tagging plus per-feed folder rules gets you most of the way for free and with no code, because your sources are largely topic-homogeneous (mof.gov.cn → 宏观经济与财政金融政策; stats.gov.cn → 03_数据与报告). Refine with a small keyword-rule script if you want item-level precision. *Does not solve:* genuine semantic disambiguation — a single 国务院 document can span 民生 and 财政, and no free rules engine will read it as well as you will. Keep 99_待核实与去重 for the ambiguous tail rather than over-engineering the classifier.

**Step 3 — land in Obsidian.**
RSS Dashboard writes Markdown into folders/subfolders with templates, frontmatter variables and tags; Templater normalises frontmatter; Dataview builds your triage views over that frontmatter. For pages with no feed, use the official Web Clipper with a custom gov.cn template. *Does not solve:* deduplication across feeds (a 国务院 document often appears in both `/gov/cn/news/gwy` and `/gov/zhengce/*`) — that stays manual, which is what your 99 folder is for.

**Step 4 — Zotero filing.**
Enable Zotero's local API (Settings → Advanced → *Allow other applications on this computer to communicate with Zotero*), then `pip install "pyzotero[cli]"`, `pyzotero authorize --app-name "news-inbox"`, and use `pyzotero createcollection` once to mirror your tree, then `pyzotero createitem <file> --collection <key> --tag <tag>`. Keep the Zotero browser connector for genuine one-click saves. *Does not solve:* metadata quality — with no gov.cn translator you still get generic webpage items and must fix agency/document-number fields by hand. Also note `pyzotero`'s own docs flag that in local mode it **ignores proxy settings** unless you pass a client with `trust_env=False`, which matters if you use a system proxy to reach GitHub/Zotero.

### Suggested minimal stack, honestly labelled

| Layer | Tool | Licence | Cost | Maintenance |
|---|---|---|---|---|
| Fetch | RSSHub self-hosted (pnpm) | AGPL-3.0 | free | Low–medium; occasional selector fixes |
| Fetch fallback | changedetection.io (pip) | Apache-2.0 | free | Low |
| Inbox | Obsidian + RSS Dashboard | MIT | free | Very low |
| Capture | Official Obsidian Web Clipper | MIT | free | Very low |
| Zotero | pyzotero CLI (+ local API) | — | free | Low |
| Classify | Your own keyword rules | — | free | Medium (you own it) |

---

## Dead ends (and exactly why)

| Project | Why it's a dead end for you |
|---|---|
| [joethei/obsidian-rss](https://github.com/joethei/obsidian-rss) (470★) | **Archived**; last push 2024-10-22 (~708 d). Still the top Google/Reddit answer for "Obsidian RSS" — do not install. |
| [jacksteamdev/obsidian-mcp-tools](https://github.com/jacksteamdev/obsidian-mcp-tools) (831★) | **Archived**; 140 d stale. |
| [cooderl/wewe-rss](https://github.com/cooderl/wewe-rss) (9,661★) | **Archived** (last push 2026-03-20). Also aimed at WeChat public accounts, and Docker/Db-centric. Popular but abandoned. |
| [jbaiter/zotero-cli](https://github.com/jbaiter/zotero-cli) (348★) | Last push 2024-05-15 (~868 d). Superseded by pyzotero's own CLI. |
| [fivefilters/full-text-rss](https://github.com/fivefilters/full-text-rss) | **Repo no longer resolves** (404) — effectively gone. |
| [larsks/feedgen](https://github.com/larsks/feedgen) | **Renamed** → [lkiesow/python-feedgen](https://github.com/lkiesow/python-feedgen); last push 2024-07-04 (~818 d). A library, not a solution; stale. |
| [damoeb/rss-proxy](https://github.com/damoeb/rss-proxy) (1,924★) | Last push 2026-01-06 → ~632 d stale. No license declared. |
| [newsboat/newsboat](https://github.com/newsboat/newsboat) (3,917★) | No native Windows build (POSIX terminal UI); would require WSL, which you don't have. |
| [FreshRSS](https://github.com/FreshRSS/FreshRSS) / [miniflux](https://github.com/miniflux/v2) / [tt-rss](https://github.com/tt-rss/tt-rss) / [selfoss](https://github.com/fossar/selfoss) / [commafeed](https://github.com/Athou/commafeed) | All excellent, all need a server stack (PHP, Postgres, or JVM) that you cannot run without Docker or significant Windows sysadmin effort. Fastest way to burn a weekend. |
| [RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge) (9,260★) | PHP; same platform problem. Worth revisiting only if you ever add PHP. |
| [huginn](https://github.com/huginn/huginn) (50,017★) | Docker-primary; manual install is Ruby on Rails. Star count is not fit. |
| [html2rss](https://github.com/html2rss/html2rss) (165★) | Ruby gem, low adoption. |
| [stefansundin/rssbox](https://github.com/stefansundin/rssbox) (815★) | Hosted service written in Ruby; not a Windows self-host target. |
| [deathau/markdownload](https://github.com/deathau/markdownload) (4,029★) | ~476 d stale and outclassed by the official Web Clipper. |
| [aoout/obsidian-rss-copyist](https://github.com/aoout/obsidian-rss-copyist) (36★) | ~686 d stale, negligible adoption. |
| [649453932/Chinese-Text-Classification-Pytorch](https://github.com/649453932/Chinese-Text-Classification-Pytorch) (5,728★) / [THUCTC](https://github.com/thunlp/THUCTC) (217★) / [Bert-Chinese-Text-Classification-Pytorch](https://github.com/649453932/Bert-Chinese-Text-Classification-Pytorch) (4,444★) | Academic training frameworks needing labelled data + torch, and **all badly stale**: 2,198 d, 2,922 d and 824 d since last push respectively. High star counts, zero install-and-go value. |
| [RSSNext/Folo](https://github.com/RSSNext/Folo) (39,050★, AGPL-3.0) | Genuinely active and impressive, but it is a **hosted platform** whose shared RSSHub instances are only browsable inside Folo. Depending on someone else's server is the exact failure mode you are escaping with `rsshub.app`. |

---

## Method limitations (stated plainly)

1. **`pushed_at` is a proxy for last-commit recency.** It reflects the last push to any branch, which can overstate activity if a maintainer pushes to a side branch; and for repos where the default branch is stable, it can understate. Every date above is `pushed_at`, not the default-branch commit date.
2. **`license.spdx_id` reads `NONE`** when GitHub cannot auto-detect a standard licence, and `NOASSERTION` for custom ones. `zotero/translators`, `zotero/zotero`, `pyzotero` and `zoni/obsidian-export` all return non-standard values while being genuinely licensed — do not treat those as "unlicensed".
3. **Live-feed results are a single point in time (2026-10-01) and are partly network-dependent.** Public-instance 502/503s may reflect my routing, instance rate limits, or the route itself; I disambiguated where I could (upstream sites all returned 200; `/gov/zhengce/zuixin` was separately proven broken by selector mismatch; two other routes succeeded repeatedly on the same instance). Treat "works/doesn't work" for the *marginal* routes as indicative, not definitive. The `/gov/zhengce/zuixin` selector-drift finding and the `rsshub.app` timeout are solid.
4. **I did not install and end-to-end run** RSS Dashboard, changedetection.io, or pyzotero's CLI. Capability claims for those are from in-repo manifests, source and official documentation, which I read directly — not from live execution.
5. Every star count, date, language and licence in the tables and dead-ends list was pulled per-repo via `gh api repos/...` during this survey — there are no estimated metadata rows.

**Software/tooling versions observed:** `gh` 2.101.0 · Node v24.16.0 · npm 11.13.0 · Python 3.12.10 · git 2.54.0.windows.1 · RSSHub `engines: ^22.22.2 || ^24.15.0` · pyzotero docs v1.15.2.
