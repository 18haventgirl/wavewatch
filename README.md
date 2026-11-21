# 观澜 · 出口管制信息监测

微信小程序与服务器持续监测的下一版规划见 [WECHAT_UPGRADE_PLAN.md](WECHAT_UPGRADE_PLAN.md)，版本管理约定见 [GIT_WORKFLOW.md](GIT_WORKFLOW.md)。V2 已实现服务器监测基础和小程序成员接口，本机微信联调见 [miniprogram/README.md](miniprogram/README.md)，后端说明见 [backend/README.md](backend/README.md)；用户准备事项见 [USER_PREPARATION.md](USER_PREPARATION.md)。下述仍为可运行的本机版，V2 尚未生产部署。

本机运行的中文信息观察台，前端沿用“利润分析/任务2”的冷蓝渐变、宽内容区和玻璃面板风格。当前仅监测中国出口管制信息网：法律（13）、法规（14）、规章及规范性文件（15）作为核心政策栏目，国内动态（1）、国际动态（2）作为辅助资讯栏目。复用 changedetection.io 0.70.4 保存正文快照；业务数据使用 SQLite。完整关系说明见 DATABASE.md。

## 使用

Windows PowerShell，在本目录运行：

```powershell
.\start.ps1
```

打开 http://127.0.0.1:8840/ 。保持运行窗口开启，关闭网页不影响后台监测。停止程序可按 Ctrl+C 或运行 `stop.ps1`。关机、休眠或程序退出期间不能持续检查，重启后会处理到期来源。

首次安装或更换电脑：安装 Python 3.11+ 与 Node.js 20.19+，运行：

```powershell
.\start.ps1 -Install
```

程序仅监听本机。8840 是中文界面，8841 是本机 changedetection.io 引擎。引擎 key 不传给前端。不要把这两个端口直接暴露到公网；服务器多用户部署需要另行配置身份认证。

## 当前范围与实际边界

- 只调度五个指定中国栏目；活动数据库与监测引擎已从空存储重新建立，旧多国数据库和旧引擎移入 `archive/china-scope-reset-20261120-110023/`，不参与当前查询、统计、提醒或调度。
- 按官网分页抓取，安全上限为每栏目 100 页；界面分别显示官网条数、有效列表条目和去重后的文章数，逐页响应摘要保存在数据库中。
- 分类依据官网栏目归属；国家、发布网站、分类树、采集入口、文章栏目关联都有独立关系。不能仅根据文章首次发现来源判断全部分类。
- 同 URL 文章全局去重；不同官网条目标识可指向同一文章。同一附件也可关联多篇文章，版本与未读提醒使用明确的关联表。
- 来源页面和文章详情显示“国家 / 发布网站 / 父栏目 / 子栏目”，可按五个子栏目筛选。界面把政策法规标为核心监测，把两个动态栏目标为辅助资讯。
- 首次收录建立历史基线，迁移分类和补录历史不产生一批新消息。已保存正文与附件发生变化后生成站内未读提醒。
- 列表接口存在问号标题时，会回查官方文章页核实。正文与附件初始快照仍分批同步，界面分别显示完成数量和错误。
- 附件另存 SHA-256 与文件副本。PDF 文本提取最多前 50 页、20 秒；图片扫描 PDF 明示无可提取文本，文件字节变化不自动等于政策变化。
- 关机、休眠或停止程序期间不能持续检查。关闭网页不影响正在运行的本机后台服务。
- 当前是中国五栏目的调试版本，尚未完成长期运行、全部附件逐项人工核对与未来服务器部署验收。

## 数据与备份

业务数据在 `data/observatory.sqlite3`，引擎数据在 `data/engine/`，附件按内容指纹存入 `data/attachments/`。运行日志在 `logs/engine.log`。活动库的数据范围由 `data_scopes` 关系和数据库触发器约束；活动来源必须明确属于 `china-exportcontrol` 范围。

先停止服务，再运行：

```powershell
.\.venv\Scripts\python.exe scripts/backup.py
```

备份存于 `backups/`，含本机引擎配置及其 API key，请作为私人备份保存。恢复时先停止服务，将当前 `data/` 重命名保留，再将可信备份中的 `data/` 与 `config/` 解压到项目目录，之后启动。不要把恢复文件覆盖到正在运行的数据目录。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
```

测试使用独立临时数据库，不往真实信息库写入虚构公告。首次基线、去重、修订提醒、附件关联提醒、已读持久化、来源故障隔离和接口边界都有固定样本验证。真实官网状态仍以界面运行记录为准。

## 上游

- changedetection.io：https://github.com/dgtlmoon/changedetection.io （Apache-2.0）
- 接口文档：https://github.com/dgtlmoon/changedetection.io/blob/master/docs/api-spec.yaml
- 前端：React、TypeScript、Vite、Lucide；业务：FastAPI、SQLite、httpx、BeautifulSoup；PDF 文本：pypdf。

原始开发计划及阶段边界见 `DEVELOPMENT_PLAN.md`。
