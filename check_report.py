# -*- coding: utf-8 -*-
"""
每日数据核对卡片生成（check_report.py）
----------------------------------------
纯本地生成，不做任何推送（钉钉 / 微信通道已全部移除）。

流程：
  1. 数据日期 = 昨天（当天录入的是前一天的数据）
  2. 取 data_103 昨日记录
  3. 数据日【全空】（无记录）或【全 0】（核对字段全为 0）→ 当天跳过，不生成
  4. 按固定倒班规律（6 天周期）判定当日白班/夜班班组
  5. 生成【图片】核对卡片，保存到桌面（自己用微信发）

用法：
  python check_report.py                # 生成图片到桌面
  python check_report.py --date 2026-10-11   # 指定数据日期（测试用）
"""
import argparse
import datetime
import logging
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data", "db_day.db")

# 保存目录：固定为管理员桌面（计划任务 SYSTEM 身份运行时也能写对位置）
SAVE_DIR = "C:/Users/Administrator/Desktop"
if not os.path.isdir(SAVE_DIR):
    SAVE_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
if not os.path.isdir(SAVE_DIR):
    SAVE_DIR = BASE_DIR

# 倒班规律：6 天周期，10/2 起循环（甲=周期起点，乙 +2 天，丙 +4 天）
CYCLES = {
    "甲": ["夜", "夜", "休", "休", "白", "白"],
    "乙": ["白", "白", "夜", "夜", "休", "休"],
    "丙": ["休", "休", "白", "白", "夜", "夜"],
}
CYCLE_START = datetime.date(2026, 10, 2)  # 该日为甲班周期第 0 天（夜）

# 核对字段（碳酸钠仓库出库 + 硫酸钠四料）
CHECK_FIELDS = ["碳酸钠仓库出库", "硫酸钠干料", "硫酸钠湿料", "硫酸钠杂质料", "硫酸钠落地料"]

