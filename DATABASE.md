# 数据库结构（V1.1，`data/guanlan.sqlite3`）

SQLite，WAL 模式，开启外键。时间字段一律是 UTC 秒数（REAL），界面显示为北京时间。结构版本记录在 `PRAGMA user_version`，当前为 1。

## 表

| 表 | 一行代表 | 要点 |
|---|---|---|
| `sources` | 一个官网栏目 | 栏目定义来自 `config/sources.json`；检查频率、正文复查频率、邮件方式、是否暂停由用户在网页上设置，重启后保留。另记录运行状态、连续失败次数、上次成功与完整核对时间。 |
| `articles` | 一个唯一网址（文章或附件文件） | `url` 唯一。`kind` 为 `article` 或 `attachment`。`next_check` 安排正文复查。`title_ok=0` 表示列表标题损坏，等文章页核实。`rebase=1` 表示下次检查只重建基线、不算修订。 |
| `entries` | 官网列表里的一个条目 | 主键为（栏目, 官网条目标识）。不同条目可以指向同一篇文章；同一篇文章可以出现在多个栏目。`position` 记录官网列表顺序。 |
| `links` | 文章与附件的关联 | 一个附件可以被多篇文章引用。 |
| `versions` | 一次保存下来的内容 | 文章保存“标题 + 副标题 + 正文”的规范化文本；附件另记 `file_digest`。`baseline=1` 是基线（首次保存或规则调整），不产生提醒。 |
| `files` | 一个按 SHA-256 保存的文件 | 文件在 `data/files/<前两位>/<摘要>`。 |
| `events` | 一次需要读者知道的变化 | `kind`：`new` 新发布、`changed` 正文修订、`attachment_new` 新增附件、`attachment_changed` 附件更新。`article_id` 总是读者要打开的文章，附件变化另记 `attachment_id`。`route` 是产生时决定的邮件方式（instant / digest / off）。`read_at` 为空表示未读。`email_id` 指向发送它的即时邮件。 |
| `runs` | 一次栏目列表检查 | `mode` 为 quick 或 full。没有新内容的成功快速检查只保留 7 天。 |
| `emails` | 一封待发或已发的邮件 | 发件队列：`pending` / `sent` / `failed`，含尝试次数、下次重试时间和失败原因。 |
| `settings` | 一项设置（JSON） | `email` 邮件设置（授权码已加密），`digest_last` 上次汇总截止时间，`keep_awake` 防睡眠开关，`legacy_import` 旧版导入报告。 |

## 关键约束

- **事件与数据同事务**：新文章、新版本和对应的事件在同一个事务里写入，不会出现有变化没提醒、或有提醒没数据的情况。
- **不重复**：`events` 上的唯一索引（文章、附件、类型、版本）保证重复检查不会重复提醒。
- **基线不提醒**：栏目首次检查、文章首次保存、附件首次下载、`rebase` 重建，都只写基线版本。
- **事件的邮件方式**：取文章所在各栏目中最强的方式（即时 > 汇总 > 不发）。
- **开启前不补发**：只为邮件开启之后（`email.enabled_since`）产生的事件发邮件。

## 旧数据库

旧版的 `data/observatory.sqlite3`（结构版本 5）和 `data/engine/` 只在新库首次创建时读取一次，由 `app/legacy.py` 导入，原文件不改动。导入只包含当时在用的五个栏目，旧多国归档数据不导入。
