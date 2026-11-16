# -*- coding: utf-8 -*-
"""
图表事件标注维护工具（后台手工录入）
------------------------------------
维护 db_day.db 的 chart_event 表，data 界面图表会自动渲染成：
  异常 → 红色图钉(markPoint，钉在当天数据点上)
  检修 → 黄色色带(markArea，铺在开始~结束日期区间)
  变更 → 紫色虚线(markLine，画在当天)

用法（在本目录上级，即 workweb/ 下执行）：
  python tools/chart_event.py list                    # 列出全部事件
  python tools/chart_event.py list lithium            # 只看某指标的事件
  python tools/chart_event.py add lithium 异常 2026/11/2 --note "原料管堵塞"
  python tools/chart_event.py add lithium 检修 2026/10/22 --end 2026/10/24 --note "年度检修"
  python tools/chart_event.py add lithium 变更 2026/11/1 --note "启用新工艺参数"
  python tools/chart_event.py edit 3 --note "改成新的说明"
  python tools/chart_event.py edit 3 --start 2026/11/3 --end 2026/11/5
  python tools/chart_event.py del 3
"""
import os
import sys
import sqlite3
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, 'data', 'db_day.db')

METRICS = {
    'lithium': '碳酸锂', 'sodiumSulfate': '硫酸钠', 'sodiumCarbonate': '碳酸钠',
    'lithiumSale': '硫酸锂', 'drain': '外排水',
}
# 各指标的曲线（系列）列表：异常图钉可指定钉在哪条线上（单曲线指标不用选）
SERIES = {
    'lithium': ['碳酸锂车间产出', '碳酸锂仓库出库'],
    'sodiumSulfate': ['硫酸钠干料', '硫酸钠湿料', '硫酸钠杂质料', '硫酸钠落地料'],
    'sodiumCarbonate': ['碳酸钠车间消耗', '碳酸钠仓库出库'],
    'lithiumSale': ['外卖硫酸锂'],
    'drain': ['外排水量'],
}
TYPES = {'异常': '红色图钉', '检修': '黄色色带', '变更': '紫色虚线'}


def norm_date(s):
    """2026/11/2、2026/11/02、2026-11-2 都接受，统一存成 2026/11/02"""
    s = s.strip().replace('-', '/')
    try:
        return datetime.strptime(s, "%Y/%m/%d").strftime("%Y/%m/%d")
    except ValueError:
        raise SystemExit(f"[错误] 日期格式不对：{s}（应像 2026/11/2 这样）")


def get_db():
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def ensure_table(con):
    con.execute('''CREATE TABLE IF NOT EXISTS chart_event (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        指标 TEXT NOT NULL,
        类型 TEXT NOT NULL,
        开始日期 TEXT NOT NULL,
        结束日期 TEXT,
        说明 TEXT NOT NULL)''')


def cmd_list(args):
    con = get_db(); ensure_table(con)
    if args.metric and args.metric not in METRICS:
        raise SystemExit(f"[错误] 指标只能是：{' / '.join(METRICS)}")
    sql = "SELECT * FROM chart_event"
    params = []
    if args.metric:
        sql += " WHERE 指标 = ?"; params.append(args.metric)
    rows = con.execute(sql + " ORDER BY ID", params).fetchall()
    if not rows:
        print("（无事件）"); return
    print(f"{'ID':<4}{'指标':<14}{'类型':<6}{'开始日期':<12}{'结束日期':<12}{'曲线':<18}说明")
    print("-" * 86)
    for r in rows:
        m = METRICS.get(r['指标'], r['指标'])
        end = r['结束日期'] or '—'
        ser = r['系列名'] or '（默认第一条线）'
        print(f"{r['ID']:<4}{m:<14}{r['类型']:<6}{r['开始日期']:<12}{end:<12}{ser:<18}{r['说明']}")
    con.close()


def cmd_add(args):
    if args.metric not in METRICS:
        raise SystemExit(f"[错误] 指标只能是：{' / '.join(METRICS)}")
    if args.type not in TYPES:
        types_hint = "、".join(t + "(" + TYPES[t] + ")" for t in TYPES)
        raise SystemExit(f"[错误] 类型只能是：{types_hint}")
    if not args.note or not args.note.strip():
        raise SystemExit("[错误] 必须写 --note \"事件说明\"")
    start = norm_date(args.start)
    end = norm_date(args.end) if args.end else None
    if args.type == '检修' and not end:
        raise SystemExit("[错误] 类型为「检修」时必须给 --end 结束日期（色带是区间事件）")
    if args.type == '异常' and end:
        raise SystemExit("[提示] 类型为「异常」是单日图钉，不需要 --end；区间请用「检修」")
    if args.series and args.metric in SERIES and args.series not in SERIES[args.metric]:
        raise SystemExit(f"[错误] 指标 {METRICS[args.metric]} 的曲线只能是：{' / '.join(SERIES[args.metric])}")
    if args.metric in SERIES and len(SERIES[args.metric]) == 1 and args.series:
        raise SystemExit(f"[提示] {METRICS[args.metric]} 只有一条曲线，不需要 --series")
    con = get_db(); ensure_table(con)
    cur = con.execute(
        "INSERT INTO chart_event (指标, 类型, 开始日期, 结束日期, 说明, 系列名) VALUES (?,?,?,?,?,?)",
        [args.metric, args.type, start, end, args.note.strip(), args.series])
    con.commit()
    print(f"[完成] 已添加事件 ID={cur.lastrowid}：{METRICS[args.metric]} {args.type} {start}" +
          (f" ~ {end}" if end else "") + f"  {args.note.strip()}")
    print("刷新 data 界面即可看到（按日粒度显示，按月聚合时自动隐藏）")
    con.close()


