# 配置一个 vault

[English](configuring.md)

下面的内容都是可选的：配好一个数据源的 vault，已经能收集、分拣，并把一篇作品带到
发布。想改它的行为时再来看这里。

## 接入你的笔记

在这个代码仓库之外建一个私人的内容 vault：

```bash
asterism init ~/Documents/AsterismVault
```

命令会问你状态存成可读的 JSON 文件还是本地 SQLite 数据库。它建出这样的结构：

```text
AsterismVault/
  asterism.yaml
  notes/
  .asterism/state/     记账；开头的点让它不出现在 Obsidian 的文件树里
```

它同时会被建成 Git 仓库（除非这个文件夹本来就在某个仓库里），**从第一天起你写的
东西就有历史**。任何时候都不会推送。其余目录只在真的有东西时才出现：第一轮分拣出
`projects/` 和 `picks/`，第一个项目出 `settings/templates/`，搁置项目才出 `trash/`。
`settings/platforms/` 由你在写某个平台的规则时自己建。

检查配置和 macOS 集成：

```bash
asterism doctor --vault ~/Documents/AsterismVault
```

先预演一次同步，再真的写文件。不带 `--source` 时所有配好的源都会跑，**某个源失败
只会被报告，不会中断其它源**。同步成功后会生成 digest；vault 是 Git 仓库时
`--commit` 会记录一个快照（任何时候都不推送）：

```bash
asterism sync --vault ~/Documents/AsterismVault --dry-run
asterism sync --vault ~/Documents/AsterismVault
asterism sync --vault ~/Documents/AsterismVault --commit
```

用 `--source` 指定源，可以重复：

```bash
# Apple Notes
asterism sync --vault ~/Documents/AsterismVault --source apple-notes

# flomo 官方导出的 HTML 或 ZIP
asterism sync --vault ~/Documents/AsterismVault --source flomo

# Cubox，通过已登录的官方 CLI
asterism sync --vault ~/Documents/AsterismVault --source cubox

# 任意本地 Markdown 目录，包括 Obsidian
asterism sync --vault ~/Documents/AsterismVault --source markdown

# 配置范围内的 Notion 页面
asterism sync --vault ~/Documents/AsterismVault --source notion

# asterism.yaml 里声明的某个 opencli 集合
asterism sync --vault ~/Documents/AsterismVault --source opencli:twitter-bookmarks
```

**Apple Notes 的日志类笔记**：指定哪些文件夹里的笔记要按时间戳拆成碎片，以及那些
时间写的是哪个时区：

```yaml
sources:
  apple_notes:
    daily_log_folders:
      - Daily Log
    timezone: Asia/Shanghai
```

**flomo**：在 vault 的 `asterism.yaml` 里配置导出文件的位置：

```yaml
sources:
  flomo:
    export_path: /absolute/path/to/flomo-export.zip
```

**Cubox**：自己在终端里安装并登录官方 CLI，然后在不暴露凭据的前提下验证集成：

```bash
cubox-cli auth status
asterism doctor --vault ~/Documents/AsterismVault --source cubox
```

**Markdown 或 Obsidian**：配置一个或多个输入根目录，位置要在 Asterism vault 之外：

```yaml
sources:
  markdown:
    roots:
      - /absolute/path/to/ObsidianVault
```

**Notion**：创建一个只读内容的 integration，只把需要的根页面或数据源共享给它，再配
置它们的 UUID。令牌只从环境变量读取，**绝不会存进 `asterism.yaml`**：

```yaml
sources:
  notion:
    root_page_ids:
      - 00000000-0000-0000-0000-000000000000
    data_source_ids: []
    discover_all: false
```

```bash
export ASTERISM_NOTION_TOKEN='set-this-in-your-shell-or-secret-manager'
asterism doctor --vault ~/Documents/AsterismVault --source notion
asterism sync --vault ~/Documents/AsterismVault --source notion
```

`discover_all: true` 的意思是"这个 integration 能看见的每一页"，不是"工作区里的每
一页"。推荐显式指定范围：能限制误收、结果可预期，也少打 API。

**opencli**：自己安装工具（`npm install -g @jackwener/opencli`），声明 Asterism 可
以跑哪些只读命令、以及它们的列如何映射成字段。Asterism 会拿每个集合去
`opencli list` 校验、拒绝写入类命令，并且**把列的含义交给 opencli 的社区适配器和你
的映射负责**：

```yaml
sources:
  opencli:
    collections:
      - name: twitter-bookmarks
        command: [twitter, bookmarks]
        args: { limit: 200 }
        map:
          id: id
          url: url
          content: [text]
          created_at: created_at
          author: author
          exclude: [rank]
```

```bash
asterism doctor --vault ~/Documents/AsterismVault --source opencli:twitter-bookmarks
```

需要浏览器的命令要求 Chrome 装了 OpenCLI 扩展并且在对应站点已登录；opencli 返回
69 或 77 时会连同这个提示一起报出来。

## 支柱、类型和平台

一个项目是 `projects/` 下的一个文件夹，装着某一篇的卡片和 brief。整理就是一个文
件：`propose` 写出一张"还没有去向"的表，你把每一行移到它该去的地方，`apply` 把这
些决定记下来。

