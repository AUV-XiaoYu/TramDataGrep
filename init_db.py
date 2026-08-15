"""
初始化用户数据库（首次运行或重置时使用）
可直接运行: python init_db.py
"""
from auth import init_db

if __name__ == "__main__":
    print("=" * 50)
    print("  电车票务数据平台 - 用户数据库初始化")
    print("=" * 50)
    init_db()
    print("初始化完成。")