"""
真实数据后端：从一个 SQL 数据文件构建本地 SQLite 库，并导出真实数据。

接口签名与 db_oracle.py 完全一致，app.py 无需任何改动即可切换。

工作方式：
    1. 读取 Config.REAL_DATA_SQL_PATH 指向的 .sql 文件
    2. 把 SQL 语句执行进本地 SQLite（缓存到 Config.REAL_DATA_DB_PATH）
    3. 后续所有查询都从 SQLite 读取，返回格式与 Oracle 后端一致

SQL 文件格式约定（重要）：
    - 文本 .sql 文件，包含 CREATE TABLE 和 / 或 INSERT INTO 语句，分号分隔。
    - 推荐直接提供 SQLite/可移植方言（VARCHAR2/NUMBER/DATE 会被自动转成
      TEXT/REAL/TEXT，TO_DATE('x','fmt') 会被自动转成 'x'）。
    - 只有 INSERT、没有 CREATE TABLE 的文件也支持：会自动根据 INSERT 的
      列清单推断建表（所有列按 TEXT 处理，日期列按列名识别）。
    - 日期/时间列的值建议存成 ISO 文本（YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS），
      这样日期筛选的字符串比较才准确。
    - 复杂 Oracle 转储（触发器、存储过程、序列等）不受支持，请用可移植格式导出。

配置项（见 config.py）：
    REAL_DATA_SQL_PATH    .sql 文件路径（必填）
    REAL_DATA_DB_PATH     构建出的 SQLite 库路径（默认 instance/real_data.db）
    REAL_DATA_OWNER       列表里显示的 Schema 名（默认 TRAM，仅用于展示）
"""
import os
import re
import sqlite3
import threading
from datetime import datetime, date, timedelta

from config import Config

# ===== 内部状态 =====
_VALID_NAME = re.compile(r"^[A-Za-z0-9_$#]+$")
_build_lock = threading.Lock()
_db_path = None
_OWNER = Config.REAL_DATA_OWNER.upper()


def _validate_name(name):
    if not _VALID_NAME.match(name or ""):
        raise ValueError(f"无效的名称: {name}")


# ===== SQL 文件解析 =====