# 日志
LOG_FILE = os.path.join(BASE_DIR, "logs", "check.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("check_report")


def shifts_of(d):
    """返回 {班组: 班次}，任意日恰为 1 白 + 1 夜 + 1 休"""
    idx = (d - CYCLE_START).days % 6
    return {name: CYCLES[name][idx] for name in CYCLES}


def fmt_num(v):
    """数字规整：None/空 → 0；去掉多余的 .0"""
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0
    if f == int(f):
        return int(f)
    return round(f, 2)


def load_day_rows(date_str):
    """读某数据日全部班组记录，返回 list[dict]"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.execute(
            "SELECT * FROM data_103 WHERE 日期 = ? ORDER BY 班组", [date_str]
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def is_all_empty(rows):
    """全空：数据日无任何记录"""
    return len(rows) == 0


def is_all_zero(rows):
    """全 0：核对字段在全部班组记录里合计为 0"""
    total = sum(fmt_num(r.get(f)) for r in rows for f in CHECK_FIELDS)
    return total == 0


def collect(data_date, rows, shifts):
    """汇总生成所需数据"""
    na_out = sum(fmt_num(r.get("碳酸钠仓库出库")) for r in rows)
    day_shift_name = next(n for n, s in shifts.items() if s == "白")
    night_shift_name = next(n for n, s in shifts.items() if s == "夜")
    rest_name = next(n for n, s in shifts.items() if s == "休")

    def sulfate_block(name):
        row = next(r for r in rows if r.get("班组") == name)
        return {
            f: fmt_num(row.get(f))
            for f in ["硫酸钠干料", "硫酸钠湿料", "硫酸钠杂质料", "硫酸钠落地料"]
        }

    return {
        "day_name": data_date.strftime("%m/%d"),
        "na_out": na_out,
        "day_shift": day_shift_name,
        "night_shift": night_shift_name,
        "rest": rest_name,
        "day_vals": sulfate_block(day_shift_name),
        "night_vals": sulfate_block(night_shift_name),
    }


def render_image(c, out_path):
    """卡片图片（大数字清单型），保存 PNG"""
    from PIL import Image, ImageDraw, ImageFont

    W, PAD = 750, 44

    def font(size, bold=True):
        for name in (
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ):
            if os.path.exists(name):
                return ImageFont.truetype(name, size)
        return ImageFont.load_default()

    H = PAD + 52 + 44 + 30 + 44 + 92 + 40 + 24 + 166 + 24 + 166 + 24 + 60 + PAD
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    y = PAD

    d.text((PAD, y), f"{c['day_name']} 数据核对清单", font=font(36), fill="#1A1B1C")
    y += 58
    d.text((PAD, y), "昨日数据 · 请与仓库核对", font=font(19, False), fill="#8A8F99")
    y += 46
    d.line([(PAD, y), (W - PAD, y)], fill="#EEEEEE", width=2)
    y += 32

    # 碳酸钠仓库出库（大数字）
    d.text((PAD, y), "碳酸钠仓库出库", font=font(22, False), fill="#1A1B1C")
    y += 46
    num = str(c["na_out"])
    num_w = d.textbbox((0, 0), num, font=font(54))[2]
    d.text((PAD, y), num, font=font(54), fill="#205493")
    d.text((PAD + num_w + 12, y + 32), "t", font=font(22, False), fill="#8A8F99")
    y += 96

    # 硫酸钠组标题
    d.text((PAD, y), "硫酸钠", font=font(24, True), fill="#1A1B1C")
    y += 40

    def draw_block(block_y, title, title_color, bg, vals):
        x0, x1 = PAD, W - PAD
        d.rounded_rectangle([x0, block_y, x1, block_y + 166], radius=16, fill=bg)
        d.text((x0 + 22, block_y + 18), title, font=font(23), fill=title_color)
        gy = block_y + 62
        gap = 12
        cell_w = (x1 - x0 - 2 * 22 - 3 * gap) // 4
        for i, (label, key) in enumerate(
            [("干料", "硫酸钠干料"), ("湿料", "硫酸钠湿料"),
             ("杂质", "硫酸钠杂质料"), ("落地", "硫酸钠落地料")]
        ):
            cx = x0 + 22 + i * (cell_w + gap)
            d.text((cx, gy), label, font=font(17, False), fill="#8A8F99")
            d.text((cx, gy + 30), str(vals[key]), font=font(36), fill="#1A1B1C")

    draw_block(y, f"白班 · {c['day_shift']}班", "#205493", "#EFF6FB", c["day_vals"])
    y += 166 + 24
    draw_block(y, f"夜班 · {c['night_shift']}班", "#4F46A5", "#F3F1FD", c["night_vals"])
    y += 166 + 24

    d.text((PAD, y), f"{c['rest']}班今日休息 · 数据为昨日录入 · 有差异请当日修正",
           font=font(18, False), fill="#9CA3AF")

    img.save(out_path, "PNG")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="每日数据核对卡片生成（本地保存）")
    parser.add_argument("--date", help="指定数据日期 YYYY-MM-DD（默认昨天）")
    args = parser.parse_args()

    today = datetime.date.today()
    if args.date:
        data_date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        data_date = today - datetime.timedelta(days=1)

    date_str = data_date.strftime("%Y/%m/%d")
    print(f"数据日期：{date_str}（今天 {today}）")

    rows = load_day_rows(date_str)

    # 规则：全空 或 全 0 → 当天不生成
    if is_all_empty(rows):
        log.info("跳过：%s 无记录（全空）", date_str)
        print(f"跳过：{date_str} 无记录（全空），不生成")
        return 0
    if is_all_zero(rows):
        log.info("跳过：%s 核对字段全 0", date_str)
        print(f"跳过：{date_str} 核对字段全 0，不生成")
        return 0

    shifts = shifts_of(data_date)
    print("班次：", shifts)
    c = collect(data_date, rows, shifts)

    tag = data_date.strftime("%m-%d")
    img_path = os.path.join(SAVE_DIR, f"数据核对_{tag}.png")
    render_image(c, img_path)
    log.info("已生成：%s", img_path)
    print(f"已保存：{img_path}")


if __name__ == "__main__":
    sys.exit(main())
