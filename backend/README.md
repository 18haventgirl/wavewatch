# 服务器版开发基础（P1 第一批）

与当前 `run.py` 本机版隔离。当前提供 SQLAlchemy/Alembic 存储、SQLite v5 一致性导入、独立 scheduler/worker、五栏目列表发现、受保护的查询接口。

目前没有小程序客户端、微信登录、日报发送、完整的服务端正文/附件持续同步。旧版正文引擎仍由现有本机版运行。生产切换前必须补齐这些功能和认证；不能将本开发部署当成正式发布版。

## 独立环境

从项目根目录运行，环境变量仅在当前终端生效：

```powershell
.\.venv\Scripts\python.exe -m venv .venv-v2
.\.venv-v2\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
$env:OBS_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:55432/guanlan_v2'
# 管理令牌至少 32 个字符；通过本机安全配置提供，不提交真实值。
$env:OBS_ADMIN_TOKEN = 'REPLACE_WITH_A_FRESH_RANDOM_TOKEN_AT_LEAST_32_CHARS'
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

健康接口 `/health/live`、`/health/ready` 不暴露数据。业务接口需要 `Authorization: Bearer <开发管理令牌>`：

- `GET /api/v1/sources`
- `GET /api/v1/articles?category=cn-domestic-laws&sort=official`
- `GET /api/v1/jobs`

当前令牌仅作为开发期间管理保护，不能嵌入未来小程序包。微信用户会话与邀请权限将在 P2 实现。

## 本地容器配置

将 `deploy/.env.example` 复制为不入库的 `deploy/.env`，填入新生成的数据库密码和开发管理令牌：

```powershell
docker compose --env-file deploy/.env -f deploy/compose.dev.yml up --build -d
```

该配置仅绑定本机 8842/55432，数据库、API、scheduler、worker 分开。首次迁移后库为空，选择 seed 或迁移导入。第一次导入前先停 scheduler/worker，确保目标不被写入。需要迁移本机数据时可通过主机 CLI 访问映射的 PostgreSQL；附件目录通过 `--target-files` 指定。

数据库卷持久化。常规停止使用 `docker compose ... stop`；不要用 `down -v` 作为停止方式。此 Compose 暂不含 HTTPS 网关和 changedetection 服务，不能公开部署。

## 验证

```powershell
.\.venv-v2\Scripts\python.exe -m unittest discover -s backend/tests -v
# 推荐：启动自有临时 PostgreSQL 容器，测试后只清理该容器。
.\.venv-v2\Scripts\python.exe scripts/test_server_postgres.py
# 同时把真实 SQLite 只读导入临时 PostgreSQL，逐表核验；不覆盖源文件。
.\.venv-v2\Scripts\python.exe scripts/test_server_postgres.py --legacy-source data/observatory.sqlite3
```

没有 `OBS_TEST_DATABASE_URL` 时 PostgreSQL 测试明确跳过。不能以 SQLite 测试通过代替 PostgreSQL 测试通过。测试容器自动移除，运行过程会下载官方镜像；旧本机版的数据库和容器不在清理范围。
