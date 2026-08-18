"""
Oracle 数据库连接与查询模块
使用 oracledb thin 模式，无需安装 Oracle Instant Client

核心设计：运行时 Schema Discovery（内省）
- 不需要预先知道表结构
- 通过 Oracle 元数据表（ALL_TABLES、ALL_TAB_COLUMNS）动态发现

支持的日期筛选：date_column + date_start/date_end 参数
- date_column 必须是表中实际存在的列名（安全校验）
- 构建参数化 WHERE 子句，防止 SQL 注入
"""
import re
import oracledb
from config import Config

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(
            user=Config.ORACLE_USER, password=Config.ORACLE_PASSWORD,
            dsn=Config.ORACLE_DSN, min=2, max=10, increment=1,
            config_dir=Config.ORACLE_CONFIG_DIR,
        )
    return _pool


_VALID_NAME = re.compile(r"^[A-Za-z0-9_$#]+$")

_SYSTEM_SCHEMAS = {
    "SYS", "SYSTEM", "XDB", "MDSYS", "CTXSYS", "ORDSYS",
    "WMSYS", "OUTLN", "DBSNMP", "APPQOSSYS", "GSMADMIN_INTERNAL",
    "DBSFWUSER", "REMOTE_SCHEDULER_AGENT", "OJVMSYS", "OLAPSYS",
    "ORDDATA", "ORDPLUGINS", "SI_INFORMTN_SCHEMA", "SQLTXPLAIN",
    "XS$NULL", "GSMCATUSER", "MDDATA", "SYSBACKUP", "SYSDG",
    "SYSKM", "SYSRAC", "AUDSYS", "DVF", "DVSYS", "LBACSYS",
}


def _validate_name(name):
    if not _VALID_NAME.match(name):
        raise ValueError(f"无效的名称: {name}")


def _validate_column_name(owner, table_name, column_name):
    """校验列名是否真实存在于表中（防 SQL 注入）"""
    cols = get_table_columns(owner, table_name)
    valid_names = {c["column_name"].upper() for c in cols}
    if column_name.upper() not in valid_names:
        raise ValueError(f"列名 '{column_name}' 不存在于表 {owner}.{table_name}")


def _build_where_clause(owner, table_name, date_column, date_start, date_end, params):
    """构建安全的日期筛选 WHERE 子句。返回 WHERE 字符串，同时修改 params dict。

    仅当 date_column 与起止时间都给出时才筛选；只给 date_column（用于排序）时返回空
    WHERE，避免把 None 绑定到 :date_start/:date_end。
    """
    if not date_column or date_start is None or date_end is None:
        return ""
    _validate_column_name(owner, table_name, date_column)
    params["date_start"] = date_start
    params["date_end"] = date_end
    return f' WHERE "{date_column.upper()}" BETWEEN :date_start AND :date_end'


def _build_excluded_schemas():
    excluded = set(_SYSTEM_SCHEMAS)
    for s in Config.EXTRA_EXCLUDED_SCHEMAS:
        excluded.add(s.upper())
    return excluded


def _apply_table_filter(sql, params):
    patterns = Config.TABLE_FILTER_PATTERNS
    if not patterns:
        return sql, params
    mode = Config.TABLE_FILTER_MODE
    clauses = []
    for i, pat in enumerate(patterns):
        pn = f"filter_{i}"
        clauses.append(f"UPPER(table_name) LIKE :{pn}")
        params[pn] = pat.upper().replace("*", "%")
    if mode == "whitelist":
        sql += f" AND ({' OR '.join(clauses)})"
    elif mode == "blacklist":
        sql += f" AND NOT ({' OR '.join(clauses)})"
    return sql, params


# ===== 查询函数 =====

def list_tables(search=None):
    pool = get_pool()
    excluded = _build_excluded_schemas()
    sql = """
        SELECT owner, table_name, num_rows, last_analyzed, avg_row_len
        FROM all_tables
        WHERE owner NOT IN ({})
    """.format(",".join(f"'{s}'" for s in excluded))
    params = {}
    sql, params = _apply_table_filter(sql, params)
    if search and search.strip():
        sql += " AND UPPER(table_name) LIKE :search"
        params["search"] = f"%{search.upper().strip()}%"
    sql += " ORDER BY owner, table_name"
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [{"owner": r[0], "table_name": r[1], "num_rows": r[2],
                     "last_analyzed": r[3], "avg_row_len": r[4]} for r in rows]


def get_table_columns(owner, table_name):
    _validate_name(owner)
    _validate_name(table_name)
    pool = get_pool()
    sql = """
        SELECT column_name, data_type, data_length, nullable, column_id,
               data_precision, data_scale
        FROM all_tab_columns
        WHERE owner = :owner AND table_name = :table_name
        ORDER BY column_id
    """
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"owner": owner.upper(), "table_name": table_name.upper()})
            rows = cur.fetchall()
            return [{"column_name": r[0], "data_type": r[1], "data_length": r[2],
                     "nullable": r[3], "column_id": r[4],
                     "data_precision": r[5], "data_scale": r[6]} for r in rows]


