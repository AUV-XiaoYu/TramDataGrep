"""
用户认证模块
使用 SQLite 存储用户，Flask-Login 管理会话
"""
import sqlite3
from datetime import datetime
from functools import wraps

from flask import redirect, url_for, flash, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "请先登录再访问此页面。"


# ===== User 模型 =====

class User(UserMixin):
    """Flask-Login 用户模型"""

    def __init__(self, row):
        # 兼容 sqlite3.Row 和普通 dict
        def _get(key, default=None):
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        self.id = row["id"]
        self.username = row["username"]
        self.password_hash = row["password_hash"]
        self.display_name = _get("display_name") or row["username"]
        self.is_admin = bool(_get("is_admin", 0))
        self.is_active_user = bool(_get("is_active", 1))
        self.created_at = _get("created_at", "")

    @property
    def is_active(self):
        """Flask-Login 需要此属性判断账号是否可用"""
        return self.is_active_user

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    """根据 user_id 加载用户对象"""
    row = _get_user_by_id(user_id)
    if row:
        return User(row)
    return None


# ===== SQLite 数据库操作 =====

def _get_db():
    """获取 SQLite 连接"""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化用户表并创建默认管理员"""
    import os
    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)

    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            password_hash   TEXT    NOT NULL,
            display_name    TEXT    NOT NULL DEFAULT '',
            is_admin        INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            last_login      TEXT
        )
    """)
    conn.commit()

    # 创建默认管理员
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (Config.DEFAULT_ADMIN_USERNAME,),
    ).fetchone()

    if not existing:
        pw_hash = generate_password_hash(Config.DEFAULT_ADMIN_PASSWORD)
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?, ?, ?, 1)",
            (Config.DEFAULT_ADMIN_USERNAME, pw_hash, "系统管理员"),
        )
        conn.commit()
        print(f"[初始化] 已创建默认管理员账号: {Config.DEFAULT_ADMIN_USERNAME}")
        print(f"[初始化] 默认密码: {Config.DEFAULT_ADMIN_PASSWORD}")
        print(f"[初始化] 请登录后立即修改密码！")

    conn.close()


def _get_user_by_id(user_id):
    """根据 ID 获取用户"""
    conn = _get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
    finally:
        conn.close()


def _get_user_by_username(username):
    """根据用户名获取用户"""
    conn = _get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    finally:
        conn.close()


def get_all_users():
    """获取所有用户列表（管理员用）"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY is_admin DESC, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_user(username, password, display_name="", is_admin=False):
    """创建新用户"""
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return False, "用户名已存在"

        pw_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?, ?, ?, ?)",
            (username, pw_hash, display_name or username, 1 if is_admin else 0),
        )
        conn.commit()
        return True, "用户创建成功"
    finally:
        conn.close()


def delete_user(user_id):
    """软删除用户（标记为不活跃）"""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?", (int(user_id),)
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def reset_user_password(user_id, new_password):
    """重置用户密码"""
    conn = _get_db()
    try:
        pw_hash = generate_password_hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pw_hash, int(user_id)),
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def change_password(user_id, old_password, new_password):
    """修改自己的密码"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
        if not row:
            return False, "用户不存在"

        if not check_password_hash(row["password_hash"], old_password):
            return False, "原密码错误"

        pw_hash = generate_password_hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pw_hash, int(user_id)),
        )
        conn.commit()
        return True, "密码修改成功"
    finally:
        conn.close()


def toggle_user_active(user_id):
    """切换用户激活状态"""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT is_active FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
        if not row:
            return False, "用户不存在"

        new_status = 0 if row["is_active"] else 1
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (new_status, int(user_id)),
        )
        conn.commit()
        return True, "已启用" if new_status else "已禁用"
    finally:
        conn.close()


def record_login(user_id):
    """记录用户登录时间"""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE users SET last_login = datetime('now','localtime') WHERE id = ?",
            (int(user_id),),
        )
        conn.commit()
    finally:
        conn.close()


# ===== 权限装饰器 =====

def admin_required(f):
    """要求管理员权限的装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated