# 电车票务数据平台 — Oracle 运营数据浏览器下载系统

## 概述

从有轨电车公司管理信息系统（Oracle 数据库）中导出运营数据表，使公司内网电脑通过浏览器直接浏览和下载为 Excel（.xlsx）文件。核心场景：**每日运营数据清分（客流清分 / 结算清分）**，支持按日期范围筛选后导出。

### 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 数据库 | Oracle | 通过 `oracledb` thin 模式连接，无需安装 Oracle Instant Client |
| 后端 | Python Flask + waitress | Windows 生产级 WSGI 服务器 |
| 用户管理 | SQLite + Flask-Login | 零配置、自包含，管理员 / 普通用户角色 |
| Excel 生成 | openpyxl (write_only) | 流式写入，不将整表加载到内存 |
| 前端 | Bootstrap 5 CDN | 中文界面，响应式布局，无需构建步骤 |

### 核心设计

- **运行时 Schema Discovery**：不需要预先知道表结构，通过 Oracle 元数据视图（`ALL_TABLES`、`ALL_TAB_COLUMNS`）动态发现
- **四层下载安全分级**：根据行数和预估文件大小自动分级（safe → large → huge → blocked），引导用户使用分片下载
- **日期范围筛选**：自动检测表中 DATE / TIMESTAMP 类型列，构建参数化 WHERE 子句，精准导出需要的数据
- **分片下载**：超大表自动拆分为多个 Excel 文件，每片独立下载
- **硬件感知**：启动时探测服务器可用内存，自动调整安全下载上限
- **演示模式**：无需 Oracle 即可运行，内置 8 张仿真电车运营表（覆盖所有分级场景）

---

## 快速开始

### 环境要求

