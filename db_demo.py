"""
演示模式：模拟 Oracle 数据库，返回逼真的电车运营数据。
接口签名与 db_oracle.py 完全一致，方便开发/演示时切换。

设置环境变量 DEMO_MODE=1 启用。

支持的日期筛选：date_column + date_start/date_end 参数
"""
import random
import re
from datetime import datetime, timedelta, date

_VALID_NAME = re.compile(r"^[A-Za-z0-9_$#]+$")


def _validate_name(name):
    if not _VALID_NAME.match(name):
        raise ValueError(f"无效的名称: {name}")


# ===== 演示数据定义 =====

_DEMO_TABLES = [
    {"owner": "TRAM", "table_name": "DAILY_PASSENGER_FLOW", "num_rows": 95800,
     "last_analyzed": datetime.now() - timedelta(days=1), "avg_row_len": 180, "description": "每日客流统计"},
    {"owner": "TRAM", "table_name": "TXN_TICKET_SALES", "num_rows": 450_000,
     "last_analyzed": datetime.now() - timedelta(hours=6), "avg_row_len": 220, "description": "票务销售交易明细"},
    {"owner": "TRAM", "table_name": "CLEARING_DAILY", "num_rows": 72_000,
     "last_analyzed": datetime.now() - timedelta(days=1), "avg_row_len": 160, "description": "每日清分结算"},
    {"owner": "TRAM", "table_name": "ROUTE_OPERATION", "num_rows": 120_000,
     "last_analyzed": datetime.now() - timedelta(days=2), "avg_row_len": 200, "description": "线路运营记录"},
    {"owner": "TRAM", "table_name": "STATION_INFO", "num_rows": 85,
     "last_analyzed": datetime.now() - timedelta(days=7), "avg_row_len": 140, "description": "站点基础信息"},
    {"owner": "TRAM", "table_name": "VEHICLE_SCHEDULE", "num_rows": 3650,
     "last_analyzed": datetime.now() - timedelta(days=1), "avg_row_len": 120, "description": "车辆调度计划"},
    {"owner": "TRAM", "table_name": "PASSENGER_FLOW_HOURLY", "num_rows": 2_100_000,
     "last_analyzed": datetime.now() - timedelta(hours=12), "avg_row_len": 150, "description": "小时级客流明细（超大表）"},
    {"owner": "TRAM_ARCHIVE", "table_name": "TXN_HISTORY_2024", "num_rows": 12_000_000,
     "last_analyzed": datetime.now() - timedelta(days=30), "avg_row_len": 220, "description": "2024年交易归档（超大表，需分片）"},
]

