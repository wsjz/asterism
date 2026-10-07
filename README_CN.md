# Asterism ⁂

[English](README.md)

**把散落的笔记变成发得出去的作品。**

你收集的比你写的多。想法落在 Apple Notes，文章堆在 Cubox，碎片攒在 flomo——
等你真坐下来要写，从三周的记录里找出那条贯穿始终的线索，比写本身还难。

Asterism 干的就是这一段。它把你收集的东西聚到一处，指出哪些笔记反复在说同一件
事，再把你选中的那条变成一篇作品——素材跟着一起走，直到草稿和各个平台的版本。

它不替你写，不删任何东西，没有你点头不会发布。它产出的一切都是 Markdown，放在
你自己的文件夹里，Obsidian 直接就能打开。

## 一轮是什么样

三个文件夹，按你遇到它们的顺序：

```text
notes/       收集到的一切，一条一个文件，镜像，不要手工改
picks/       每轮一张表：还没决定去向的东西
projects/    一个文件夹一篇作品，从候选选题到发布记录
```

一轮几分钟，长这样：

1. **`asterism sync`** 把新东西收进来。
2. **`asterism propose`** 写出 `picks/<date>.md`。反复出现同一个小标题的笔记
   已经被归成一条线索并标好条数——**作品通常就在那里**。
3. **你打开这张表**，把每一行移到它该去的地方：`used`、`later`、`reference`、
   `dropped`。在 `used` 下面，把属于同一篇的行归到你自己写的一个标题下。
   **那个标题就是这篇作品。**
4. **`asterism apply`** 把每个标题变成一个项目，素材跟着进去。
5. 之后这篇作品有自己的文件夹，文件名按工序编号：
   `01-project` `02-brief` `03-draft` `04-exports`。

全程只需要你做三次决定：**这篇要写什么**、**草稿够不够好**、**要不要发出去**。
没有你点头，什么都不会往前走。

## 快速开始

### 头十分钟

从一个工具里导出几条笔记，就能从零走到一个可以动笔的项目：

```bash
asterism init ~/Vault --state-backend file          # 建一个私人 vault，同时建成 Git 仓库
# 在 ~/Vault/asterism.yaml 里指向你的笔记，例如
#   sources: { markdown: { roots: [/path/to/your/notes] } }
asterism sync --vault ~/Vault                       # 收进 notes/<source>/origin/，并生成 digest
asterism propose --vault ~/Vault --now              # 写出 picks/<date>.md，含今天收集的
# 在表里把同一篇的几行移到 `## II. used` 下面，归在你自己写的
# `### 选题` 标题下，然后
asterism apply --vault ~/Vault                      # 这个标题变成一个候选项目
asterism confirm <id> --vault ~/Vault --angle 1     # 门 1：确定这篇写什么
# 在项目文件夹里写 03-draft.md，自己写或交给 agent
```

不加 `--now` 时，`propose` 只提供**已经结束的周期**——这是你每隔几天整理一次的
正常节奏；但第一天这样会什么都提供不了。

下一步：[接入你其它的笔记](docs/configuring_CN.md)。

## 写的时候

写作时反复出现的两个问题，用同一条命令回答：

```bash
asterism find "RANGE_COMPARE" --vault V                   # 这个词我最早是哪天写下的？
asterism find "percent_of_total" --vault V --in content   # 这个我是不是已经写过了？
```

结果按笔记聚合：哪一天写的、后来判成了什么、命中的是哪几行。

vault 如果是 Git 仓库，随时可以存一个档：

```bash
asterism snapshot --vault V -m "改中间那段之前"
```

它会提交 vault 里所有被跟踪的东西——**正文和笔记一样都在内**——并且从不推送。

## 用 agent 驱动

CLI 只负责记账：收集了什么、每条笔记判成了什么、进了哪篇作品、每篇过了哪道门。
**它从不写正文。** 起草、审稿、按平台改写都是判断，所以放在
`skills/asterism/SKILL.md` 里，而不是写进代码。

除 `init` 外每个命令都支持 `--json`，输出一个字段稳定的对象，agent 可以直接读
结果而不是读一段话。这个 skill 教它整套流程，更重要的是教它**边界**：agent 负责
分拣、归组、汇集素材、起草、改写平台版本，**并在三道门前各停一次，等你回答**。
把它复制到 `~/.claude/skills/` 就能配合 Claude Code 使用。

## 目前到哪一步了

- **已经真用起来的**：收集、digest、选题、项目。在真实 vault 上跑了几周。
- **走通三遍、但还没长期使用**：整条流程，从空 vault 到一条发布记录。三篇内容在
  一天之内走完全程；它还没有承载过一整周的日常写作，而那才是判定一个阶段完成的
  标准。
- **还没建的**：work-log 适配器、`assets.md` 素材清单、推送到博客、以及指标和评论
  回流成新素材。`publish` 只记录这篇发到了哪里，**不往任何地方推送**。

## 运行要求

macOS 带 Apple Notes、Python 3.11 或更新、以及允许你的终端控制 Notes 的权限。
Cubox 需要安装并登录官方的 `cubox-cli`；flomo 读取官方导出的 HTML 或 ZIP。
Asterism 从不读取这两个应用的私有数据库，也从不在命令行上接收令牌。运行时唯一的
第三方依赖是 PyYAML。

## 安全模型

笔记内容和路径一律按不可信输入处理：生成的路径不会越出 vault，SQLite 查询全部参数
化，Markdown 原子写入，采集器从不调用 shell。**任何东西都不会被删除，任何东西都不
会被推送。**

## 更多

- [配置一个 vault](docs/configuring_CN.md) —— 数据源、支柱、平台、digest
- 参与 Asterism 本身的开发：[AGENTS.md](AGENTS.md)