- **Python 3.9+**（[python.org](https://www.python.org/downloads/) 下载，安装时勾选 "Add Python to PATH"）
- Oracle 数据库可被该 Windows 机器访问（生产模式）；或无需 Oracle（演示模式）
- 内网环境（HTTP 即可）

### 方式一：演示模式（无需 Oracle）

```batch
set DEMO_MODE=1
start.bat
```

内置 8 张仿真电车运营表，涵盖从 85 行到 1200 万行的各种场景，适合评估和测试。

### 方式二：生产模式（连接 Oracle）

编辑 `start.bat` 顶部的环境变量：

```batch
set ORACLE_USER=tram                           # Oracle 用户名
set ORACLE_PASSWORD=tram123                    # Oracle 密码
set ORACLE_DSN=192.168.1.100:1521/ORCL         # Oracle 连接串
set WEB_PORT=8080                              # Web 服务端口
```

也可通过 Windows 系统环境变量设置（优先级更高）。

双击 `start.bat`，脚本自动完成：

1. 检查 Python 环境
2. 创建虚拟环境（首次）
3. 安装依赖包
4. 初始化用户数据库（创建默认管理员）
5. 启动 waitress 服务器

### 访问

- 本机：`http://localhost:8080`
- 内网其他电脑：`http://<服务器IP>:8080`
- 默认管理员：`admin` / `Admin@tram2026`（首次登录后请立即修改密码）

---

## 文件结构

```
tram/
├── config.py              # 配置文件（Oracle连接、下载阈值、硬件探测）
├── requirements.txt       # Python 依赖清单
├── app.py                 # Flask 主应用（路由、请求处理）
├── auth.py                # 用户认证模块（登录/权限/用户CRUD）
├── db_oracle.py           # Oracle 数据库连接与查询模块
├── db_demo.py             # 演示模式：模拟 Oracle（8张电车运营表）
├── export.py              # Excel 流式导出（openpyxl write_only）
├── init_db.py             # 用户数据库初始化脚本
├── start.bat              # Windows 一键启动脚本
└── templates/
    ├── base.html              # 基础布局模板（导航栏 + Flash 消息）
    ├── login.html             # 登录页
    ├── index.html             # 数据表列表主页（Schema 分组 + 搜索）
    ├── table.html             # 表预览页（日期筛选 + 下载方案 + 分片 + 列信息 + 数据预览）
    ├── admin.html             # 用户管理面板（管理员专用）
    ├── change_password.html   # 修改密码页面
    ├── diagnostics.html       # 系统诊断页（硬件/连接/配置概览）
    └── error.html             # 错误页面（403/404/500）
```

---

## 功能清单

### 数据浏览

| 功能 | 路由 | 说明 |
|------|------|------|
| 表列表主页 | `/` | Oracle 用户表浏览，按 Schema 分组，支持实时搜索，行数颜色编码 |
| 表预览 | `/table/<name>` | 列信息 + 日期筛选 + 下载方案建议 + 前 100 行数据预览 |

### 日期筛选

表预览页自动检测表中所有 DATE / TIMESTAMP 列，显示日期筛选卡片：

1. 选择日期列（下拉框自动列出所有日期类型列）
2. 设定开始/结束日期（HTML5 日期选择器）
3. 点击「查询」→ 刷新行数预估、下载方案、数据预览
4. 点击「清除」→ 恢复全表视图

筛选后的行数和文件大小实时更新。大表加日期筛选后可降至安全级别直接下载。

**示例效果**（演示模式）：

| 表名 | 筛选前 | 10 天筛选后 |
|------|--------|------------|
| PASSENGER_FLOW_HOURLY | 210 万行 (huge) | ~5.7 万行 (safe) |
| TXN_HISTORY_2024 | 1200 万行 (blocked) | ~3.2 万行 (safe，选 1 天) |

### Excel 下载

| 功能 | 路由 | 说明 |
|------|------|------|
| 流式下载 | `/download/<name>` | 边读边写，不将整表加载到内存 |
| 分片下载 | `/download/<name>?chunk=N` | 超大表拆分为多个 Excel 文件，每片独立下载 |
| 日期筛选下载 | `/download/<name>?date_col=...&date_start=...&date_end=...` | 按日期范围导出 |
| 下载方案 API | `/api/table/<name>/plan` | JSON 格式返回行数、大小预估、分级建议 |

### 四层下载安全分级

| 级别 | 行数 | 行为 |
|------|------|------|
| 🟢 safe | < 10 万 | 直接下载，无警告 |
| 🔵 large | 10 万 ~ 50 万 | 显示信息提示，可直接下载 |
| 🟡 huge | 50 万 ~ 500 万 | 警告提示，需确认后下载；建议使用分片 |
| 🔴 blocked | > 500 万 | 拒绝直接下载，仅支持分片下载 |

阈值均可通过环境变量自定义（见下方配置参考）。

### 用户管理

| 功能 | 路由 | 权限 |
|------|------|------|
| 用户列表 | `/admin` | 管理员 |
| 创建用户 | `/admin/create` | 管理员 |
| 删除用户 | `/admin/delete/<id>` | 管理员（不能删除自己） |
| 重置密码 | `/admin/reset-password/<id>` | 管理员（生成随机密码） |
| 启用/禁用 | `/admin/toggle-active/<id>` | 管理员（不能禁用自己的账号） |
| 修改密码 | `/change-password` | 所有登录用户 |
| 登录 / 登出 | `/login` `/logout` | 公开 |

### 系统诊断

| 功能 | 路由 | 权限 | 说明 |
|------|------|------|------|
| 诊断面板 | `/diagnostics` | 管理员 | 硬件信息、Oracle 连接测试、表统计、当前配置 |

诊断页探明的内容：
- **服务器硬件**：总内存、可用内存、CPU 核心数、Python 版本
- **安全下载上限**：根据可用内存自动计算（可用内存 × 60% ÷ 2 倍膨胀系数）
- **Oracle 连接**：连通性测试 + 延迟
- **表统计**：总表数、Schema 数、各级别表数量
- **当前配置**：所有阈值的实际值

---

## 演示模式详解

设置 `DEMO_MODE=1` 后，应用使用 `db_demo.py` 替代 `db_oracle.py`。内置 8 张仿真电车运营表：

| 表名 | Schema | 行数 | 级别 | 说明 |
|------|--------|------|------|------|
| STATION_INFO | TRAM | 85 | safe | 站点基础信息 |
| VEHICLE_SCHEDULE | TRAM | 3,650 | safe | 车辆调度计划 |
| CLEARING_DAILY | TRAM | 72,000 | safe | 每日清分结算 |
| DAILY_PASSENGER_FLOW | TRAM | 95,800 | safe | 每日客流统计 |
| ROUTE_OPERATION | TRAM | 120,000 | large | 线路运营记录 |
| TXN_TICKET_SALES | TRAM | 450,000 | huge | 票务销售交易明细 |
| PASSENGER_FLOW_HOURLY | TRAM | 2,100,000 | huge | 小时级客流明细 |
| TXN_HISTORY_2024 | TRAM_ARCHIVE | 12,000,000 | blocked | 2024年交易归档（需分片） |

所有表都包含 DATE/TIMESTAMP 列，可测试日期筛选功能。演示模式接口签名与真实 Oracle 模块完全一致，确保切换时无需修改任何代码。

---

## 配置参考

`config.py` 中的主要配置项（均支持同名环境变量覆盖）：

### Oracle 连接

```python
ORACLE_USER = "tram"
ORACLE_PASSWORD = "tram123"
ORACLE_DSN = "localhost:1521/ORCL"
ORACLE_CONFIG_DIR = None        # Oracle Wallet 目录（可选）
```

### 演示模式

```python
DEMO_MODE = "0"                 # 设为 "1" 启用演示模式（无需 Oracle）
```

### 表过滤

```python
TABLE_FILTER_MODE = "all"       # "all" | "whitelist" | "blacklist"
TABLE_FILTER_PATTERNS = []      # 例如 ["TXN%", "DAILY%", "PASSENGER_FLOW"]
EXTRA_EXCLUDED_SCHEMAS = []     # 额外排除的 Schema
```

### 下载安全阈值

```python
DOWNLOAD_WARN_ROWS = 100_000            # 超过此值显示 large 警告
DOWNLOAD_CONFIRM_ROWS = 500_000         # 超过此值显示 huge 警告，需确认
MAX_DOWNLOAD_ROWS = 5_000_000           # 单次下载硬上限（超过仅分片）
DOWNLOAD_SPLIT_CHUNK_ROWS = 500_000     # 分片下载每片行数
DOWNLOAD_SPLIT_SIZE_MB = 100            # 文件超过此值建议分片
MIN_FREE_MEMORY_RATIO = 0.15            # 可用内存低于此比例拒绝下载
MAX_DOWNLOAD_MEMORY_RATIO = 0.6         # 文件超过可用内存此比例拒绝下载
```

### 其他

```python
MAX_PREVIEW_ROWS = 100                  # 预览页最多显示行数
DOWNLOAD_CHUNK_SIZE = 1000              # 每次从 Oracle 取数批量大小
PERMANENT_SESSION_LIFETIME = 28800      # 会话过期时间（8 小时）
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@tram2026"
```

---

## 安全机制

| 层面 | 措施 |
|------|------|
| 认证 | 密码 werkzeug scrypt 哈希存储，会话 8 小时过期 |
| 授权 | Flask-Login 会话管理，`@admin_required` 装饰器保护管理路由 |
| SQL 注入 | 表名 / Schema 名正则白名单 `^[A-Za-z0-9_$#]+$`；日期列名校验（确认列存在于表中） |
| 参数化查询 | 日期筛选 WHERE 子句使用 Oracle 绑定变量 `:date_start` / `:date_end` |
| 数据库连接 | 连接池（2~10 连接），Oracle 账号建议仅授予 SELECT 权限 |
| 下载保护 | 四层分级 + 分片下载 + 流式 Excel 生成 + 内存检查，防止服务器 OOM |
| 传输安全 | HttpOnly Cookie，内网环境使用 HTTP |

---

## 依赖项

| 包名 | 版本 | 用途 |
|------|------|------|
| Flask | ≥3.0, <4.0 | Web 框架 |
| Flask-Login | ≥0.6, <1.0 | 用户会话管理 |
| oracledb | ≥2.0, <3.0 | Oracle 数据库驱动（thin 模式，纯 Python） |
| openpyxl | ≥3.1, <4.0 | Excel .xlsx 流式生成（write_only 模式） |
| waitress | ≥3.0, <4.0 | Windows 兼容的生产级 WSGI 服务器 |

可选依赖：

| 包名 | 用途 |
|------|------|
| psutil | 精确探测服务器硬件（内存/CPU），未安装时使用保守默认值 |

---

## 运维操作

### 注册为 Windows 服务（开机自启）

使用 [NSSM](https://nssm.cc/)：

```powershell
nssm install TramDataExport
# Application: C:\path\to\tram\venv\Scripts\python.exe
# Arguments: -c "from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port=8080)"
# Start directory: C:\path\to\tram
nssm start TramDataExport
```

### 重置管理员密码

删除 `instance/users.db` 文件，重新运行 `start.bat` 或 `python init_db.py`，将重建默认管理员账号。

### 只暴露业务相关表

设置环境变量限制可见的表：

```batch
set TABLE_FILTER_MODE=whitelist
set TABLE_FILTER_PATTERNS=["DAILY%","CLEARING%","PASSENGER%","TXN%"]
```

---

## 常见问题

**Q: 启动时提示"无法解析 DSN"？**
A: 检查 `ORACLE_DSN` 格式：`主机:端口/服务名`（如 `192.168.1.100:1521/ORCL`）。确保 Windows 机器能 ping 通 Oracle 服务器，且防火墙放行 1521 端口。

**Q: 下载大表时浏览器显示超时？**
A: 服务端采用流式传输不会超时。如表超过 500 万行，系统会自动要求分片下载——请在表预览页使用「分片下载」按钮逐片下载。

**Q: 如何在没有 Oracle 的环境中评估系统？**
A: 设置 `DEMO_MODE=1` 启动演示模式。内置 8 张仿真电车运营表，覆盖从 85 行到 1200 万行的所有分级场景。

**Q: 如何修改 Web 服务端口？**
A: 编辑 `start.bat` 中 `WEB_PORT` 变量，或在系统环境变量中设置。

**Q: 可以用 Oracle Wallet 认证吗？**
A: 可以。设置环境变量 `ORACLE_CONFIG_DIR` 指向 Wallet 目录，并在 `ORACLE_DSN` 中使用 Wallet 中的连接名。

**Q: 忘记管理员密码怎么办？**
A: 删除 `instance/users.db` 文件，重新运行 `start.bat` 或 `python init_db.py`，将重新创建默认管理员。

**Q: 表超过 500 万行如何导出全部数据？**
A: 在表预览页使用「分片下载」区域的分片按钮，逐个下载每片 Excel 文件；或使用日期筛选缩小范围后将行数降至安全级别再下载。