_COLUMNS_MAP = {
    "DAILY_PASSENGER_FLOW": [
        ("FLOW_DATE", "DATE", 7, "N"), ("LINE_NO", "VARCHAR2", 20, "N"),
        ("STATION_CODE", "VARCHAR2", 20, "N"), ("BOARDING_COUNT", "NUMBER", 22, "Y"),
        ("ALIGHTING_COUNT", "NUMBER", 22, "Y"), ("TOTAL_TRANSACTIONS", "NUMBER", 22, "Y"),
        ("CREATED_AT", "TIMESTAMP", 11, "N"),
    ],
    "TXN_TICKET_SALES": [
        ("TXN_ID", "VARCHAR2", 32, "N"), ("TXN_DATE", "DATE", 7, "N"),
        ("CARD_NO", "VARCHAR2", 20, "N"), ("LINE_NO", "VARCHAR2", 20, "N"),
        ("STATION_IN", "VARCHAR2", 20, "N"), ("STATION_OUT", "VARCHAR2", 20, "Y"),
        ("FARE_AMOUNT", "NUMBER", 10, "N"), ("DISCOUNT_AMOUNT", "NUMBER", 10, "Y"),
        ("PAYMENT_TYPE", "VARCHAR2", 10, "N"), ("TXN_TIME", "TIMESTAMP", 11, "N"),
        ("DEVICE_ID", "VARCHAR2", 16, "N"), ("SETTLEMENT_STATUS", "VARCHAR2", 4, "N"),
    ],
    "CLEARING_DAILY": [
        ("CLEARING_DATE", "DATE", 7, "N"), ("LINE_NO", "VARCHAR2", 20, "N"),
        ("TOTAL_RIDES", "NUMBER", 22, "N"), ("TOTAL_FARE", "NUMBER", 12, "N"),
        ("CASH_AMOUNT", "NUMBER", 12, "N"), ("CARD_AMOUNT", "NUMBER", 12, "N"),
        ("MOBILE_AMOUNT", "NUMBER", 12, "N"), ("SETTLEMENT_STATUS", "VARCHAR2", 8, "N"),
        ("AUDITED_BY", "VARCHAR2", 20, "Y"),
    ],
    "ROUTE_OPERATION": [
        ("OP_DATE", "DATE", 7, "N"), ("LINE_NO", "VARCHAR2", 20, "N"),
        ("VEHICLE_ID", "VARCHAR2", 16, "N"), ("DRIVER_ID", "VARCHAR2", 10, "N"),
        ("DEPARTURE_TIME", "TIMESTAMP", 11, "N"), ("ARRIVAL_TIME", "TIMESTAMP", 11, "Y"),
        ("SCHEDULED_TRIPS", "NUMBER", 22, "N"), ("ACTUAL_TRIPS", "NUMBER", 22, "Y"),
        ("DELAY_MINUTES", "NUMBER", 22, "Y"), ("PASSENGER_COUNT", "NUMBER", 22, "Y"),
        ("REMARKS", "VARCHAR2", 200, "Y"),
    ],
    "STATION_INFO": [
        ("STATION_CODE", "VARCHAR2", 20, "N"), ("STATION_NAME", "VARCHAR2", 60, "N"),
        ("LINE_NO", "VARCHAR2", 20, "N"), ("STATION_ORDER", "NUMBER", 4, "N"),
        ("LATITUDE", "NUMBER", 10, "Y"), ("LONGITUDE", "NUMBER", 10, "Y"),
        ("TRANSFER_LINES", "VARCHAR2", 100, "Y"), ("IS_ACTIVE", "VARCHAR2", 1, "N"),
    ],
    "VEHICLE_SCHEDULE": [
        ("SCHEDULE_DATE", "DATE", 7, "N"), ("VEHICLE_ID", "VARCHAR2", 16, "N"),
        ("LINE_NO", "VARCHAR2", 20, "N"), ("SHIFT_NO", "NUMBER", 4, "N"),
        ("START_TIME", "VARCHAR2", 8, "N"), ("END_TIME", "VARCHAR2", 8, "N"),
        ("ASSIGNED_DRIVER", "VARCHAR2", 10, "Y"), ("STATUS", "VARCHAR2", 8, "N"),
    ],
    "PASSENGER_FLOW_HOURLY": [
        ("FLOW_DATE", "DATE", 7, "N"), ("HOUR_SLOT", "NUMBER", 4, "N"),
        ("LINE_NO", "VARCHAR2", 20, "N"), ("STATION_CODE", "VARCHAR2", 20, "N"),
        ("BOARDING_COUNT", "NUMBER", 22, "N"), ("ALIGHTING_COUNT", "NUMBER", 22, "N"),
        ("DIRECTION", "VARCHAR2", 4, "N"), ("DATA_SOURCE", "VARCHAR2", 8, "N"),
    ],
    "TXN_HISTORY_2024": [
        ("TXN_ID", "VARCHAR2", 32, "N"), ("TXN_DATE", "DATE", 7, "N"),
        ("CARD_NO", "VARCHAR2", 20, "N"), ("LINE_NO", "VARCHAR2", 20, "N"),
        ("STATION_IN", "VARCHAR2", 20, "N"), ("STATION_OUT", "VARCHAR2", 20, "Y"),
        ("FARE_AMOUNT", "NUMBER", 10, "N"), ("PAYMENT_TYPE", "VARCHAR2", 10, "N"),
        ("TXN_TIME", "TIMESTAMP", 11, "N"), ("ARCHIVE_DATE", "DATE", 7, "N"),
    ],
}

