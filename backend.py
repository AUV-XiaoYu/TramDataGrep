"""
数据后端选择器。

三个后端（oracle / demo_large / demo_real）实现完全一致的函数接口，
app.py 通过本模块的 get_backend() 获取当前后端模块，避免在 app.py 里写 if/elif。

    from backend import get_backend
    db = get_backend()          # 返回 db_oracle / db_demo / db_sqlfile 之一
    db.list_tables(...)

新增后端时，只需在 get_backend() 里加一个分支即可，其余代码不用动。
"""
from config import Config


def get_backend():
    """根据 Config.DATA_BACKEND 返回对应的数据访问模块。"""
    mode = Config.DATA_BACKEND
    if mode == "demo_large":
        import db_demo as mod
    elif mode == "demo_real":
        import db_sqlfile as mod
    else:  # "oracle"
        import db_oracle as mod
    return mod
