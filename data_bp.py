# -*- coding: utf-8 -*-
"""
数据对比蓝图
------------
- 页面：/data
- 接口：/api/output/all（data_103 按日聚合）、/api/plan/get（月度计划）
- 导出：/api/export/output（Excel，openpyxl 生成 xlsx）
数据访问统一走 db.py（主库 db_day.db）
"""
from datetime import datetime
from io import BytesIO
from flask import Blueprint, request, render_template, send_file
from openpyxl import Workbook
from db import query, fetchone
from resp import ok

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
    
    """数据对比页面"""
    return render_template("data.html")


@data_bp.route("/api/output/all")
def api_all():
    
    """日聚合数据（按指标返回全部日记录）"""
    return ok(get_all_rows())


def get_all_rows():
    """日聚合数据（与前端 dataScr.js 的原始数据一致，已排序、日期格式 2026/09/01）"""
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
    return res


# 各指标导出列配置：{key: (表头列表, 字段列表)}
EXPORT_COLUMNS = {
    "lithium": (["日期", "碳酸锂车间产出", "碳酸锂仓库出库"],
                ["日期", "碳酸锂车间产出", "碳酸锂仓库出库"]),
    "sodiumSulfate": (["日期", "硫酸钠日累计", "干料", "湿料", "杂质料", "落地料"],
                      ["日期", "硫酸钠", "硫酸钠干料", "硫酸钠湿料", "硫酸钠杂质料", "硫酸钠落地料"]),
    "sodiumCarbonate": (["日期", "碳酸钠车间消耗", "碳酸钠仓库出库", "碳酸钠/碳酸锂消耗比"],
                        ["日期", "碳酸钠车间消耗", "碳酸钠仓库出库", "ratio_na_li"]),
    "drain": (["日期", "外排水量"],
              ["日期", "外排水量"]),
}


@data_bp.route("/api/export/output")
def api_export_output():
    """导出 Excel：按指标 key + 日期范围(start~end 含) + 粒度(day/month) 生成 xlsx"""
    key = request.args.get("key", "lithium")
    start = request.args.get("start", "")   # 2026-08-31
    end = request.args.get("end", "")       # 2026-09-30
    granularity = request.args.get("granularity", "day")

    headers, fields = EXPORT_COLUMNS.get(key, EXPORT_COLUMNS["lithium"])
    rows = get_all_rows()

    # 1) 按日期范围过滤（与前端 filterByDate 一致：start 含、end 含）
    def dt_of(dstr):
        try:
            return datetime.strptime(dstr, "%Y/%m/%d")
        except (ValueError, TypeError):
            return None

    start_dt = datetime.strptime(start, "%Y-%m-%d") if start else None
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else None

    filtered = []
    for r in rows:
        d = dt_of(r["日期"])
        if d is None:
            continue
        if start_dt and d < start_dt:
            continue
        if end_dt and d > end_dt:
            continue
        filtered.append(r)

    # 2) 按月聚合（与前端 groupByMonth 逻辑一致）
    if granularity == "month":
        agg = {}
        for r in filtered:
            m = r["日期"][:7]  # "2026/09/01"[:7] → "2026/09"
            if m not in agg:
                agg[m] = dict(r)
                agg[m]["日期"] = m
            else:
                for f in fields:
                    if f == "日期" or f == "ratio_na_li":
                        continue
                    agg[m][f] = float(agg[m].get(f) or 0) + float(r.get(f) or 0)
        # 碳酸钠消耗比：加总后 = 消耗 / 产出
        for m in agg:
            li_out = float(agg[m].get("碳酸锂车间产出") or 0)
            na_con = float(agg[m].get("碳酸钠车间消耗") or 0)
            agg[m]["ratio_na_li"] = round(na_con / li_out, 2) if li_out > 0 else 0
        filtered = list(agg.values())

    # 3) openpyxl 生成 xlsx
    wb = Workbook()
    ws = wb.active
    ws.title = key
    ws.append(headers)
    for r in filtered:
        row_vals = []
        for f in fields:
            v = r.get(f)
            if f == "ratio_na_li":
                row_vals.append(round(float(v or 0), 2))
            elif f == "日期":
                row_vals.append(v or "")
            else:
                row_vals.append(round(float(v or 0), 2))
        ws.append(row_vals)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"产量数据_{key}_{start or 'all'}_{end or 'all'}_{granularity}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
        return ok({"碳酸锂": 0, "硫酸钠": 0})
    return ok({
        "碳酸锂": float(row["碳酸锂"]),
        "硫酸钠": float(row["硫酸钠"])
    })