_STATIONS = ["人民广场", "火车站", "中央大道", "滨江路", "大学城", "高新区",
             "市政府", "体育馆", "会展中心", "客运站", "机场东", "高铁站"]
_LINES = ["1号线", "2号线", "3号线", "5号线", "S1线"]
_PAYMENT_TYPES = ["CASH", "CARD", "MOBILE", "QR"]
_STATUSES = ["已结算", "待结算", "异常"]
_DRIVERS = ["D001", "D002", "D008", "D015", "D023", "D041"]

# 日期列索引（用于日期筛选时生成匹配的随机数据）
_DATE_COL_NAMES = {}  # {table_name: [list of date column names]}
for _tn, _cols in _COLUMNS_MAP.items():
    _DATE_COL_NAMES[_tn] = [c[0] for c in _cols if c[1] in ("DATE", "TIMESTAMP")]


def _get_table_meta(table_name):
    for t in _DEMO_TABLES:
        if t["table_name"] == table_name.upper():
            return t
    return None


def _random_row(cols, table_name, row_num, date_col=None, date_start=None, date_end=None):
    """生成一行随机数据，支持日期范围约束"""
    values = []
    for c in cols:
        name, dtype, _, _ = c
        if dtype == "DATE":
            if date_col and name.upper() == date_col.upper() and date_start and date_end:
                days_range = max(0, (date_end - date_start).days)
                values.append(date_start + timedelta(days=random.randint(0, days_range)))
            else:
                values.append(date.today() - timedelta(days=random.randint(0, 365)))
        elif dtype == "TIMESTAMP":
            if date_col and name.upper() == date_col.upper() and date_start and date_end:
                days_range = max(0, (date_end - date_start).days)
                d = date_start + timedelta(days=random.randint(0, days_range))
                values.append(datetime(d.year, d.month, d.day,
                                       random.randint(6, 23), random.randint(0, 59)))
            else:
                values.append(datetime.now() - timedelta(
                    days=random.randint(0, 30), hours=random.randint(0, 23),
                    minutes=random.randint(0, 59)))
        elif dtype == "NUMBER":
            if "AMOUNT" in name or "FARE" in name:
                values.append(round(random.uniform(0.5, 8.0), 2))
            elif "COUNT" in name or "RIDES" in name:
                values.append(random.randint(0, 5000))
            elif "HOUR" in name:
                values.append(random.randint(6, 23))
            elif "SHIFT" in name or "ORDER" in name:
                values.append(random.randint(1, 10))
            elif "LATITUDE" in name:
                values.append(round(random.uniform(30.5, 31.5), 6))
            elif "LONGITUDE" in name:
                values.append(round(random.uniform(120.5, 121.5), 6))
            elif "DELAY" in name:
                values.append(random.randint(-2, 15))
            else:
                values.append(random.randint(1, 100000))
        elif dtype == "VARCHAR2":
            if name == "STATION_CODE":
                values.append(f"ST{random.randint(1, 99):02d}")
            elif name == "STATION_NAME":
                values.append(random.choice(_STATIONS))
            elif "STATION_IN" in name or "STATION_OUT" in name:
                values.append(random.choice(_STATIONS))
            elif name == "LINE_NO":
                values.append(random.choice(_LINES))
            elif name == "PAYMENT_TYPE":
                values.append(random.choice(_PAYMENT_TYPES))
            elif name == "CARD_NO":
                values.append(f"CN{random.randint(10000000, 99999999)}")
            elif name == "VEHICLE_ID":
                values.append(f"V{random.randint(100, 999)}")
            elif name == "DRIVER_ID" or "DRIVER" in name:
                values.append(random.choice(_DRIVERS))
            elif name == "TXN_ID":
                values.append(f"TXN{datetime.now().strftime('%Y%m%d')}{random.randint(100000, 999999)}")
            elif name == "DEVICE_ID":
                values.append(f"DEV{random.randint(10000, 99999)}")
            elif name == "SETTLEMENT_STATUS":
                values.append(random.choice(_STATUSES))
            elif name == "AUDITED_BY":
                values.append(random.choice(_DRIVERS) if random.random() > 0.3 else None)
            elif name == "TRANSFER_LINES":
                values.append(random.choice(["2号线,5号线", "", "3号线", None, "S1线"]))
            elif name == "IS_ACTIVE":
                values.append("Y" if random.random() > 0.1 else "N")
            elif name == "STATUS":
                values.append(random.choice(["运行中", "已结束", "待分配"]))
            elif name == "DIRECTION":
                values.append(random.choice(["上行", "下行"]))
            elif name == "DATA_SOURCE":
                values.append(random.choice(["闸机", "POS机", "APP"]))
            elif name == "REMARKS":
                values.append(random.choice(["", "晚点5分钟", None, "设备故障", "正常"]))
            else:
                values.append(f"VAL_{random.randint(1, 999)}")
        else:
            values.append(f"VAL_{random.randint(1, 99)}")
    return tuple(values)


