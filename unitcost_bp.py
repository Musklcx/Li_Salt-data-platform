# -*- coding: utf-8 -*-
"""
辅料包材单耗蓝图
----------------
- 库：data/db_day.db（主库，连接走 db.py 的 get_db，与数据对比页同源）
- 页面：/unitcost
- 接口：/api/unitcost/all（月度汇总，前端做展示层派生）
        /api/export/unitcost（Excel 导出）

数据来源与口径
--------------
辅料（data_103，1 天 3 个班组各 1 行）：
    103硫酸 / 103液碱 / 活性炭 / 除氟剂 / 碳酸钠车间消耗
    → 按日汇总 3 班组 → 按月累计
    → 月单耗 = 月消耗 ÷ 月碳酸锂产量（碳酸锂车间产出）

辅材（month_plan，本身就是月度数，无需累计）：
    碳酸锂包装 · 滤布 · 渣袋 ÷ 碳酸锂产量；硫酸钠包装 ÷ 硫酸钠产量

换算系数：
    硫酸、液碱在库里记的是体积（m³），吨位 = 体积 × 密度：
    硫酸 ×1.84、液碱 ×1.35。系数只影响「消耗量 / 单耗」，
    不改库、也不影响任何原始数据口径。

派生指标（在前端算，规则见 unitcostScr.js）：
    环比     = 本月单耗 ÷ 上月单耗 − 1
    年均单耗 = 本年累计消耗 ÷ 本年累计产量（加权，只统计两项都有值的月份）
    状态     = 较年均 +25% 超耗 / +10% 偏高 / −10% 节约（库中暂无单耗目标表）
"""
import os
import re
from datetime import datetime
from io import BytesIO

from flask import Blueprint, render_template, request, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from db import get_db

unitcost_bp = Blueprint('unitcost', __name__)

# ---------- 数据列定义 ----------
# data_103 里参与计算的列（按班组累计）
AUX_SRC = {
    "硫酸":   "103硫酸",
    "液碱":   "103液碱",
    "活性炭": "活性炭",
    "除氟剂": "除氟剂",
    "碳酸钠": "碳酸钠车间消耗",
}
# 产出列
LI_COL, NA_COL = "碳酸锂车间产出", "硫酸钠"
NA4_COLS = ["硫酸钠干料", "硫酸钠湿料", "硫酸钠杂质料", "硫酸钠落地料"]

# month_plan 里的辅材列（月度数，直接取）
MAT_KEYS = ["碳酸锂包装", "硫酸钠包装", "滤布", "渣袋"]

# 体积 → 吨 的换算系数（其余物料视为已是吨/条/片，系数 1）
FACTOR = {"硫酸": 1.84, "液碱": 1.35}

# 单耗基准：÷ 碳酸锂产量 / ÷ 硫酸钠产量
BASE = {
    "硫酸": "li", "液碱": "li", "活性炭": "li", "除氟剂": "li", "碳酸钠": "li",
    "碳酸锂包装": "li", "硫酸钠包装": "na", "滤布": "li", "渣袋": "li",
}
UNIT = {
    "硫酸": "t", "液碱": "t", "活性炭": "t", "除氟剂": "t", "碳酸钠": "t",
    "碳酸锂包装": "条", "硫酸钠包装": "条", "滤布": "片", "渣袋": "条",
}
GROUP = {
    "硫酸": "aux", "液碱": "aux", "活性炭": "aux", "除氟剂": "aux", "碳酸钠": "aux",
    "碳酸锂包装": "mat", "硫酸钠包装": "mat", "滤布": "mat", "渣袋": "mat",
}


# ---------- 工具 ----------
def num(v):
    """宽松数值化：None / '' / '0' / '1,234.5' / 带单位文本 都能吃"""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else 0.0


