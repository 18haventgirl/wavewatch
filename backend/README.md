# 服务器版开发环境（P2 小程序联调）

与当前 `run.py` 本机版隔离。当前提供 SQLAlchemy/Alembic 存储、SQLite v5 一致性导入、独立 scheduler/worker、五栏目列表发现、正文历史同步、标题核实、附件发现/版本保存和受保护的查询接口。

已提供 Taro 小程序、服务端微信登录、一次性邀请、独立个人未读与偏好接口；本机操作见 [miniprogram/README.md](../miniprogram/README.md)。真实微信登录、开发者工具界面与真机尚待联调；日报发送及正式 HTTPS 部署尚未完成。独立引擎的真实正文链路已验证，Linux 容器构建仍受 Docker Hub 连接中断影响，不能将本开发配置当成正式发布版。

## 独立环境

从项目根目录运行，环境变量仅在当前终端生效：

```powershell
.\.venv\Scripts\python.exe -m venv .venv-v2
.\.venv-v2\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
$env:OBS_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/guanlan_v2'
# 管理令牌至少 32 个字符；通过本机安全配置提供，不提交真实值。
$env:OBS_ADMIN_TOKEN = 'REPLACE_WITH_A_FRESH_RANDOM_TOKEN_AT_LEAST_32_CHARS'
$env:OBS_ENGINE_URL = 'http://127.0.0.1:8851'
$env:OBS_ENGINE_KEY = 'REPLACE_WITH_A_SEPARATE_RANDOM_ENGINE_KEY'
$env:OBS_FILES_ROOT = (Join-Path (Get-Location) 'data-v2')
.\.venv-v2\Scripts\python.exe -m backend.cli migrate
```

### 路径 A：演练已有数据迁移

需要一个已迁移且**没有种子/业务数据**的目标库。运行 scheduler/worker 之前完成导入。源 SQLite 以只读事务获取一致性快照；原目录保持完整，附件放在同级 attachments/。正式切换仍需先停止旧写入并备份。

```powershell
.\.venv-v2\Scripts\python.exe -m backend.cli import-legacy data/observatory.sqlite3
.\.venv-v2\Scripts\python.exe -m backend.cli import-legacy data/observatory.sqlite3 --apply --target-files data-v2
```

默认只检查不导入。`--apply` 会核验逐表规范化内容摘要、外键、版本、附件；目标非空拒绝覆盖。保存旧拥有者的已读状态，历史导入不产生任务或新事件。暂不导入到生产库。

### 路径 B：从空库重新采集

与迁移二选一，不要先 seed 再导入：

```powershell
.\.venv-v2\Scripts\python.exe -m backend.cli seed
```

### 独立进程

分别在有相同环境配置的终端启动：

```powershell
.\.venv-v2\Scripts\python.exe -m uvicorn backend.api:create_app --factory --host 127.0.0.1 --port 8842 --no-access-log
.\.venv-v2\Scripts\python.exe -m backend.cli scheduler
.\.venv-v2\Scripts\python.exe -m backend.cli worker
```

手动单次调度/消费：`python -m backend.cli tick`、`python -m backend.cli worker --once`。API 进程不进行迁移、采集或后台同步；增加 API 实例不增加调度线程。

健康接口 `/health/live`、`/health/ready` 不暴露数据。业务查询接口需要 `Authorization: Bearer <成员会话或开发管理令牌>`：

- `GET /api/v1/sources`
- `GET /api/v1/articles?category=cn-domestic-laws&sort=official`
- `GET /api/v1/jobs`：仅管理员
- `GET /api/v1/articles/{id}`：版本、差异、附件、独立采集状态
- `GET /api/v1/attachments/{id}/download`：受身份验证保护的文件

开发管理令牌不能嵌入小程序包，也不能代替个人登录。`POST /api/v1/auth/wechat` 以微信 code 和首次邀请码换取短期成员会话；个人接口使用 `/api/v1/me`、`/api/v1/me/events` 和 `/api/v1/me/preferences`。微信密钥只由后端读取 `OBS_WECHAT_APP_SECRET`；本机联调入口提供隐藏输入，不写入文件。管理员通过 `POST /api/v1/admin/invitations` 生成普通成员的一次性邀请码。

## 本地容器配置

将 `deploy/.env.example` 复制为不入库的 `deploy/.env`，填入新生成的数据库密码和开发管理令牌：

```powershell
docker compose --env-file deploy/.env -f deploy/compose.dev.yml up --build -d
```

该配置仅绑定本机 8842/55432，数据库、API、scheduler、worker、独立 changedetection.io 分开；引擎不对主机开放端口。必须在 deploy/.env 配置额外的 OBS_ENGINE_KEY。首次迁移后库为空，选择 seed 或迁移导入。第一次导入前先停 scheduler/worker，确保目标不被写入。附件使用 API 与 Worker 共用的持久化卷；不能把主机附件复制到任意临时目录后就宣称容器可用，正式容器迁移必须把附件导入同一卷。

数据库、附件和引擎均使用持久化卷。常规停止使用 `docker compose ... stop`；不要用 `down -v` 作为停止方式。此 Compose 暂不含 HTTPS 网关，不能公开部署。

`backend.engine_bootstrap` 在上游引擎启动前通过固定版本的配置存储设置专用 API key，并启用校验；不修改上游代码、不加载旧 data/engine 的密钥或任务。Windows 独立运行该模块时使用原 .venv（已安装固定版上游），配置 OBS_ENGINE_DATA 指向 data-v2 下的新目录，OBS_ENGINE_HOST 默认为 127.0.0.1。不要把它指向本机版 data/engine。

## 验证

```powershell
.\.venv-v2\Scripts\python.exe -m unittest discover -s backend/tests -v
# 推荐：启动自有临时 PostgreSQL 容器，测试后只清理该容器。
.\.venv-v2\Scripts\python.exe scripts/test_server_postgres.py
# 同时把真实 SQLite 只读导入临时 PostgreSQL，逐表核验；不覆盖源文件。
.\.venv-v2\Scripts\python.exe scripts/test_server_postgres.py --legacy-source data/observatory.sqlite3
# 真实官网 -> 独立上游引擎 -> 正文版本 -> 受保护详情接口
.\.venv-v2\Scripts\python.exe -X utf8 scripts/smoke_server_monitor.py
```

没有 `OBS_TEST_DATABASE_URL` 时 PostgreSQL 测试明确跳过。不能以 SQLite 测试通过代替 PostgreSQL 测试通过。测试容器自动移除，运行过程会下载官方镜像；旧本机版的数据库和容器不在清理范围。