def _estimate_filtered_rows(table_name, date_start, date_end):
    """Demo 模式：根据日期范围估算过滤后的行数"""
    meta = _get_table_meta(table_name)
    if not meta or not date_start or not date_end:
        return meta["num_rows"] if meta else 0
    total_days = 365
    filter_days = max(1, (date_end - date_start).days)
    ratio = min(1.0, filter_days / total_days)
    return max(1, int(meta["num_rows"] * ratio))


# ===== 公共接口 =====

def list_tables(search=None):
    tables = _DEMO_TABLES.copy()
    if search and search.strip():
        s = search.upper().strip()
        tables = [t for t in tables if s in t["table_name"]]
    return tables


def get_table_columns(owner, table_name):
    _validate_name(owner)
    _validate_name(table_name)
    cols = _COLUMNS_MAP.get(table_name.upper(), [])
    return [{
        "column_name": c[0], "data_type": c[1], "data_length": c[2],
        "nullable": c[3], "column_id": i + 1,
        "data_precision": 10 if c[1] == "NUMBER" else None,
        "data_scale": 2 if "AMOUNT" in c[0] or "FARE" in c[0] else 0,
    } for i, c in enumerate(cols)]


def get_date_columns(owner, table_name):
    """返回表中的日期/时间列名列表"""
    cols = _COLUMNS_MAP.get(table_name.upper(), [])
    return [c[0] for c in cols if c[1] in ("DATE", "TIMESTAMP")]


def get_table_row_count(owner, table_name, date_column=None, date_start=None, date_end=None):
    """获取表行数（支持日期筛选估算）"""
    _validate_name(owner)
    _validate_name(table_name)
    if date_column and date_start and date_end:
        return _estimate_filtered_rows(table_name, date_start, date_end)
    for t in _DEMO_TABLES:
        if t["table_name"] == table_name.upper():
            return t["num_rows"]
    return 0


def get_table_data(owner, table_name, limit=100, offset=0,
                   date_column=None, date_start=None, date_end=None):
    """分页获取表数据"""
    _validate_name(owner)
    _validate_name(table_name)
    cols = _COLUMNS_MAP.get(table_name.upper(), [])
    if not cols:
        return [], []
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    actual_limit = min(limit, row_count - offset)
    if actual_limit < 0:
        actual_limit = 0
    columns = [c[0] for c in cols]
    rows = [_random_row(cols, table_name, offset + i, date_column, date_start, date_end)
            for i in range(actual_limit)]

    # 有日期筛选时按日期列降序排列（最新在前）
    if date_column:
        col_idx = next((i for i, n in enumerate(columns) if n.upper() == date_column.upper()), None)
        if col_idx is not None:
            rows.sort(key=lambda r: r[col_idx] or "", reverse=True)

    return columns, rows