```bash
asterism propose --vault ~/Documents/AsterismVault             # 写出 picks/<date>.md
asterism propose --vault ~/Documents/AsterismVault --now       # 把今天收集的也算进来
# 把行移到 used / later / reference / dropped 下面；在 used 下面，
# 把同一篇的几行归到一个 `### 选题` 标题下，然后
asterism apply --vault ~/Documents/AsterismVault              # 每个标题变成一个项目
asterism status --vault ~/Documents/AsterismVault --pillar desk-setup
asterism week --vault ~/Documents/AsterismVault               # 在做什么、在等什么
asterism new "Desk lighting" --vault ~/Documents/AsterismVault --pillar desk-setup --type tutorial
```

支柱决定素材怎么分类、新项目从哪个 brief 模板开始；**匹配不上任何支柱的素材就不带
支柱，而不是猜一个**。每个支柱的别名要用素材实际使用的语言写——它们是拿去和标签、
文件夹名、以及你写的选题标题做匹配的，不会去匹配它们的译名：

```yaml
content:
  pillars:
    - { key: vibe-coding, name: Vibe Coding, tags: [coding] }
    - { key: desk-setup, name: Desk Setup, tags: [desk] }
  types: [tutorial, review, makeover, opinion, checklist]
  platforms: [blog, zhihu, xiaohongshu, douyin, sspai, flowus]
project:
  path: "{year}/{date}-{title}"   # 或者 "{pillar}/{date}-{title}"
```

决定不做的一篇叫"搁置"：`asterism drop <id>` 把它的文件夹移到 `trash/`，**什么都不
删**；`asterism restore <id>` 把它作为候选拿回来。整条流程依赖的状态都记在项目卡片
的 `status` 里。

模板在第一次被用到时播种进 vault（`settings/templates/project.md`、
`settings/templates/brief-<name>.md`），所以改了它们，之后的每个项目都跟着变。
**状态是你的**：它只在三道门——`confirm`、`accept`、`publish`——或者你在 Obsidian
里手改时才会动，从不自己往前走。

一篇作品怎么改写成某个平台的版本，是你自己写的一条笔记
`settings/platforms/<platform>.md`：篇幅、开头、必须有什么、绝不能有什么。改写平台
版本的人——你或者 agent——照着它写进 `04-exports/<platform>.md`。Asterism 不自带任何
规则，因为一个平台上什么管用，是你的判断。

`--vault` 决定输出的根。按上面的命令，Apple Notes 会写到：

```text
~/Documents/AsterismVault/notes/apple-notes/origin/
```

每个源自己决定安全的目录名，于是会有 `notes/flomo/origin/`、
`notes/cubox/origin/`、`notes/opencli-<collection>/origin/` 这些路径。`origin/` 下
面**镜像源自己的层级**：Apple Notes 的文件夹、Cubox 的收藏夹、Markdown 的目录、
Notion 的父页面都会变成子目录，一条笔记在源里挪了位置，磁盘上也跟着挪。Asterism
不会自动把代码仓库当成 vault。

为了方便本地开发，这个仓库带了一份不含任何凭据的
[`asterism.yaml`](../asterism.yaml)，所以可以直接拿仓库本身当 vault：

```bash
.venv/bin/python -m asterism.cli doctor --vault .
.venv/bin/python -m asterism.cli sync --vault . --dry-run
# 只有当你确实打算把私人测试输出写进 notes/ 时，才去掉 --dry-run。
```

生成的笔记和状态都被 Git 忽略，各个源的 README 文件保持跟踪。

初始化时想跳过交互提问：

```bash
asterism init ~/Documents/AsterismVault --state-backend sqlite
```

## Digest

每次同步之后，Asterism 会在源自己的目录里做时间维度的汇总，这个目录分成两半：
`notes/<source>/origin/` 放收集到的东西，`notes/<source>/digest/{daily,weekly,monthly,yearly}/`
放它们的汇总。**每一级都装着自己那整段时间的内容**：周包含这一周的条目，月包含这
一个月的——所以高一级单独读也读得通，把低一级归档走不会丢东西。各级互相独立，各自
在配置的那天结束周期；还开着的周期每次同步都会重建，已关闭的只生成一次，需要重做
用 `asterism digest --regenerate 2026-W39`。`include_days` 这一族开关决定某一级要不
要把下一级的内容也带上。**digest 自己不记任何分拣状态**：某段时间处理完没有，是从
它那些条目的去向推导出来的。

```yaml
digest:
  timezone: Asia/Shanghai
  week: { run_on: 3, include_days: true, archive_days: false }   # 周期在周三结束
  month: { run_on: last }
  year: { enabled: false }
```

```bash
asterism digest --vault ~/Documents/AsterismVault
asterism missing --vault ~/Documents/AsterismVault
```

`archive.enabled` 是总开关，默认关闭；打开之后，被汇总掉的 digest 会被复制或移动到
`archive.root` 下面，那个位置可以是 NAS 挂载点。`doctor` 会报告 vault 的存储情况、
在 vault 位于网络文件系统上时告警，并指出哪些归档开关因为总开关没开而无效。

## Front matter 与版本升级

每条笔记开头都是一段固定顺序的 front matter，由 `schema` 标记版本。升级到新的
schema 时，下一次同步会把每条笔记重写一遍；**文件名和状态里的键不会变**。
