# -*- coding: utf-8 -*-
"""
data_103 绩效考核数据导入工具（覆盖版）
========================================
工作 web 项目日期规范：所有日级日期统一为 YYYY/MM/DD 补零格式（如 2026/10/27）。
本工具在写库前完成归一化，保证与页面显示、跨库对齐口径一致。

改动记录（相对旧版）：
  1. 写库日期统一补零：f"{y}/{m}/{d}" → YYYY/MM/DD（旧版写入 2026/10/27 会变成 2026/10/27 不补零，
     是全库日期格式混乱的源头之一）
  2. 单日覆盖的 DELETE 条件使用补零日期（旧版用不补零日期串删除，迁移后旧记录一条都删不掉，
     再追加就是重复行）
  3. 修复隐患：日期输入解析失败时旧版会静默落入"全量追加"模式，现在明确报错退出
  4. 输入弹窗提示与确认弹窗文案同步更新

使用：python tools/import_data103.py  （Excel 路径在下方配置项修改）
"""
import pandas as pd
import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import simpledialog, messagebox

# -------------------------- 配置项 --------------------------
EXCEL_PATH = r'C:\Users\Administrator\Desktop\103绩效考核.xlsx'
DB_PATH = r'D:\MyWork\Flask\Workweb\workweb\data\db_day.db'
SHEET_NAME = 'data'
TABLE_NAME = 'data_103'

# 红色主题
THEME_COLOR = "#D9001B"
THEME_TITLE = "🔴 data_103 绩效考核数据导入"

col_map = {
    "日期": "日期",
    "班组": "班组",
    # 旧 Excel 表头兼容：库列已于 2026/11/12 由 活性炭渣 改名 除氟剂渣
    "活性炭渣": "除氟剂渣",
    # 需要映射的其他列在这里加
}
# -------------------------------------------------------------

def fmt_date(dt):
    """统一输出补零日期 YYYY/MM/DD（项目唯一标准格式）"""
    return "%04d/%02d/%02d" % (dt.year, dt.month, dt.day)


def read_excel_safely(path, sheet_name):
    try:
        return pd.read_excel(path, sheet_name=sheet_name, engine='openpyxl')
    except Exception as e:
        print(f"❌ 读取 Excel 失败: {e}")
        return None

def connect_db_safely(db_path):
    try:
        return sqlite3.connect(db_path)
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return None

def get_table_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    cols = [row[1] for row in cur.fetchall()]
    cur.close()
    return cols

def normalize_columns(df):
    new_cols = [str(c).strip().replace('\n','').replace('\r','').replace(' ','') for c in df.columns]
    df.columns = new_cols
    return df

def parse_input_date(input_str):
    """解析用户输入的日期，支持 2026/10/27、2026-10-27、2026.10.27、2026年10月27日、10/27。
    解析失败返回 None（由调用方报错，绝不静默降级为全量导入）。"""
    if not input_str or str(input_str).strip() == "":
        return None
    s = str(input_str).strip()
    for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y年%m月%d日"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        m, d = map(int, s.split('/'))
        return datetime(datetime.now().year, m, d)
    except Exception:
        pass
    return None

# ========== 自定义彩色输入弹窗 ==========
def ask_date_with_color_label(color, big_title):
    win = tk.Toplevel()
    win.title(big_title)
    win.geometry("460x230")
    win.resizable(False, False)
    win.grab_set()

    tk.Label(win, text=big_title, fg=color, font=("微软雅黑", 16, "bold")).pack(pady=15)
    tk.Label(win, text="请输入要导入的日期（示例：2026/10/27，不补零也没关系）\n留空直接确定 = 全量追加（自动按 日期+班组 去重）",
             font=("微软雅黑", 10)).pack(pady=5)

    entry = tk.Entry(win, font=("微软雅黑", 12), justify="center", width=24)
    entry.pack(pady=10)
    entry.focus_set()

    result = {"value": None}
    def on_ok():
        result["value"] = entry.get()
        win.destroy()
    def on_cancel():
        result["value"] = None
        win.destroy()

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=8)
    tk.Button(btn_frame, text="确定导入", width=10, bg=color, fg="white",
              font=("微软雅黑", 10, "bold"), command=on_ok).pack(side="left", padx=10)
    tk.Button(btn_frame, text="取消", width=10, command=on_cancel).pack(side="left", padx=10)

    win.bind('<Return>', lambda e: on_ok())
    win.wait_window()
    return result["value"]

# ========== 自定义彩色确认弹窗 ==========
def ask_confirm_with_color_label(color, big_title, msg):
    win = tk.Toplevel()
    win.title(big_title)
    win.geometry("460x230")
    win.resizable(False, False)
    win.grab_set()

    tk.Label(win, text=big_title, fg=color, font=("微软雅黑", 14, "bold")).pack(pady=12)
    tk.Label(win, text=msg, font=("微软雅黑", 10), justify="center").pack(pady=8)

    result = {"ok": False}
    def on_yes():
        result["ok"] = True
        win.destroy()
    def on_no():
        result["ok"] = False
        win.destroy()

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=12)
    tk.Button(btn_frame, text="确认删除并导入", width=14, bg=color, fg="white",
              font=("微软雅黑", 10, "bold"), command=on_yes).pack(side="left", padx=8)
    tk.Button(btn_frame, text="取消", width=8, command=on_no).pack(side="left", padx=8)
    win.wait_window()
    return result["ok"]