def parse_ym(s):
    """'2026/1/1' '2026-01-01' '2026年10月' → (2026, 1)"""
    m = re.match(r"\s*(\d{4})\D+(\d{1,2})", str(s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def ym_key(k):
    return "%04d-%02d" % k


def load_monthly():
    """按月汇总 data_103（辅料+产量），并挂上 month_plan 的辅材月消耗与计划量"""
    db = get_db()

    cols = list(AUX_SRC.values()) + [LI_COL, NA_COL] + NA4_COLS
    sql = "SELECT [日期],[班组],%s FROM [data_103]" % ",".join(f"[{c}]" for c in cols)

    agg = {}
    for r in db.execute(sql).fetchall():
        k = parse_ym(r["日期"])
        if k is None:
            continue
        a = agg.setdefault(k, {"aux": {x: 0.0 for x in AUX_SRC}, "days": set(), "rows": 0,
                               "li": 0.0, "na": 0.0, "na4": 0.0})
        a["days"].add(str(r["日期"]).strip())
        a["rows"] += 1
        for key, col in AUX_SRC.items():
            a["aux"][key] += num(r[col])
        a["li"] += num(r[LI_COL])
        a["na"] += num(r[NA_COL])
        for c in NA4_COLS:
            a["na4"] += num(r[c])

    # month_plan：计划量 + 辅材消耗
    plan = {}
    try:
        for r in db.execute("SELECT * FROM [month_plan]").fetchall():
            k = parse_ym(r["月份"])
            if k is None:
                continue
            d = {"liPlan": num(r["碳酸锂"]), "naPlan": num(r["硫酸钠"])}
            for key in MAT_KEYS:
                d[key] = None if r[key] is None or str(r[key]).strip() == "" else num(r[key])
            plan[k] = d
    except Exception:  # 老库没有这 4 列时降级（不阻塞页面）
        plan = {}

    rows = []
    for k in sorted(agg):
        a = agg[k]
        p = plan.get(k, {})
        rows.append({
            "m": ym_key(k),
            "li": round(a["li"], 2),
            "na": round(a["na"], 2),
            "na4": round(a["na4"], 2),
            "liPlan": round(float(p.get("liPlan") or 0), 2),
            "naPlan": round(float(p.get("naPlan") or 0), 2),
            "aux": {x: round(v, 2) for x, v in a["aux"].items()},
            "mat": {key: (None if p.get(key) is None else round(float(p[key]), 2)) for key in MAT_KEYS},
            "days": len(a["days"]),
            "rows": a["rows"],
        })
    return rows


def all_items():
    return list(AUX_SRC) + MAT_KEYS


# ---------- 页面 ----------
@unitcost_bp.route('/unitcost')
def page_unitcost():
    return render_template("unitcost.html")


# ---------- 接口 ----------
@unitcost_bp.route("/api/unitcost/all")
def api_all():
    try:
        rows = load_monthly()
    except Exception as e:
        return {"code": 1, "msg": "读取月度数据失败：%s" % e, "data": None}, 500
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "rows": rows,
            "items": [
                {"key": k, "grp": GROUP[k], "unit": UNIT[k], "base": BASE[k],
                 "factor": FACTOR.get(k, 1)}
                for k in all_items()
            ],
        },
    }


@unitcost_bp.route("/api/export/unitcost")
def api_export():
    """导出：月份为行，每个物料两列（消耗量 / 单耗），口径与页面完全一致"""
    rows = load_monthly()
    view = request.args.get("view", "aux")
    keys = [k for k in all_items() if GROUP[k] == view] if view in ("aux", "mat") else all_items()

    wb = Workbook()
    ws = wb.active
    ws.title = "辅料" if view == "aux" else ("辅材" if view == "mat" else "全部")

    # 表头：两行（第一行物料分组，第二行消耗量/单耗）
    head1 = ["月份", "碳酸锂产量(t)", "", "碳酸锂计划(t)", "", "硫酸钠产量(t)", "", "硫酸钠计划(t)", ""]
    head2 = ["", "实际", "计划完成", "计划", "环比", "实际", "", "计划", ""]
    for k in keys:
        head1 += [k, ""]
        head2 += ["消耗量(%s)" % UNIT[k], "单耗(%s/t)" % UNIT[k]]
    ws.append(head1)
    ws.append(head2)

    fill = PatternFill("solid", fgColor="205493")
    for row in ws.iter_rows(min_row=1, max_row=2):
        for c in row:
            c.font = Font(color="FFFFFF", bold=True, size=10)
            c.fill = fill
            c.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    for i in range(len(keys)):
        c0 = 10 + i * 2
        ws.merge_cells(start_row=1, start_column=c0, end_row=1, end_column=c0 + 1)

    prev = None
    for r in rows:
        vals = [r["m"], r["li"], "", r["liPlan"], "", r["na"], "", r["naPlan"], ""]
        for k in keys:
            q = r["aux"].get(k) if GROUP[k] == "aux" else r["mat"].get(k)
            q = None if q is None else q * FACTOR.get(k, 1)
            base = r[BASE[k]] or 0
            u = (q / base) if (q is not None and base) else None
            vals += [None if q is None else round(q, 2), None if u is None else round(u, 4)]
        ws.append(vals)
        prev = r

    # 列宽 + 冻结
    ws.column_dimensions["A"].width = 11
    for i in range(2, 10):
        ws.column_dimensions[get_column_letter(i)].width = 13
    for i in range(len(keys) * 2):
        ws.column_dimensions[get_column_letter(10 + i)].width = 14
    ws.freeze_panes = "B3"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = "辅料包材单耗_%s_%s.xlsx" % ({"aux": "辅料", "mat": "辅材"}.get(view, "全部"),
                                     datetime.now().strftime("%Y%m%d"))
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
