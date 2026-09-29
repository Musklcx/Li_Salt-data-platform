# -*- coding: utf-8 -*-
"""
数据对比蓝图
------------
- 页面：/data
- 接口：/api/output/all（data_103 按日聚合）、/api/plan/get（月度计划）
数据访问统一走 db.py（主库 db_day.db）
"""
from datetime import datetime
from flask import Blueprint, jsonify, request, render_template
from db import query, fetchone

data_bp = Blueprint('data', __name__)


def format_date(s):
    """原始字符串 2026/9/1 → 2026/09/01"""
    if not s:
        return ""
    s = s.strip()
    fmt = "%Y/%m/%d"
    try:
        dt = datetime.strptime(s, fmt)
        return dt.strftime("%Y/%m/%d")
    except ValueError:
        pass
    return s


def parse_raw_date(s):
    """把原始日期字符串转为 datetime，用于排序"""
    s = s.strip()
    fmt = "%Y/%m/%d"
    try:
        return datetime.strptime(s, fmt)
    except ValueError:
        pass
    return None


@data_bp.route('/data')
def page_data():
    return render_template("data.html")


@data_bp.route("/api/output/all")
def api_all():
    rows = query('''
    SELECT
    日期 AS raw_date,
    SUM(碳酸锂仓库出库) AS 碳酸锂仓库出库,
    SUM(碳酸锂车间产出) AS 碳酸锂车间产出,
    SUM(硫酸钠) AS 硫酸钠,
    SUM(硫酸钠干料) AS 硫酸钠干料,
    SUM(硫酸钠湿料) AS 硫酸钠湿料,
    SUM(硫酸钠杂质料) AS 硫酸钠杂质料,
    SUM(硫酸钠落地料) AS 硫酸钠落地料,
    SUM(碳酸钠车间消耗) AS 碳酸钠车间消耗,
    SUM(碳酸钠仓库出库) AS 碳酸钠仓库出库,
    SUM(外排水量) AS 外排水量
    FROM data_103
    GROUP BY raw_date
    ''')

    temp = []
    for d in rows:
        dt_obj = parse_raw_date(d["raw_date"])
        temp.append({"dt_obj": dt_obj, "raw": d})

    # 按真实时间排序，空时间排最后
    temp.sort(key=lambda x: x["dt_obj"] if x["dt_obj"] else datetime.max)

    res = []
    for item in temp:
        raw_row = item["raw"]
        out = {
            "日期": format_date(raw_row["raw_date"]),
            "碳酸锂仓库出库": raw_row["碳酸锂仓库出库"],
            "碳酸锂车间产出": raw_row["碳酸锂车间产出"],
            "硫酸钠": raw_row["硫酸钠"],
            "硫酸钠干料": raw_row["硫酸钠干料"],
            "硫酸钠湿料": raw_row["硫酸钠湿料"],
            "硫酸钠杂质料": raw_row["硫酸钠杂质料"],
            "硫酸钠落地料": raw_row["硫酸钠落地料"],
            "碳酸钠车间消耗": raw_row["碳酸钠车间消耗"],
            "碳酸钠仓库出库": raw_row["碳酸钠仓库出库"],
            "外排水量": raw_row["外排水量"]
        }
        res.append(out)
    return jsonify(res)


@data_bp.route("/api/plan/get")
def api_plan_get():
    """读取month_plan月度计划表，前端参数 yyyy-mm"""
    month_str = request.args.get("month")  # 例如 "2026-09"
    # 把 "2026-09" 转成 "2026年9月"，匹配数据库month_plan表的月份字段
    year, mon = month_str.split("-")
    # 去掉月份前面的0，09 →9，数据库是"2026年9月"不是"2026年09月"
    mon_int = int(mon)
    db_month_text = f"{year}年{mon_int}月"

    row = fetchone("SELECT 碳酸锂,硫酸钠 FROM month_plan WHERE 月份 = ?", [db_month_text])
    if row is None:
        return jsonify({"碳酸锂": 0, "硫酸钠": 0})
    return jsonify({
        "碳酸锂": float(row["碳酸锂"]),
        "硫酸钠": float(row["硫酸钠"])
    })
