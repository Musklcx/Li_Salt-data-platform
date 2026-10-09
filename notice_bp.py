# -*- coding: utf-8 -*-
"""
班组工作量（通知公示）蓝图
--------------------------
- 页面：/notice
- 接口：/api/notice/list（明细表格）、/api/notice/sum（班组汇总卡片）
数据访问统一走 db.py（主库 db_day.db）
"""
from flask import Blueprint, request, render_template
from db import query
from resp import ok

notice_bp = Blueprint('notice', __name__)


@notice_bp.route('/notice')
def page_notice():
    return render_template("notice.html")


@notice_bp.route("/api/notice/list")
def api_notice_list():
    """明细表格数据：年月 + 班组筛选"""
    month_str = request.args.get("month")
    banzu = request.args.get("banzu", "全部")
    year, mon = month_str.split("-")
    year_val = year
    mon_val = str(int(mon))  # 09 → 9，适配数据库 2026/9/1 不带前导零

    sql_base = """
    SELECT
        日期,
        班组,
        `碳酸锂车间产出`,
        `硫酸钠`,
        `去蒸发前液处理量`,
        `合成前液处理量`,
        `压滤机卸渣量`,
        `蒸发冷凝水`,
        `碳酸钠车间消耗`,
        `投活性炭、除氟剂量`,
        `产出锂渣`,
        `回投锂渣`,
        `镍渣`,
        `104返镁液`,
        `104废液`,
        `外排水量`,
        `钴渣量`,
        `清合成釜`,
        `更换滤布`
    FROM data_103
    WHERE
    substr(日期,1,instr(日期,'/')-1) = ?
    AND substr(日期,instr(日期,'/')+1, instr(substr(日期,instr(日期,'/')+1),'/')-1) = ?
    """
    params = [year_val, mon_val]
    if banzu != "全部":
        sql_base += " AND 班组 = ? "
        params.append(banzu)
    return ok(query(sql_base, params))


@notice_bp.route("/api/notice/sum")
def api_notice_sum():
    """按月聚合，甲、乙、丙各班汇总产量，用于顶部卡片"""
    month_str = request.args.get("month")
    year, mon = month_str.split("-")
    year_val = year
    mon_val = str(int(mon))

    rows = query("""
    SELECT
        班组,
        SUM(`碳酸锂车间产出`) AS sum_li,
        SUM(`硫酸钠`) AS sum_na
    FROM data_103
    WHERE
    substr(日期,1,instr(日期,'/')-1) = ?
    AND substr(日期,instr(日期,'/')+1, instr(substr(日期,instr(日期,'/')+1),'/')-1) = ?
    GROUP BY 班组
    """, [year_val, mon_val])

    out = {"甲": {"sum_li": 0, "sum_na": 0}, "乙": {"sum_li": 0, "sum_na": 0}, "丙": {"sum_li": 0, "sum_na": 0}}
    for r in rows:
        bz = r["班组"]
        if bz in out:
            out[bz]["sum_li"] = float(r["sum_li"] or 0)
            out[bz]["sum_na"] = float(r["sum_na"] or 0)
    return ok(out)
