# -*- coding: utf-8 -*-
"""
db_balance.balance 水电汽 14 列体检 + 空值补零（Excel 原件已删除，以库内数据为准）

1. 14 个水电汽列 NULL -> 0
2. 体检报告：各列首个有效底数日期、零段分布、读数下降点（疑似漏录/异常）
"""
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # workweb 根目录
DB = os.path.join(BASE, "data", "db_balance.db")

NEW_COLS = [
    "车间总电表", "60t高压电表1", "60t高压电表2", "30t高压电表",
    "沸腾床电表", "60t低压电表", "30t低压电表", "104总电表",
    "车间总蒸汽", "60t总蒸汽", "30t总蒸汽", "沸腾床蒸汽",
    "自来水", "工业水",
]

def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1) 空值补 0
    filled = 0
    for col in NEW_COLS:
        cur.execute(f"UPDATE balance SET [{col}]=0 WHERE [{col}] IS NULL")
        filled += cur.rowcount
    con.commit()
    print(f"空值补 0：{filled} 个单元格")

    # 2) 体检
    rows = cur.execute(
        "SELECT 日期," + ",".join(f"[{c}]" for c in NEW_COLS) +
        " FROM balance ORDER BY 日期"
    ).fetchall()
    print(f"总行数：{len(rows)}")

    dates = [r[0] for r in rows]
    for i, col in enumerate(NEW_COLS, start=1):
        vals = [r[i] for r in rows]
        first = next((dates[j] for j, v in enumerate(vals) if v and v > 0), None)
        # 中间零段（首个有效日期之后的 0）
        zeros_after = []
        if first:
            fi = dates.index(first)
            zeros_after = [dates[j] for j in range(fi + 1, len(vals)) if not vals[j]]
        # 下降点（非零递减，疑似异常；忽略跨零段）
        drops = []
        for j in range(1, len(vals)):
            if vals[j] and vals[j-1] and vals[j] < vals[j-1]:
                drops.append((dates[j], vals[j-1], vals[j]))
        status = f"首值 {first or '无'}"
        if zeros_after:
            status += f" · 中间零值 {len(zeros_after)} 天: {','.join(zeros_after[:6])}{'...' if len(zeros_after)>6 else ''}"
        if drops:
            status += f" · 下降点 {len(drops)} 处: {drops[:3]}"
        print(f"  {col:<10} {status}")

    con.close()
    print("\n完成。")

if __name__ == "__main__":
    main()