def get_date_columns(owner, table_name):
    """返回表中 DATE 或 TIMESTAMP 类型的列名列表"""
    cols = get_table_columns(owner, table_name)
    return [c["column_name"] for c in cols if c["data_type"] in ("DATE", "TIMESTAMP")]


def get_table_row_count(owner, table_name, date_column=None, date_start=None, date_end=None):
    """获取表行数（支持日期筛选）"""
    _validate_name(owner)
    _validate_name(table_name)
    pool = get_pool()

    params = {}
    where = _build_where_clause(owner, table_name, date_column, date_start, date_end, params)

    # 先尝试统计值（仅在无日期筛选时）
    if not where:
        with pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT num_rows FROM all_tables WHERE owner = :o AND table_name = :t",
                    {"o": owner.upper(), "t": table_name.upper()})
                row = cur.fetchone()
                if row and row[0] is not None:
                    return row[0]

    # 精确 COUNT(*)
    sql = f'SELECT COUNT(*) FROM "{owner.upper()}"."{table_name.upper()}"{where}'
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]


def get_table_data(owner, table_name, limit=100, offset=0,
                   date_column=None, date_start=None, date_end=None):
    """分页获取表数据"""
    _validate_name(owner)
    _validate_name(table_name)
    pool = get_pool()

    params = {}
    where = _build_where_clause(owner, table_name, date_column, date_start, date_end, params)

    # 有日期筛选时按日期列降序排列（最新在前）
    order_by = ""
    if date_column:
        order_by = f' ORDER BY "{date_column.upper()}" DESC'

    sql = (f'SELECT * FROM "{owner.upper()}"."{table_name.upper()}"{where}'
           f"{order_by}"
           f" OFFSET {int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY")

    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return columns, rows


def stream_table_data(owner, table_name, chunk_size=None, offset=0, max_rows=None,
                      date_column=None, date_start=None, date_end=None):
    """流式生成表数据"""
    _validate_name(owner)
    _validate_name(table_name)
    if chunk_size is None:
        chunk_size = Config.DOWNLOAD_CHUNK_SIZE
    if max_rows is None:
        max_rows = Config.MAX_DOWNLOAD_ROWS

    pool = get_pool()
    params = {}
    where = _build_where_clause(owner, table_name, date_column, date_start, date_end, params)

    sql = f'SELECT * FROM "{owner.upper()}"."{table_name.upper()}"{where}'
    if offset > 0:
        sql += f" OFFSET {int(offset)} ROWS"
    sql += f" FETCH NEXT {int(max_rows)} ROWS ONLY"

    _check_memory_before_download(owner, table_name, date_column, date_start, date_end)

    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.arraysize = chunk_size
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            yield columns
            total_rows = 0
            while True:
                batch = cur.fetchmany(chunk_size)
                if not batch:
                    break
                total_rows += len(batch)
                if total_rows > Config.MAX_DOWNLOAD_ROWS:
                    raise ValueError(
                        f"表行数超过下载上限（{Config.MAX_DOWNLOAD_ROWS:,} 行），"
                        f"请缩小日期范围或使用分片下载。")
                yield batch


def _check_memory_before_download(owner, table_name, date_column=None, date_start=None, date_end=None):
    try:
        import psutil
        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024 * 1024)
        est_size_mb = estimate_table_size_mb(owner, table_name, date_column, date_start, date_end)
        if est_size_mb > 0 and est_size_mb > available_mb * Config.MAX_DOWNLOAD_MEMORY_RATIO:
            raise ValueError(
                f"预计下载文件大小 {est_size_mb:.0f} MB 超过服务器可用内存的 60%，"
                f"请使用分片下载（每片 {Config.DOWNLOAD_SPLIT_CHUNK_ROWS:,} 行）。")
    except ImportError:
        pass


def estimate_row_size(owner, table_name, sample_rows=10):
    _validate_name(owner)
    _validate_name(table_name)
    pool = get_pool()
    sql = (f'SELECT * FROM "{owner.upper()}"."{table_name.upper()}"'
           f" WHERE ROWNUM <= {int(sample_rows)}")
    with pool.acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
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


def estimate_table_size_mb(owner, table_name, date_column=None, date_start=None, date_end=None):
    row_count = get_table_row_count(owner, table_name, date_column, date_start, date_end)
    if row_count == 0:
        return 0.0
    avg_bytes = estimate_row_size(owner, table_name)
    if avg_bytes == 0:
        avg_bytes = 200
    return round(row_count * avg_bytes * 2 / (1024 * 1024), 2)


def get_download_plan(owner, table_name, date_column=None, date_start=None, date_end=None):
    """返回下载方案建议。修复：blocked 表也计算分片。"""
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