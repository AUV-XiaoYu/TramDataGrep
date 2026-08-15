"""
中文标签映射（集中管理）。

把英文的表名、列名、数据类型、常见枚举值统一映射成中文关键词，供模板层调用。
所有后端（oracle / demo_large / demo_real）共用同一份映射，避免到处硬编码。

用法：
    from labels import table_label, column_label, type_label, value_label

    table_label("DAILY_PASSENGER_FLOW")   # -> "每日客流统计"
    column_label("FLOW_DATE")             # -> "客流日期"
    type_label("VARCHAR2")                # -> "文本"

未收录的名称会原样返回（英文），这是有意设计的回退行为：
新增字段或表时不会报错，只是暂时显示英文，往对应字典里补一条即可。

映射键统一用大写，查询时也先转大写做不区分大小写匹配。
"""
import re

# ===== 表名 -> 中文 =====
TABLE_NAMES_ZH = {
    "DAILY_PASSENGER_FLOW": "每日客流统计",
    "TXN_TICKET_SALES": "票务销售交易明细",
    "CLEARING_DAILY": "每日清分结算",
    "ROUTE_OPERATION": "线路运营记录",
    "STATION_INFO": "站点基础信息",
    "VEHICLE_SCHEDULE": "车辆调度计划",
    "PASSENGER_FLOW_HOURLY": "小时级客流明细",
    "TXN_HISTORY_2024": "2024年交易归档",
}

# ===== 列名 -> 中文 =====
COLUMN_NAMES_ZH = {
    # 客流 / 清分通用
    "FLOW_DATE": "客流日期",
    "CLEARING_DATE": "清分日期",
    "OP_DATE": "运营日期",
    "TXN_DATE": "交易日期",
    "TXN_TIME": "交易时间",
    "SCHEDULE_DATE": "调度日期",
    "ARCHIVE_DATE": "归档日期",
    "CREATED_AT": "创建时间",
    "START_TIME": "开始时间",
    "END_TIME": "结束时间",
    "DEPARTURE_TIME": "发车时间",
    "ARRIVAL_TIME": "到达时间",
    # 线路 / 站点
    "LINE_NO": "线路号",
    "STATION_CODE": "站点编码",
    "STATION_NAME": "站点名称",
    "STATION_IN": "进站站点",
    "STATION_OUT": "出站站点",
    "STATION_ORDER": "站点顺序",
    "TRANSFER_LINES": "换乘线路",
    "DIRECTION": "方向",
    # 客流指标
    "BOARDING_COUNT": "上车人数",
    "ALIGHTING_COUNT": "下车人数",
    "TOTAL_TRANSACTIONS": "交易总数",
    "TOTAL_RIDES": "乘车总次数",
    "PASSENGER_COUNT": "乘客数",
    "HOUR_SLOT": "小时时段",
    # 票务 / 交易
    "TXN_ID": "交易ID",
    "CARD_NO": "卡号",
    "FARE_AMOUNT": "票价金额",
    "DISCOUNT_AMOUNT": "优惠金额",
    "TOTAL_FARE": "票价总额",
    "CASH_AMOUNT": "现金金额",
    "CARD_AMOUNT": "卡支付金额",
    "MOBILE_AMOUNT": "移动支付金额",
    "PAYMENT_TYPE": "支付方式",
    "SETTLEMENT_STATUS": "结算状态",
    "DEVICE_ID": "设备编号",
    "DATA_SOURCE": "数据来源",
    "AUDITED_BY": "审核人",
    # 车辆 / 调度
    "VEHICLE_ID": "车辆编号",
    "DRIVER_ID": "司机编号",
    "ASSIGNED_DRIVER": "指派司机",
    "SHIFT_NO": "班次号",
    "SCHEDULED_TRIPS": "计划班次",
    "ACTUAL_TRIPS": "实际班次",
    "DELAY_MINUTES": "延误分钟",
    # 站点地理
    "LATITUDE": "纬度",
    "LONGITUDE": "经度",
    # 其他
    "IS_ACTIVE": "是否启用",
    "STATUS": "状态",
    "REMARKS": "备注",
}

# ===== 常见枚举值 -> 中文 =====
VALUE_ZH = {
    "CASH": "现金",
    "CARD": "卡支付",
    "MOBILE": "移动支付",
    "QR": "二维码",
    "Y": "是",
    "N": "否",
}

# ===== 数据类型 -> 中文 =====
TYPE_ZH = {
    "VARCHAR2": "文本",
    "NVARCHAR2": "文本",
    "VARCHAR": "文本",
    "CHAR": "文本",
    "CLOB": "长文本",
    "TEXT": "文本",
    "NUMBER": "数字",
    "INTEGER": "整数",
    "INT": "整数",
    "FLOAT": "浮点数",
    "REAL": "浮点数",
    "DATE": "日期",
    "TIMESTAMP": "时间戳",
    "DATETIME": "时间",
    "BLOB": "二进制",
}


def _norm(name):
    """统一大写并去除首尾空白，用于查表。"""
    return (name or "").strip().upper()


def table_label(name):
    """表名 -> 中文，未收录则返回原名。"""
    key = _norm(name)
    return TABLE_NAMES_ZH.get(key, name)


def column_label(name):
    """列名 -> 中文，未收录则返回原名。"""
    key = _norm(name)
    return COLUMN_NAMES_ZH.get(key, name)


def value_label(value):
    """枚举值 -> 中文，未收录则返回原值。仅处理 str 类型。"""
    if not isinstance(value, str):
        return value
    key = _norm(value)
    return VALUE_ZH.get(key, value)


def type_label(data_type):
    """数据类型 -> 中文，未收录则返回原类型名。"""
    if not data_type:
        return ""
    # 去掉括号里的长度/精度，如 NUMBER(10,2) -> NUMBER
    base = re.sub(r"\(.*\)", "", str(data_type)).strip()
    return TYPE_ZH.get(_norm(base), data_type)
