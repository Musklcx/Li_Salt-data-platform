# -*- coding: utf-8 -*-
"""
水电汽消耗蓝图
--------------
- 库：data/db_balance.db（balance 表：1 天 1 行，含 14 个水电汽底数列）
- 页面：/utilities
- 接口：/api/utilities/all（日底数全量）、/api/export/utilities（Excel 导出）
- 口径：14 列均为累计表底读数（底数）。0 = 未抄表。
  日用量 = （当日有效底数 − 前日有效底数）× 电表倍率；两个有效底数之间的漏抄日按线性插值均摊，
  首个有效底数日无前值（用量为空）。插值不影响合计（合计只取决于首尾真实底数）。
  电表倍率见 COL_RATIO：车间总表 / 60t高压1·2 为 ×4000，30t高压 ×40，其余 ×1；
  蒸汽与水的表本身就是计量单位，倍率为 1。
"""
import os
import sqlite3
from datetime import datetime
from io import BytesIO
from flask import Blueprint, render_template, request, g, send_file
from openpyxl import Workbook

utilities_bp = Blueprint('utilities', __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'db_balance.db')

# 14 个水电汽底数列（与 balance 表列名一致）
ELEC_COLS = ["车间总电表", "60t高压电表1", "60t高压电表2", "30t高压电表",
             "沸腾床电表", "60t低压电表", "30t低压电表", "104总电表"]
STEAM_COLS = ["车间总蒸汽", "60t总蒸汽", "30t总蒸汽", "沸腾床蒸汽"]
WATER_COLS = ["自来水", "工业水"]
ALL_COLS = ELEC_COLS + STEAM_COLS + WATER_COLS

# 电表倍率：表上读数 × 倍率 = 实际电量（kWh）
# 库里存的是表上原始读数，倍率只在“读数差 → 用量”这一步乘进去，
# 所以「表底读数」口径显示的仍是抄表时看到的数字。
COL_RATIO = {
    "车间总电表": 4000,
    "60t高压电表1": 4000,
    "60t高压电表2": 4000,
    "30t高压电表": 40,
    "沸腾床电表": 1,
    "60t低压电表": 1,
    "30t低压电表": 1,
    "104总电表": 1,
}

METRICS = {
    "elec":  {"name": "用电", "unit": "kWh", "cols": ELEC_COLS},
    "steam": {"name": "蒸汽", "unit": "t",   "cols": STEAM_COLS},
    "water": {"name": "用水", "unit": "m³",  "cols": WATER_COLS},
}


# ---------- DB（沿用 inventory_bp 的独立连接范式） ----------
def get_db():
    if 'util_db' not in g:
        g.util_db = sqlite3.connect(DB_PATH, timeout=10)
        g.util_db.row_factory = sqlite3.Row
        g.util_db.execute('PRAGMA journal_mode=WAL')
        g.util_db.execute('PRAGMA busy_timeout=5000')
    return g.util_db


@utilities_bp.teardown_request
def close_db(exc=None):
    db = g.pop('util_db', None)
    if db is not None:
        db.close()


def parse_date(s):
    try:
        return datetime.strptime(str(s).strip(), "%Y/%m/%d")
    except (ValueError, TypeError):
        return None


def load_rows():
    """全量日记录：日期格式化为 YYYY/MM/DD，14 列数值化（NULL→0），按真实日期排序"""
    cols_sql = ",".join(f"[{c}]" for c in ALL_COLS)
    rows = get_db().execute(
        f"SELECT [日期],[碳酸锂金属量],{cols_sql} FROM [balance]"
    ).fetchall()
    out = []
    for r in rows:
        d = parse_date(r["日期"])
        if d is None:
            continue
        item = {"日期": d.strftime("%Y/%m/%d"), "碳酸锂金属量": float(r["碳酸锂金属量"] or 0)}
        for c in ALL_COLS:
            item[c] = float(r[c] if r[c] is not None else 0)
        out.append((d, item))
    out.sort(key=lambda x: x[0])
    return [item for _, item in out]


# ---------- 底数 → 有效底数/日用量（与前端 utilitiesScr.js 逻辑一致） ----------
def compute_eff(raw_series):
    """线性插值补齐中间漏抄日（0），返回 (有效底数列表, 插值标记列表)"""
    eff = list(raw_series)
    est = [False] * len(raw_series)
    first = next((i for i, v in enumerate(raw_series) if v > 0), None)
    if first is not None:
        last = first
        for i in range(first + 1, len(raw_series)):
            if raw_series[i] > 0:
                if i - last > 1:
                    step = (raw_series[i] - raw_series[last]) / (i - last)
                    for k in range(last + 1, i):
                        eff[k] = raw_series[last] + step * (k - last)
                        est[k] = True
                last = i
    return eff, est


