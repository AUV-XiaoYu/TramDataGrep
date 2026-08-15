# CLAUDE.md

本文件给 Claude Code（以及任何接手此项目的人）提供项目速览。改代码前先读这里。

## 项目是什么

**电车票务数据平台（TRAM）**：一个纯读取型的 Web 数据浏览与导出工具。连接 Oracle 数据库，让内网用户在浏览器里浏览运营数据表并下载成 Excel/CSV。核心场景是每日运营数据清分（客流清分 / 结算清分）。

**关键性质**：对 Oracle 数据库**只读**（只有 SELECT），不写、不改、不建任何数据库对象。

## 快速启动

```bash
# 演示模式（合成假数据，无需 Oracle）
DEMO_MODE=1 venv/Scripts/python.exe -c "from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port=8080)"

# 真实数据模式（从 SQL 文件构建本地库，无需 Oracle）
DATA_BACKEND=demo_real REAL_DATA_SQL_PATH=/path/to/data.sql venv/Scripts/python.exe -c "from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port=8080)"

# 生产模式（连真 Oracle）
venv/Scripts/python.exe -c "from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port=8080)"
```

Windows 下双击 `start.bat` 是最常用的启动方式。默认管理员 `admin` / `Admin@tram2026`。

## 目录结构 / 模块职责

```
config.py         全部配置（连接串、下载阈值、会话、后端选择）。环境变量可覆盖。
backend.py        数据后端选择器：根据 Config.DATA_BACKEND 返回对应模块。
app.py            Flask 主应用：create_app() 工厂 + 所有路由。⚠️ 单文件 695 行，是冲突重灾区。
auth.py           用户认证（SQLite 存用户，读写的是 instance/users.db，与业务数据无关）。
db_oracle.py      【后端1】连真 Oracle，只读 SELECT + 元数据发现。
db_demo.py        【后端2】合成假数据，8 张仿真表，接口与 db_oracle 完全一致。
db_sqlfile.py     【后端3】从 .sql 文件构建本地 SQLite，导出真实数据。接口一致。
export.py         Excel(.xlsx)/CSV 流式生成（openpyxl write_only + csv）。
labels.py         英文表名/列名/类型 → 中文关键词的集中映射。
init_db.py        初始化用户库（instance/users.db），可单独运行。
start.bat         Windows 一键启动脚本。
templates/        9 个 Jinja2 页面（base / index / table / login / admin / diagnostics / change_password / error）。
```

## 核心架构：数据后端抽象

app.py 里 `db_oracle` 这个变量名实际指向「当前数据后端」，通过 `backend.get_backend()` 取得：

```
Config.DATA_BACKEND  ──>  backend.get_backend()  ──>  db_oracle / db_demo / db_sqlfile
    ├─ "oracle"         连真 Oracle
    ├─ "demo_large"     合成假数据（8 张表）
    └─ "demo_real"      .sql 文件 → 本地 SQLite，真实数据
```

**三个后端实现完全一致的函数接口**（这是整个架构的约定）：

```python
list_tables(search=None)                       # -> [dict(owner, table_name, num_rows, last_analyzed, avg_row_len)]
get_table_columns(owner, table_name)           # -> [dict(column_name, data_type, data_length, nullable, column_id, data_precision, data_scale)]
get_date_columns(owner, table_name)            # -> [列名]
get_table_row_count(owner, table_name, date_column=None, date_start=None, date_end=None)
get_table_data(owner, table_name, limit=100, offset=0, date_column=None, ...)  # -> (columns, rows)
stream_table_data(owner, table_name, chunk_size=None, offset=0, max_rows=None, ...)  # 生成器：先 yield columns，再 yield 行批次
estimate_row_size(owner, table_name, sample_rows=10)
estimate_table_size_mb(owner, table_name, date_column=None, ...)
get_download_plan(owner, table_name, date_column=None, ...)  # -> dict
```

**新增一个后端 = 新建一个模块实现上面 9 个函数 + 在 `backend.get_backend()` 加一个分支。** 别在 app.py 里写 if/elif。

## 中文标签映射（labels.py）

英文词转中文统一走 `labels.py`，不要散落在模板里：

```python
from labels import table_label, column_label, type_label, value_label
table_label("DAILY_PASSENGER_FLOW")   # "每日客流统计"
column_label("FLOW_DATE")             # "客流日期"
```

未收录的名称原样返回（英文），这是有意设计——新增字段不会报错，往对应字典补一条即可。

## 真实数据模式（db_sqlfile.py）的 SQL 文件约定

这是最容易踩坑的地方，写文档或交接时务必说明：

- 文件是**文本 .sql**，含 `CREATE TABLE` 和/或 `INSERT INTO`，分号分隔。
- 支持**仅 INSERT 无 CREATE TABLE** 的文件：自动按 INSERT 列清单推断建表（列全按 TEXT，日期列靠列名识别）。
- Oracle 方言做**尽力转换**：`VARCHAR2/NUMBER/DATE` → `TEXT/REAL/TEXT`；`TO_DATE('x','fmt')` → `'x'`。复杂转储（触发器/存储过程/序列）不支持。
- **日期列必须存成 ISO 文本**（`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS`），否则日期筛选的字符串比较不准。
- 日期筛选用 `>= start AND < end+1天` 实现右开区间，保证「结束日期」当天数据被完整包含。

## 关键约定 / 易错点

1. **只读铁律**：db_oracle.py 里只能有 SELECT。任何改动都不能引入写操作（INSERT/UPDATE/DELETE/DDL）。
2. **表名/列名大小写**：Oracle 后端内部统一 `.upper()`；SQLite 后端（db_sqlfile）保留原始大小写，靠 `_resolve_table`/`_resolve_column` 做大小写不敏感匹配。不要假设大小写。
3. **app.py 是大文件**：所有路由都堆在 `create_app()` 里。多人并行时，这是唯一的高冲突文件——改动尽量放自己的模块，路由改动要协调。
4. **下载安全逻辑**：`get_download_plan` 的阈值判断在三个后端里是**重复的**（safe/large/huge/blocked）。将来可抽公共函数，但现在保持三份一致即可。
5. **用户库 vs 业务库**：`instance/users.db` 是认证用的 SQLite，跟业务数据无关；`instance/real_data.db` 是 demo_real 模式构建的业务库。两者都不要提交进 git。
6. **测试用 DEMO_MODE**：demo_large 模式无需 Oracle 即可完整跑通全流程，是主要的开发/测试环境。

## 测试方法

```bash
# 冒烟测试：能建 app 就说明基本没坏
DEMO_MODE=1 venv/Scripts/python.exe -c "from app import create_app; create_app(); print('OK')"

# 后端单测（临时 SQL 文件测 db_sqlfile）
DATA_BACKEND=demo_real REAL_DATA_SQL_PATH=/tmp/t.sql venv/Scripts/python.exe -c "from backend import get_backend; print(get_backend().list_tables())"
```

目前项目**没有自动化测试**，验证靠上面的冒烟命令 + demo 模式手工点一遍（浏览表、日期筛选、下载小表）。
