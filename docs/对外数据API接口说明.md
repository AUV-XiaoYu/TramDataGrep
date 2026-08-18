# 对外数据 API 接口说明（供下游系统开发者）

本文档面向**需要从电车票务数据平台（TRAM）拉取数据**的下游系统开发人员。

TRAM 对外提供一组只读的 HTTP API。下游系统用 HTTP GET 主动拉取数据，拿到的是 CSV 文本，适合每日清分完成后做批量同步。

---

## 1. 基本约定

| 项目 | 说明 |
| --- | --- |
| 协议 | HTTP / HTTPS（内网一般用 HTTP） |
| 数据格式 | CSV（UTF-8 带 BOM，首行为英文列名） |
| 鉴权方式 | `Authorization: Bearer <token>` 请求头 |
| 只读 | 所有接口只读，不会修改数据库 |

**基础地址**（示例，请以实际部署为准）：

```
http://<TRAM服务器IP>:8080
```

---

## 2. 鉴权（Token）

每个请求都必须携带请求头：

```
Authorization: Bearer <API_TOKEN>
```

- `<API_TOKEN>` 是一段固定字符串，由 TRAM 运维在启动服务前配置好（见文末「运维配置」）。
- 未携带或携带错误的 Token，接口返回 `401`。
- TRAM 服务未配置 Token 时，接口整体关闭，返回 `403`。

> 拿到 Token 后请妥善保管，不要写入日志或提交到代码仓库。

---

## 3. 接口列表

### 3.1 列出所有可导出的表

```
GET /api/v1/tables
```

返回 JSON：

```json
{
  "count": 2,
  "tables": [
    {
      "owner": "TRAM",
      "table_name": "DAILY_PASSENGER_FLOW",
      "num_rows": 1280000,
      "last_analyzed": "2026-08-18 04:00:00",
      "date_columns": ["FLOW_DATE", "CREATED_AT"]
    },
    {
      "owner": "TRAM",
      "table_name": "SETTLEMENT_CLEARING",
      "num_rows": 960000,
      "last_analyzed": "2026-08-18 04:00:00",
      "date_columns": ["SETTLE_DATE"]
    }
  ]
}
```

字段说明：

- `owner`：表所属 Schema（调用数据接口时的 `owner` 参数，可省略）。
- `table_name`：表名（用于数据接口的路径参数）。
- `num_rows`：近似行数（Oracle 统计值，可能不精确）。
- `date_columns`：可用来做日期筛选的列名（`date_col` 的取值来源）。

> 用途：下游系统先调这个接口发现有哪些表、以及每张表能按哪些日期列筛选，再决定拉哪些表。

### 3.2 拉取某张表的数据（CSV）

```
GET /api/v1/table/<table_name>/data
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `owner` | 否 | 表所属 Schema，默认取 TRAM 配置的 Oracle 用户，一般不用传 |
| `date_col` | 否 | 日期筛选列名（取自 3.1 的 `date_columns`） |
| `date_start` | 否 | 起始时间（含），格式 `YYYY-MM-DD` 或 `YYYY-MM-DDTHH:MM:SS` |
| `date_end` | 否 | 结束时间（含），格式同上 |

- 三个日期参数需**同时给出**才生效；都不传则导出**全表**。
- 传了 `date_col` 时，结果按该列**降序**（最新在前）。

返回：`200`，响应体即为 CSV 文本；`Content-Disposition` 里带了表名作为建议文件名。

**CSV 格式细节：**

- 编码 `UTF-8`，带 BOM（`﻿`），Excel 直接打开中文不乱码。
- 首行是英文列名（与 `date_columns`、表结构一致）。
- 换行符 `\r\n`。
- 值序列化规则：
  - 日期时间 → `YYYY-MM-DD HH:MM:SS`
  - 纯日期 → `YYYY-MM-DD`
  - `NULL` → 空字符串
  - 二进制 → UTF-8 解码后的文本

---

## 4. 调用示例

### 4.1 用 curl 测试

```bash
# 1. 列出表
curl -H "Authorization: Bearer <API_TOKEN>" \
     "http://<TRAM服务器IP>:8080/api/v1/tables"

# 2. 拉取某张表全量数据，保存为 CSV
curl -H "Authorization: Bearer <API_TOKEN>" \
     "http://<TRAM服务器IP>:8080/api/v1/table/DAILY_PASSENGER_FLOW/data" \
     -o daily_passenger_flow.csv

# 3. 按日期范围拉取（每日批量常用：只拉前一天清分完成的数据）
curl -H "Authorization: Bearer <API_TOKEN>" \
     "http://<TRAM服务器IP>:8080/api/v1/table/DAILY_PASSENGER_FLOW/data?date_col=FLOW_DATE&date_start=2026-08-17&date_end=2026-08-17" \
     -o daily_passenger_flow_20260817.csv
```

### 4.2 用 Python（requests）

```python
import requests

BASE = "http://<TRAM服务器IP>:8080"
HEADERS = {"Authorization": "Bearer <API_TOKEN>"}

# 1. 发现表
tables = requests.get(f"{BASE}/api/v1/tables", headers=HEADERS, timeout=60).json()
for t in tables["tables"]:
    print(t["table_name"], t["date_columns"])

# 2. 拉取某表某天的数据
params = {
    "date_col": "FLOW_DATE",
    "date_start": "2026-08-17",
    "date_end": "2026-08-17",
}
resp = requests.get(
    f"{BASE}/api/v1/table/DAILY_PASSENGER_FLOW/data",
    headers=HEADERS,
    params=params,
    timeout=600,          # 大表可能要几分钟
)
resp.raise_for_status()
csv_text = resp.content.decode("utf-8-sig")   # utf-8-sig 会自动去掉 BOM
print(csv_text[:500])
```

---

## 5. 错误码

| 状态码 | 含义 | 响应体 |
| --- | --- | --- |
| `200` | 成功 | CSV 或 JSON（`/api/v1/tables`） |
| `400` | 表名非法、列名不存在等参数错误 | `{"error": "..."}` |
| `401` | Token 缺失或错误 | `{"error": "无效的 API Token"}` |
| `403` | TRAM 未启用对外 API | `{"error": "..."}` |
| `500` | 服务端错误 | `{"error": "..."}` |

错误统一是 JSON，带 `error` 字段。

---

## 6. 注意事项

1. **单次下载有行数上限**（默认 500 万行）。超过上限的表会报错，请用日期筛选缩小范围后再拉；超大表建议按天批量拉取。
2. **每日批量建议在清分完成后执行**。清分（结算）完成后数据才完整，拉取时机请与 TRAM 运维对齐。
3. **大表拉取可能耗时数分钟**，请给 HTTP 客户端设足够的超时时间（如 600 秒）。
4. **接口只读**，不会对源数据库做任何写操作，不影响电车的运营系统。
5. 表名、列名均为**英文大写**，与 `date_columns` 返回的值一致，请原样使用。

---

## 附录：运维配置（TRAM 侧）

下游系统拿到的 Token，由 TRAM 运维在启动服务前配置：

```bat
:: 生成一串足够长且随机的 Token（例如用 Python 生成）
:: python -c "import secrets; print(secrets.token_urlsafe(48))"

:: 启动前设置环境变量，再启动服务
set API_TOKEN=<生成的随机字符串>
start.bat
```

- 若未设置 `API_TOKEN`，对外 API 整体关闭（返回 `403`），不影响浏览器端的正常使用。
- Token 变更后需重启服务生效。
- 若需更换 Token，请提前通知下游系统同步更新，避免拉取中断。