def cmd_edit(args):
    con = get_db(); ensure_table(con)
    row = con.execute("SELECT * FROM chart_event WHERE ID = ?", [args.id]).fetchone()
    if not row:
        raise SystemExit(f"[错误] 找不到 ID={args.id} 的事件，先用 list 查看现有 ID")
    fields, params = [], []
    if args.metric:
        if args.metric not in METRICS:
            raise SystemExit(f"[错误] 指标只能是：{' / '.join(METRICS)}")
        fields.append("指标 = ?"); params.append(args.metric)
    if args.type:
        if args.type not in TYPES:
            raise SystemExit(f"[错误] 类型只能是：{' / '.join(TYPES)}")
        fields.append("类型 = ?"); params.append(args.type)
    if args.start:
        fields.append("开始日期 = ?"); params.append(norm_date(args.start))
    if args.end:
        fields.append("结束日期 = ?"); params.append(norm_date(args.end))
    if args.note:
        fields.append("说明 = ?"); params.append(args.note.strip())
    if args.series is not None:
        metric_now = args.metric or row['指标']
        if args.series.strip():  # 空串 = 清除，恢复默认第一条线
            if metric_now in SERIES and args.series not in SERIES[metric_now]:
                raise SystemExit(f"[错误] 指标 {METRICS.get(metric_now, metric_now)} 的曲线只能是：{' / '.join(SERIES[metric_now])}")
            fields.append("系列名 = ?"); params.append(args.series.strip())
        else:
            fields.append("系列名 = ?"); params.append(None)
    if not fields:
        raise SystemExit("[错误] edit 至少要改一项：--metric / --type / --start / --end / --note / --series")
    params.append(args.id)
    con.execute(f"UPDATE chart_event SET {', '.join(fields)} WHERE ID = ?", params)
    con.commit()
    new = con.execute("SELECT * FROM chart_event WHERE ID = ?", [args.id]).fetchone()
    print(f"[完成] 已修改 ID={args.id}：{new['指标']} {new['类型']} {new['开始日期']}" +
          (f" ~ {new['结束日期']}" if new['结束日期'] else "") + f"  {new['说明']}")
    con.close()


def cmd_del(args):
    con = get_db(); ensure_table(con)
    row = con.execute("SELECT * FROM chart_event WHERE ID = ?", [args.id]).fetchone()
    if not row:
        raise SystemExit(f"[错误] 找不到 ID={args.id} 的事件")
    con.execute("DELETE FROM chart_event WHERE ID = ?", [args.id])
    con.commit()
    print(f"[完成] 已删除 ID={args.id}：{row['指标']} {row['类型']} {row['开始日期']}  {row['说明']}")
    con.close()


def main():
    p = argparse.ArgumentParser(description="图表事件标注维护工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出事件（可带指标过滤）")
    p_list.add_argument("metric", nargs="?", default=None)
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="新增事件")
    p_add.add_argument("metric", help="指标：%s" % " / ".join(METRICS))
    p_add.add_argument("type", help="类型：%s" % " / ".join(TYPES))
    p_add.add_argument("start", help="开始日期，如 2026/11/2")
    p_add.add_argument("--end", default=None, help="结束日期（仅「检修」色带需要）")
    p_add.add_argument("--note", required=True, help="事件说明（原因）")
    p_add.add_argument("--series", default=None, help="图钉钉在哪条曲线上（多曲线指标可选，默认第一条线）")
    p_add.set_defaults(func=cmd_add)

    p_edit = sub.add_parser("edit", help="按 ID 修改事件")
    p_edit.add_argument("id", type=int, help="事件 ID（list 查看）")
    p_edit.add_argument("--metric", default=None)
    p_edit.add_argument("--type", default=None)
    p_edit.add_argument("--start", default=None)
    p_edit.add_argument("--end", default=None)
    p_edit.add_argument("--note", default=None)
    p_edit.add_argument("--series", default=None, help="曲线名；传空串 \"\" 表示恢复默认第一条线")
    p_edit.set_defaults(func=cmd_edit)

    p_del = sub.add_parser("del", help="按 ID 删除事件")
    p_del.add_argument("id", type=int, help="事件 ID（list 查看）")
    p_del.set_defaults(func=cmd_del)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
