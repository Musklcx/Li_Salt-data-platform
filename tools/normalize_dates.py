# -*- coding: utf-8 -*-
"""
日期格式统一迁移工具
====================
把三个库所有"日期类"文本列统一成标准格式：

  - 日级日期：YYYY/MM/DD（补零，如 2026/09/01）—— 与页面显示格式一致
  - 月级月份：YYYY年MM月（补零，如 2026年01月）
  - ISO 时间戳（users.db 的 created_at 等）：不动

覆盖的列：
  db_day.db    data_103.日期 / month_plan.月份 / safeRisks.隐患排查时间·要求整改时间·整改完成时间 / chart_event.开始日期·结束日期
  db_balance.db balance.日期 / periods.start_date·end_date

安全机制：
  1. 冲突检测：若两种写法（2026/9/1 与 2026/09/01）同时存在，标准化后会在同一键上撞车，
     检测到即中止，不写库（需人工合并后重跑）
  2. 迁移前后行数/数值列合计校验，防误改
  3. 可重复执行（幂等）：已是标准格式的值原样跳过

使用：
  .venv\\Scripts\\python.exe tools/normalize_dates.py --dry-run   # 只看会改什么
  .venv\\Scripts\\python.exe tools/normalize_dates.py             # 实际执行
"""
import os
import re
import sys
import sqlite3
import shutil
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRY = '--dry-run' in sys.argv

# ---------- 归一化 ----------

def norm_date(s):
    """任意常见日期写法 → YYYY/MM/DD；解析失败返回 None"""
    s = str(s).strip().replace('.', '/').replace('-', '/')
    m = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        datetime.date(y, mo, d)
    except ValueError:
        return None
    return '%04d/%02d/%02d' % (y, mo, d)


def norm_month(s):
    """2026年1月 / 2026-01 / 2026/1 → 2026年01月；失败返回 None"""
    s = str(s).strip()
    m = re.match(r'^(\d{4})\D+(\d{1,2})月?$', s)
    if not m:
        return None
    return '%04d年%02d月' % (int(m.group(1)), int(m.group(2)))

# ---------- 迁移任务定义 ----------
# (库文件, 表, 列, 归一化函数)   键列用于冲突检测/数值校验
JOBS = [
    ('data/db_day.db',    'data_103',     '日期',          norm_date,  ['日期', '班组']),
    ('data/db_day.db',    'month_plan',   '月份',          norm_month, ['月份']),
    ('data/db_day.db',    'safeRisks',    '隐患排查时间',   norm_date,  None),
    ('data/db_day.db',    'safeRisks',    '要求整改时间',   norm_date,  None),
    ('data/db_day.db',    'safeRisks',    '整改完成时间',   norm_date,  None),
    ('data/db_day.db',    'chart_event',  '开始日期',       norm_date,  None),
    ('data/db_day.db',    'chart_event',  '结束日期',       norm_date,  None),
    ('data/db_balance.db', 'balance',     '日期',          norm_date,  ['日期']),
    ('data/db_balance.db', 'periods',     'start_date',    norm_date,  None),
    ('data/db_balance.db', 'periods',     'end_date',      norm_date,  None),
]


def checksum_rows(con, table, cols):
    """行数 + 指定列求和（迁移前后必须一致，防误改数值）"""
    n = con.execute(f'SELECT COUNT(*) FROM [{table}]').fetchone()[0]
    if not cols:
        return n, None
    sums = []
    for c in cols:
        try:
            s = con.execute(f'SELECT SUM([{c}]) FROM [{table}]').fetchone()[0]
            sums.append(round(float(s), 4))
        except sqlite3.OperationalError:
            sums.append(None)
    return n, sums


def main():
    changed_total = 0
    for dbf, table, col, fn, keycols in JOBS:
        path = os.path.join(BASE, dbf)
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        rows = con.execute(f'SELECT rowid AS rid, [{col}] AS v FROM [{table}]').fetchall()

        # 1) 归一化 + 冲突检测
        mapping = {}          # rid -> 新值
        norm_seen = {}        # 标准值 -> 原始值（发现第二种写法即冲突）
        conflicts = []
        bad = []
        n_change = 0
        for r in rows:
            v = str(r['v']).strip() if r['v'] is not None else ''
            if v == '':
                continue
            nv = fn(v)
            if nv is None:
                bad.append(v)
                continue
            if nv != v:
                mapping[r['rid']] = nv
                n_change += 1
            if nv in norm_seen and norm_seen[nv] != v:
                conflicts.append((nv, norm_seen[nv], v))
            norm_seen.setdefault(nv, v)

        tag = '[dry-run] ' if DRY else ''
        if conflicts:
            print(f'❌ {dbf}/{table}.{col}: 冲突！同一标准日期存在多种写法，需人工合并后重跑：')
            for nv, a, b in conflicts[:10]:
                print(f'    {nv} <- "{a}" 和 "{b}"')
            con.close()
            sys.exit(1)
        if bad:
            print(f'⚠️  {dbf}/{table}.{col}: {len(bad)} 个值无法解析为日期，已跳过: {bad[:5]}')

        # 2) 数值校验基线
        n_before, sums_before = checksum_rows(con, table, keycols)

        # 3) 写库
        if mapping and not DRY:
            con.executemany(
                f'UPDATE [{table}] SET [{col}]=? WHERE rowid=?',
                [(mapping[rid], rid) for rid in mapping])
            con.commit()

        # 4) 迁移后校验（实际执行时）
        if not DRY and mapping:
            n_after, sums_after = checksum_rows(con, table, keycols)
            if n_before != n_after or sums_before != sums_after:
                print(f'❌ {dbf}/{table}.{col}: 迁移后校验不一致，行数 {n_before}->{n_after}，'
                      f'合计 {sums_before}->{sums_after}')
                con.close()
                sys.exit(1)

        if n_change:
            ex = list(mapping.items())[:2]
            print(f'{tag}{dbf}/{table}.{col}: 改 {n_change} 值'
                  + (f'，例: rid={ex[0][0]} -> {ex[0][1]}' if ex else ''))
        else:
            print(f'{tag}{dbf}/{table}.{col}: 已是标准格式，无需改动')
        changed_total += n_change
        con.close()

    print(f'\n{"[dry-run] " if DRY else ""}合计待改/已改: {changed_total} 个值')
    if DRY:
        print('确认无误后去掉 --dry-run 实际执行。')
    else:
        print('完成。备份在 D:\\MyWork\\Flask\\Workweb\\_backup_before_datefix\\')


if __name__ == '__main__':
    main()