def stream_table_data(owner, table_name, chunk_size=1000, offset=0, max_rows=None,
                      date_column=None, date_start=None, date_end=None):
    """流式生成表数据"""
    _validate_name(owner)
    _validate_name(table_name)
    from config import Config
    if max_rows is None:
        max_rows = Config.MAX_DOWNLOAD_ROWS
    cols = _COLUMNS_MAP.get(table_name.upper(), [])
    if not cols:
        yield []
        return
    columns = [c[0] for c in cols]
    yield columns
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    remaining = min(row_count - offset, max_rows)
    if remaining <= 0:
        return
    batch_count = 0
    while remaining > 0:
        batch_size = min(chunk_size, remaining)
        batch = [_random_row(cols, table_name, batch_count * chunk_size + offset + i,
                             date_column, date_start, date_end)
                 for i in range(batch_size)]
        batch_count += 1
        remaining -= batch_size
        yield batch


def estimate_row_size(owner, table_name, sample_rows=10):
    for t in _DEMO_TABLES:
        if t["table_name"] == table_name.upper():
            return t.get("avg_row_len", 200)
    return 200


def estimate_table_size_mb(owner, table_name, date_column=None, date_start=None, date_end=None):
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    avg_bytes = estimate_row_size(owner, table_name)
    return round(row_count * avg_bytes * 2 / (1024 * 1024), 2)


def get_download_plan(owner, table_name, date_column=None, date_start=None, date_end=None):
    """返回下载方案建议。修复：blocked 表也计算分片。"""
    from config import Config
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    est_size_mb = estimate_table_size_mb(owner, table_name, date_column, date_start, date_end)
    chunk_rows = Config.DOWNLOAD_SPLIT_CHUNK_ROWS

    plan = {
        "row_count": row_count, "est_size_mb": est_size_mb,
        "needs_split": False, "chunks": 0, "chunk_rows": chunk_rows,
        "warning_level": "safe", "warning_message": "",
    }

    # 先判断是否需要分片（独立于 warning_level）
    if row_count > Config.DOWNLOAD_CONFIRM_ROWS or est_size_mb > Config.DOWNLOAD_SPLIT_SIZE_MB:
        plan["needs_split"] = True
        plan["chunks"] = max(1, (row_count + chunk_rows - 1) // chunk_rows)

    # 再判断警告级别
    if row_count > Config.MAX_DOWNLOAD_ROWS:
        plan["warning_level"] = "blocked"
        plan["needs_split"] = True
        plan["chunks"] = max(1, (row_count + chunk_rows - 1) // chunk_rows)
        plan["warning_message"] = (
            f"表行数（{row_count:,}）超过单次下载上限（{Config.MAX_DOWNLOAD_ROWS:,}），"
            f"仅支持分片下载（共 {plan['chunks']} 片，每片 {chunk_rows:,} 行）。"
        )
    elif plan["needs_split"]:
        plan["warning_level"] = "huge"
        plan["warning_message"] = (
            f"该表有 {row_count:,} 行，预计下载大小 {est_size_mb:.0f} MB。"
            f"建议分 {plan['chunks']} 片下载（每片 {chunk_rows:,} 行）。"
        )
    elif row_count > Config.DOWNLOAD_WARN_ROWS:
        plan["warning_level"] = "large"
        plan["warning_message"] = (
            f"该表有 {row_count:,} 行，预计下载大小 {est_size_mb:.0f} MB。可以下载，但可能需要几分钟时间。"
        )

    return plan