def compute_usage_all(rows):
    """返回 (EFF, USAGE)：EFF[col][i]=插值后底数（表上读数）；USAGE[col][i]=日用量（已乘倍率，None=无前值）"""
    eff_map, usage_map = {}, {}
    n = len(rows)
    for col in ALL_COLS:
        ratio = COL_RATIO.get(col, 1)
        raw = [r[col] for r in rows]
        eff, _ = compute_eff(raw)
        eff_map[col] = eff
        usage = []
        for i in range(n):
            if eff[i] == 0:
                usage.append(0.0)
            elif i == 0 or eff[i - 1] == 0:
                usage.append(None)
            else:
                usage.append((eff[i] - eff[i - 1]) * ratio)
        usage_map[col] = usage
    return eff_map, usage_map


# ---------- 页面 ----------
@utilities_bp.route('/utilities')
def page_utilities():
    return render_template("utilities.html")


# ---------- 接口 ----------
@utilities_bp.route("/api/utilities/all")
def api_all():
    """日底数全量（前端自行计算插值与日用量）"""
    return {"code": 0, "msg": "ok", "data": load_rows()}


@utilities_bp.route("/api/export/utilities")
def api_export():
    """导出 Excel：key(elec/steam/water) + start/end + granularity(day/month) + mode(usage/reading)"""
    key = request.args.get("key", "elec")
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    granularity = request.args.get("granularity", "day")
    mode = request.args.get("mode", "usage")
    if key not in METRICS:
        key = "elec"
    cols = METRICS[key]["cols"]
    unit = METRICS[key]["unit"]

    rows = load_rows()
    eff_map, usage_map = compute_usage_all(rows)

    # 蒸汽展示口径：碳酸锂汽 = 车间总蒸汽 − 沸腾床蒸汽（与页面 cellVal 一致）
    if key == "steam":
        eff_map["车间总蒸汽"] = [a - b for a, b in zip(eff_map["车间总蒸汽"], eff_map["沸腾床蒸汽"])]
        usage_map["车间总蒸汽"] = [
            None if (u is None or v is None) else u - v
            for u, v in zip(usage_map["车间总蒸汽"], usage_map["沸腾床蒸汽"])
        ]

    start_dt = datetime.strptime(start, "%Y-%m-%d") if start else None
    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else None

    # 过滤（带原索引，便于取插值序列）
    filtered = []
    for i, r in enumerate(rows):
        d = parse_date(r["日期"])
        if start_dt and d < start_dt:
            continue
        if end_dt and d > end_dt:
            continue
        filtered.append((i, r))

    # 月聚合：用量按月累加；底数取当月最后一个有效底数
    if granularity == "month":
        agg = {}
        for i, r in filtered:
            m = r["日期"][:7]
            if m not in agg:
                agg[m] = {"last_idx": i, "usage": {c: 0.0 for c in cols}}
            for c in cols:
                v = usage_map[c][i]
                if v is not None:
                    agg[m]["usage"][c] += v
        records = []
        for m in sorted(agg):
            rec = {"日期": m}
            for c in cols:
                rec[c] = agg[m]["usage"][c] if mode == "usage" else eff_map[c][agg[m]["last_idx"]]
            records.append(rec)
    else:
        records = []
        for i, r in filtered:
            rec = {"日期": r["日期"]}
            for c in cols:
                rec[c] = usage_map[c][i] if mode == "usage" else eff_map[c][i]
            records.append(rec)

    # 生成 xlsx（车间总蒸汽展示名：碳酸锂汽）
    DISPLAY = {"车间总蒸汽": "碳酸锂汽"}
    if mode == "usage":
        headers = ["日期"] + [f"{DISPLAY.get(c, c)}({unit})" for c in cols]
    else:
        headers = ["日期"] + [f"{DISPLAY.get(c, c)}(表读数)" for c in cols]
    wb = Workbook()
    ws = wb.active
    ws.title = key
    ws.append(headers)
    for rec in records:
        row_vals = [rec["日期"]]
        for c in cols:
            v = rec[c]
            row_vals.append("" if v is None else round(float(v), 2))
        ws.append(row_vals)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    mode_text = "日用量" if mode == "usage" else "底数"
    g_text = "按月" if granularity == "month" else "按日"
    fname = f"水电汽_{METRICS[key]['name']}_{start or 'all'}_{end or 'all'}_{g_text}_{mode_text}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
