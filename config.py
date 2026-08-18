"""
电车票务数据平台 - 配置文件
通过环境变量覆盖默认值，适合不同机器部署
"""
import os
import secrets
import json


def _parse_list_env(env_name, default):
    """解析环境变量中的 JSON 数组，例如 '["TXN%","DAILY%"]'"""
    val = os.environ.get(env_name)
    if val:
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return default


def _resolve_backend():
    """解析数据后端：oracle | demo_large | demo_real。向后兼容旧的 DEMO_MODE 布尔开关。"""
    val = os.environ.get("DATA_BACKEND", "").strip().lower()
    if val in ("oracle", "demo_large", "demo_real"):
        return val
    if os.environ.get("DEMO_MODE") == "1":
        return "demo_large"
    return "oracle"


class Config:
    # ===== Flask 安全配置 =====
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # ===== Oracle 数据库连接 =====
    ORACLE_USER = os.environ.get("ORACLE_USER", "tram")
    ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "tram123")
    ORACLE_DSN = os.environ.get("ORACLE_DSN", "localhost:1521/ORCL")
    ORACLE_CONFIG_DIR = os.environ.get("ORACLE_CONFIG_DIR") or None

    # ===== SQLite 用户数据库 =====
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    DATABASE = os.path.join(_base_dir, "instance", "users.db")

    # ===== 会话配置 =====
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 28800  # 8 小时

    # ===== 数据后端（oracle / demo_large / demo_real） =====
    # 由 DATA_BACKEND 环境变量选择；未设置时向后兼容旧的 DEMO_MODE 布尔开关。
    DATA_BACKEND = _resolve_backend()

    # ===== 演示模式（已由 DATA_BACKEND 取代，保留仅为向后兼容） =====
    DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"

    # ===== 真实数据模式（从 SQL 或 CSV 文件构建本地 SQLite 库） =====
    REAL_DATA_SQL_PATH = os.environ.get("REAL_DATA_SQL_PATH") or None
    # 未指定 SQL 文件时，回退到 CSV 文件（默认用项目内的 7.10.csv 作为固定测试数据）
    REAL_DATA_CSV_PATH = os.environ.get("REAL_DATA_CSV_PATH") or os.path.join(
        _base_dir, "7.10.csv"
    )
    REAL_DATA_DB_PATH = os.environ.get("REAL_DATA_DB_PATH") or os.path.join(
        _base_dir, "instance", "real_data.db"
    )
    REAL_DATA_OWNER = os.environ.get("REAL_DATA_OWNER", "TRAM")

    # ===== 表过滤配置 =====
    # 模式: "all"（列出所有表）、"whitelist"（仅显示匹配的表）、"blacklist"（排除匹配的表）
    TABLE_FILTER_MODE = os.environ.get("TABLE_FILTER_MODE", "all")

    # 白名单/黑名单模式下的表名匹配模式（Oracle LIKE 语法，支持 % 通配符）
    # 例如: ["TXN%", "DAILY%", "PASSENGER_FLOW", "TICKET_%"]
    # 可通过环境变量设置: set TABLE_FILTER_PATTERNS='["TXN%","DAILY%"]'
    TABLE_FILTER_PATTERNS = _parse_list_env("TABLE_FILTER_PATTERNS", [])

    # 可额外排除的 Schema 名称（在系统 Schema 过滤之后）
    EXTRA_EXCLUDED_SCHEMAS = _parse_list_env("EXTRA_EXCLUDED_SCHEMAS", [])

    # ===== 数据预览与下载限制 =====
    MAX_PREVIEW_ROWS = int(os.environ.get("MAX_PREVIEW_ROWS", "100"))
    DOWNLOAD_CHUNK_SIZE = int(os.environ.get("DOWNLOAD_CHUNK_SIZE", "1000"))

    # ---- 下载安全阈值 ----
    # 当表行数超过此值，前端显示"大表"警告（黄色），但允许下载
    DOWNLOAD_WARN_ROWS = int(os.environ.get("DOWNLOAD_WARN_ROWS", "100000"))

    # 当表行数超过此值，前端显示"超大表"警告（红色），需确认后才能下载
    DOWNLOAD_CONFIRM_ROWS = int(os.environ.get("DOWNLOAD_CONFIRM_ROWS", "500000"))

    # 单次下载行数上限（硬限制，超过拒绝）
    MAX_DOWNLOAD_ROWS = int(os.environ.get("MAX_DOWNLOAD_ROWS", str(5_000_000)))

    # 预计文件大小超过此值(MB)时，建议分片下载
    DOWNLOAD_SPLIT_SIZE_MB = int(os.environ.get("DOWNLOAD_SPLIT_SIZE_MB", "100"))

    # 分片下载每片行数
    DOWNLOAD_SPLIT_CHUNK_ROWS = int(os.environ.get("DOWNLOAD_SPLIT_CHUNK_ROWS", "500000"))

    # 服务器可用内存低于此比例时，拒绝大表下载
    MIN_FREE_MEMORY_RATIO = float(os.environ.get("MIN_FREE_MEMORY_RATIO", "0.15"))

    # 预计文件大小超过可用内存的比例时拒绝下载
    MAX_DOWNLOAD_MEMORY_RATIO = float(os.environ.get("MAX_DOWNLOAD_MEMORY_RATIO", "0.6"))

    # ===== 默认管理员账号（仅首次初始化时使用） =====
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "Admin@tram2026"


# ===== 硬件探明（启动时运行一次） =====

_diagnostics_cache = None


def get_hardware_info():
    """探明当前机器的硬件能力，结果缓存"""
    global _diagnostics_cache
    if _diagnostics_cache is not None:
        return _diagnostics_cache

    info = {
        "total_memory_mb": 0,
        "available_memory_mb": 0,
        "cpu_count": 0,
        "python_version": "",
        "safe_download_rows": Config.MAX_DOWNLOAD_ROWS,
        "safe_download_size_mb": 0,
    }

    # 尝试获取系统内存信息（psutil 为可选依赖）
    try:
        import psutil
        mem = psutil.virtual_memory()
        info["total_memory_mb"] = round(mem.total / (1024 * 1024))
        info["available_memory_mb"] = round(mem.available / (1024 * 1024))
        info["cpu_count"] = psutil.cpu_count(logical=False) or 1
        # 安全下载大小 = 可用内存 × 60%，保守估计 Excel 膨胀系数 2x
        safe_mem = info["available_memory_mb"] * Config.MAX_DOWNLOAD_MEMORY_RATIO
        info["safe_download_size_mb"] = round(safe_mem / 2)
        info["safe_download_rows"] = _estimate_safe_rows(info["safe_download_size_mb"])
    except ImportError:
        # 无 psutil 时用保守默认值
        info["safe_download_size_mb"] = 256
        info["safe_download_rows"] = 500_000

    info["python_version"] = __import__("sys").version.split()[0]

    _diagnostics_cache = info
    return info


def _estimate_safe_rows(safe_size_mb):
    """根据安全文件大小反推行数（假设平均每行 200 字节）"""
    avg_row_bytes = 200
    return int(safe_size_mb * 1024 * 1024 / avg_row_bytes)