def _read_sql(path):
    """读取 SQL 文件，自动尝试常见编码（含中文 Windows 的 GBK）。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_statements(sql_text):
    """按分号拆分 SQL 语句，忽略字符串字面量和注释里的分号。"""
    statements = []
    buf = []
    in_single = False
    in_line = False
    in_block = False
    i, n = 0, len(sql_text)
    while i < n:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < n else ""
        if in_line:
            buf.append(ch)
            if ch == "\n":
                in_line = False
        elif in_block:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                in_block = False
                buf.append("/")
                i += 1
        elif in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append("'")
                i += 1
            elif ch == "'":
                in_single = False
        else:
            if ch == "-" and nxt == "-":
                in_line = True
                buf.append("--")
                i += 1
            elif ch == "/" and nxt == "*":
                in_block = True
                buf.append("/*")
                i += 1
            elif ch == "'":
                in_single = True
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    statements.append(stmt)
                buf = []
            else:
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _normalize_types(create_sql):
    """把 Oracle 数据类型转成 SQLite 类型（仅用于 CREATE TABLE 语句）。"""
    rules = [
        (r"\bVARCHAR2\s*\(\s*\d+\s*(?:CHAR|BYTE)?\s*\)", "TEXT"),
        (r"\bNVARCHAR2\s*\(\s*\d+\s*\)", "TEXT"),
        (r"\bVARCHAR\s*\(\s*\d+\s*\)", "TEXT"),
        (r"\bCHAR\s*\(\s*\d+\s*\)", "TEXT"),
        (r"\bCLOB\b", "TEXT"),
        (r"\bNUMBER\s*\(\s*\d+\s*,\s*\d+\s*\)", "REAL"),
        (r"\bNUMBER\s*\(\s*\d+\s*\)", "INTEGER"),
        (r"\bNUMBER\b", "REAL"),
        (r"\bFLOAT\b", "REAL"),
        (r"\bDATE\b", "TEXT"),
        (r"\bTIMESTAMP\s*(\(\s*\d+\s*\))?\b", "TEXT"),
    ]
    for pat, repl in rules:
        create_sql = re.sub(pat, repl, create_sql, flags=re.IGNORECASE)
    return create_sql


def _normalize_values(sql):
    """把值层面常见的 Oracle 函数转成 SQLite 可执行的形式。"""
    # TO_DATE('2024-01-01','YYYY-MM-DD') -> '2024-01-01'
    sql = re.sub(
        r"TO_DATE\s*\(\s*('[^']*')\s*,\s*'[^']*'\s*\)",
        r"\1", sql, flags=re.IGNORECASE,
    )
    # SYSDATE / SYSTIMESTAMP -> 当前时间
    sql = re.sub(r"\bSYSDATE\b", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bSYSTIMESTAMP\b", "CURRENT_TIMESTAMP", sql, flags=re.IGNORECASE)
    return sql


def _normalize_statement(stmt):
    """对单条 SQL 做最佳努力的方言转换。"""
    if stmt.lstrip().upper().startswith("CREATE TABLE"):
        stmt = _normalize_types(stmt)
    return _normalize_values(stmt)


def _infer_create_table(conn, insert_sql):
    """INSERT 找不到目标表时，根据 INSERT 的列清单推断建表（全 TEXT）。"""
    m = re.match(
        r'INSERT\s+INTO\s+["\'`]?([A-Za-z0-9_$#]+)["\'`]?\s*'
        r'(?:\(([^)]*)\))?\s*VALUES',
        insert_sql, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        raise ValueError("无法从 INSERT 语句推断表结构，请确保 SQL 文件包含 CREATE TABLE 或带列清单的 INSERT。")
    table = m.group(1)
    cols_spec = m.group(2)
    if not cols_spec:
        raise ValueError(f"表 {table} 缺少列清单，无法推断结构，请补上 INSERT INTO {table}(col1, col2, ...)。")
    cols = [c.strip().strip('"').strip("'").strip("`") for c in cols_spec.split(",") if c.strip()]
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(f'CREATE TABLE "{table}" ({col_defs})')


# ===== 构建本地 SQLite 库 =====

def _build_db():
    """读取 SQL 文件并构建本地 SQLite 库，返回库文件路径。"""
    sql_path = Config.REAL_DATA_SQL_PATH
    if not sql_path or not os.path.exists(sql_path):
        raise FileNotFoundError(
            f"未找到真实数据 SQL 文件：{sql_path or '(未配置)'}。"
            f"请设置环境变量 REAL_DATA_SQL_PATH 指向 .sql 文件。"
        )

    db_path = Config.REAL_DATA_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # 缓存库比 SQL 文件新就直接复用，避免每次启动重建
    if os.path.exists(db_path) and os.path.getmtime(db_path) >= os.path.getmtime(sql_path):
        return db_path

    conn = sqlite3.connect(db_path)
    try:
        sql_text = _read_sql(sql_path)
        for stmt in _split_statements(sql_text):
            stmt = _normalize_statement(stmt)
            if not stmt.strip():
                continue
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower() and stmt.lstrip().upper().startswith("INSERT"):
                    _infer_create_table(conn, stmt)
                    conn.execute(stmt)
                else:
                    raise
        conn.commit()
    except Exception:
        # 构建失败时清掉半成品库，避免下次误用
        conn.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        raise
    conn.close()
    return db_path


def _ensure_db():
    """惰性构建 + 线程安全的单次构建。"""
    global _db_path
    if _db_path is not None:
        return _db_path
    with _build_lock:
        if _db_path is None:
            _db_path = _build_db()
        return _db_path


def _connect():
    """打开一个到本地 SQLite 库的短连接（每次查询独立，线程安全）。"""
    return sqlite3.connect(_ensure_db())


# ===== 元数据辅助 =====

def _list_table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def _resolve_table(table_name):
    """大小写不敏感地解析出库中真实表名。"""
    _validate_name(table_name)
    conn = _connect()
    try:
        for name in _list_table_names(conn):
            if name.upper() == table_name.upper():
                return name
    finally:
        conn.close()
    raise ValueError(f"表 '{table_name}' 不存在")


def _resolve_column(table_name, column_name):
    """大小写不敏感地解析出库中真实列名。"""
    actual_table = _resolve_table(table_name)
    conn = _connect()
    try:
        cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{actual_table}")').fetchall()]
    finally:
        conn.close()
    for c in cols:
        if c.upper() == column_name.upper():
            return c
    raise ValueError(f"列名 '{column_name}' 不存在于表 {table_name}")


def _parse_type_info(dtype):
    """从 SQLite 声明类型里解析 (归一化类型, 长度, 精度, 小数位)。"""
    dtype = (dtype or "").strip()
    if not dtype:
        return "TEXT", None, None, None
    base = re.sub(r"\(.*\)", "", dtype).strip().upper()
    m = re.match(r"(\w+)\s*\(\s*(\d+)(?:\s*,\s*(\d+))?\s*\)", dtype)
    length = precision = scale = None
    if m:
        precision = int(m.group(2))
        scale = int(m.group(3)) if m.group(3) is not None else None
        length = precision
    return base, length, precision, scale


def _is_date_column(name, dtype):
    """判断某列是否为日期/时间列（按列名或声明类型）。"""
    name = (name or "").upper()
    dtype = (dtype or "").upper()
    if any(k in name for k in ("DATE", "TIME")):
        return True
    return any(k in dtype for k in ("DATE", "TIME", "TIMESTAMP"))


def _to_iso(d):
    """把 date/datetime 转成 ISO 字符串，用于 SQLite 字符串比较。"""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _to_iso_end(d):
    """日期筛选的右开区间上界：date 类型加一天。"""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(d, date):
        return (d + timedelta(days=1)).isoformat()
    return str(d)


def _build_where(table_name, date_column, date_start, date_end):
    """构建日期筛选 WHERE 子句。返回 (where_sql, params)。"""
    if not date_column:
        return "", ()
    actual_col = _resolve_column(table_name, date_column)
    start_s = _to_iso(date_start)
    end_s = _to_iso_end(date_end)
    return f' WHERE "{actual_col}" >= ? AND "{actual_col}" < ?', (start_s, end_s)


# ===== 公共接口（与 db_oracle.py 签名一致）=====

def list_tables(search=None):
    conn = _connect()
    tables = []
    try:
        names = _list_table_names(conn)
        for name in names:
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            tables.append({
                "owner": _OWNER,
                "table_name": name,
                "num_rows": count,
                "last_analyzed": datetime.now(),
                "avg_row_len": 200,
            })
    finally:
        conn.close()

    if search and search.strip():
        s = search.upper().strip()
        tables = [t for t in tables if s in t["table_name"].upper()]
    tables.sort(key=lambda t: t["table_name"])
    return tables


def get_table_columns(owner, table_name):
    actual_table = _resolve_table(table_name)
    conn = _connect()
    result = []
    try:
        for cid, name, dtype, notnull, _dflt, _pk in conn.execute(
            f'PRAGMA table_info("{actual_table}")'
        ).fetchall():
            base, length, precision, scale = _parse_type_info(dtype)
            result.append({
                "column_name": name,
                "data_type": base,
                "data_length": length,
                "nullable": "N" if notnull else "Y",
                "column_id": cid + 1,
                "data_precision": precision,
                "data_scale": scale,
            })
    finally:
        conn.close()
    return result


def get_date_columns(owner, table_name):
    cols = get_table_columns(owner, table_name)
    return [c["column_name"] for c in cols if _is_date_column(c["column_name"], c["data_type"])]


def get_table_row_count(owner, table_name, date_column=None, date_start=None, date_end=None):
    actual_table = _resolve_table(table_name)
    where, params = _build_where(table_name, date_column, date_start, date_end)
    conn = _connect()
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{actual_table}"{where}', params).fetchone()[0]
    finally:
        conn.close()


def get_table_data(owner, table_name, limit=100, offset=0,
                   date_column=None, date_start=None, date_end=None):
    actual_table = _resolve_table(table_name)
    where, params = _build_where(table_name, date_column, date_start, date_end)

    order = ""
    if date_column:
        order = f' ORDER BY "{_resolve_column(table_name, date_column)}" DESC'

    sql = f'SELECT * FROM "{actual_table}"{where}{order} LIMIT ? OFFSET ?'
    conn = _connect()
    try:
        cur = conn.execute(sql, (*params, int(limit), int(offset)))
        columns = [d[0] for d in cur.description]
        rows = [tuple(r) for r in cur.fetchall()]
        return columns, rows
    finally:
        conn.close()


def stream_table_data(owner, table_name, chunk_size=None, offset=0, max_rows=None,
                      date_column=None, date_start=None, date_end=None):
    actual_table = _resolve_table(table_name)
    if chunk_size is None:
        chunk_size = Config.DOWNLOAD_CHUNK_SIZE
    if max_rows is None:
        max_rows = Config.MAX_DOWNLOAD_ROWS

    where, params = _build_where(table_name, date_column, date_start, date_end)
    order = ""
    if date_column:
        order = f' ORDER BY "{_resolve_column(table_name, date_column)}" DESC'

    sql = f'SELECT * FROM "{actual_table}"{where}{order} LIMIT ? OFFSET ?'
    conn = _connect()
    cur = conn.execute(sql, (*params, int(max_rows), int(offset)))
    columns = [d[0] for d in cur.description]
    yield columns
    total_rows = 0
    try:
        while True:
            batch = cur.fetchmany(chunk_size)
            if not batch:
                break
            total_rows += len(batch)
            if total_rows > Config.MAX_DOWNLOAD_ROWS:
                raise ValueError(
                    f"表行数超过下载上限（{Config.MAX_DOWNLOAD_ROWS:,} 行），"
                    f"请缩小日期范围或使用分片下载。")
            yield [tuple(r) for r in batch]
    finally:
        conn.close()


def estimate_row_size(owner, table_name, sample_rows=10):
    actual_table = _resolve_table(table_name)
    conn = _connect()
    try:
        rows = conn.execute(f'SELECT * FROM "{actual_table}" LIMIT ?', (int(sample_rows),)).fetchall()
        if not rows:
            return 200
        total_bytes = 0
        for row in rows:
            for val in row:
                if val is None:
                    total_bytes += 4
                elif isinstance(val, (int, float)):
                    total_bytes += 12
                elif isinstance(val, str):
                    total_bytes += len(val.encode("utf-8", errors="replace"))
                elif isinstance(val, bytes):
                    total_bytes += len(val)
                else:
                    total_bytes += len(str(val).encode("utf-8", errors="replace"))
        return total_bytes // len(rows)
    finally:
        conn.close()


def estimate_table_size_mb(owner, table_name, date_column=None, date_start=None, date_end=None):
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    if row_count == 0:
        return 0.0
    avg_bytes = estimate_row_size(owner, table_name)
    if avg_bytes == 0:
        avg_bytes = 200
    return round(row_count * avg_bytes * 2 / (1024 * 1024), 2)


def get_download_plan(owner, table_name, date_column=None, date_start=None, date_end=None):
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    est_size_mb = estimate_table_size_mb(owner, table_name, date_column, date_start, date_end)
    chunk_rows = Config.DOWNLOAD_SPLIT_CHUNK_ROWS

    plan = {
        "row_count": row_count, "est_size_mb": est_size_mb,
        "needs_split": False, "chunks": 0, "chunk_rows": chunk_rows,
        "warning_level": "safe", "warning_message": "",
    }

    if row_count > Config.DOWNLOAD_CONFIRM_ROWS or est_size_mb > Config.DOWNLOAD_SPLIT_SIZE_MB:
        plan["needs_split"] = True
        plan["chunks"] = max(1, (row_count + chunk_rows - 1) // chunk_rows)

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