def main():
    root = tk.Tk()
    root.withdraw()

    user_input = ask_date_with_color_label(THEME_COLOR, THEME_TITLE)
    if user_input is None:
        messagebox.showinfo("提示", "已取消导入")
        return

    # 输入非空但解析失败 → 明确报错退出（旧版这里会静默变成全量追加，已修复）
    if str(user_input).strip() != "" and parse_input_date(user_input) is None:
        messagebox.showerror(
            "日期格式不正确",
            f"无法识别输入的日期：{user_input}\n\n"
            "支持的写法：2026/10/27、2026-10-27、2026.10.27、2026年10月27日、10/27\n"
            "（留空 = 全量追加模式）"
        )
        return

    target_dt = parse_input_date(user_input)
    print("🚀 data_103 覆盖版导入工具启动")
    print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    df = read_excel_safely(EXCEL_PATH, SHEET_NAME)
    if df is None:
        messagebox.showerror("错误", "读取 Excel 失败，请检查文件是否被 WPS 打开占用！")
        return
    print(f"✅ 读取成功，共 {len(df)} 行")
    df = normalize_columns(df)
    print("===【调试】清洗后Excel列名===", list(df.columns))

    df.rename(columns=col_map, inplace=True)

    need_cols = ["日期", "班组"]
    miss_cols = [c for c in need_cols if c not in df.columns]
    if miss_cols:
        messagebox.showerror("表头校验失败", f"缺少必需列：{','.join(miss_cols)}")
        return

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")

    if target_dt is not None:
        df = df[df["日期"].dt.date == target_dt.date()].copy()
        if len(df) == 0:
            messagebox.showwarning("无数据", f"Excel中没有 {fmt_date(target_dt)} 的数据！")
            return
        print(f"🔍 筛选出当天 {len(df)} 行")

    bad_dates = int(df["日期"].isna().sum())
    if bad_dates:
        messagebox.showwarning("存在无效日期", f"Excel 中有 {bad_dates} 行日期无法解析，这些行将被跳过！")

    # 规范化：写库日期一律补零 YYYY/MM/DD（2026/10/27，不是 2026/10/27 不补零版）
    df = df[df["日期"].notna()].copy()
    df["日期"] = df["日期"].apply(fmt_date)
    print(f"✅ 日期已规范化为 YYYY/MM/DD，样例: {df['日期'].iloc[0] if len(df) else '-'}")

    conn = connect_db_safely(DB_PATH)
    if conn is None:
        messagebox.showerror("错误", "数据库连接失败！")
        return

    db_cols = get_table_columns(conn, TABLE_NAME)
    keep_cols = [c for c in df.columns if c in db_cols]
    df = df[keep_cols].copy()
    print(f"✅ 最终写入列：{keep_cols}")

    insert_cnt = 0

    if target_dt is not None:
        date_str = fmt_date(target_dt)   # 覆盖删除必须用补零日期，才能删到迁移后的旧记录
        ok = ask_confirm_with_color_label(
            THEME_COLOR, THEME_TITLE,
            f"即将删除 data_103 表中【{date_str}】全部旧记录（甲乙丙三班）\n"
            f"然后写入Excel当天 {len(df)} 条新数据。\n\n确认继续？"
        )
        if not ok:
            conn.close()
            print("❌ 用户取消覆盖操作")
            return
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE `日期` = ?", (date_str,))
        del_cnt = cursor.rowcount
        conn.commit()
        print(f"🗑️  已删除旧记录 {del_cnt} 条")
        if del_cnt == 0:
            again = messagebox.askyesno(
                "未删除到旧记录",
                f"按【{date_str}】没有删到任何旧记录。\n"
                "可能是该日本来就没有数据，也可能日期写错。\n\n仍要写入这 "
                f"{len(df)} 条新数据吗？"
            )
            if not again:
                conn.close()
                print("❌ 用户取消（未删除到旧记录，防止误写）")
                return
        df.to_sql(TABLE_NAME, conn, if_exists="append", index=False)
        insert_cnt = len(df)
    else:
        print("📦 全量追加模式（按 日期+班组 去重）")
        try:
            exist_df = pd.read_sql(f"SELECT `日期`, `班组` FROM {TABLE_NAME}", conn)
            exist_set = set(exist_df.itertuples(index=False, name=None))
        except Exception:
            exist_set = set()
        new_rows = [row for _, row in df.iterrows() if (row["日期"], row["班组"]) not in exist_set]
        new_df = pd.DataFrame(new_rows)
        if len(new_df) > 0:
            new_df.to_sql(TABLE_NAME, conn, if_exists="append", index=False)
        skipped = len(df) - len(new_df)
        print(f"✅ 跳过已存在 {skipped} 条（含库中已有数据）")
        insert_cnt = len(new_df)

    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    total = cursor.fetchone()[0]
    conn.close()

    msg = f"本次导入：{insert_cnt} 条\ndata_103表总记录：{total} 条"
    print(msg)
    messagebox.showinfo("导入完成", msg)

if __name__ == '__main__':
    main()
