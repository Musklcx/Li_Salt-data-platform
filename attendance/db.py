# -*- coding: utf-8 -*-
"""数据库初始化 / 迁移 / 每日备份"""
import os
import sqlite3
from datetime import date, datetime, timedelta

from attendance import config
from attendance.config import (CYCLE, DEFAULT_STAFF_PER_GROUP, GROUPS, WHITE_DAY_CODE,
                         WHITE_GROUPS)

# 常白班(周工作制)生效首日: 系统里这 3 人从来没被算过考勤, 没有历史账要保护,
# 所以从数据起点(2026-09)统一按 8h 周工作制, 避免出现"11h 过渡月"
WHITE_SINCE = '2026-09-01'


def day_before_iso(iso):
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def get_conn():
    return sqlite3.connect(config.DB)


def _copy_db(target):
    src = sqlite3.connect(config.DB, timeout=10)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)          # 在线热备, 不阻塞读
    finally:
        dst.close()
        src.close()


def backup_db(force=False):
    """每日一份数据库快照, 保留最近 30 份。同一天已备份则跳过。"""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    target = os.path.join(config.BACKUP_DIR, f'attendance-{date.today():%Y%m%d}.db')
    if os.path.exists(target) and not force:
        return target
    _copy_db(target)
    olds = sorted(f for f in os.listdir(config.BACKUP_DIR)
                  if f.startswith('attendance-') and f.endswith('.db'))
    for f in olds[:-30]:
        try:
            os.remove(os.path.join(config.BACKUP_DIR, f))
        except OSError:
            pass
    return target


def close_db(exc):
    from flask import g
    db = g.pop('att_db', None)
    if db:
        db.close()


def init_db(with_backup=True):
    db = get_conn()
    c = db.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS staff(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        group_name TEXT NOT NULL,
        status TEXT DEFAULT '在职'
    );
    CREATE TABLE IF NOT EXISTS schedule(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        group_name TEXT NOT NULL,
        shift TEXT NOT NULL,
        is_override INTEGER DEFAULT 0,
        UNIQUE(date, group_name)
    );
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS exceptions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        exc_date TEXT NOT NULL,
        category TEXT NOT NULL,
        exc_type TEXT NOT NULL,
        planned_hours REAL DEFAULT 0,
        actual_hours REAL DEFAULT 0,
        multiplier REAL DEFAULT 1,
        note TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS month_lock(
        ym TEXT PRIMARY KEY,
        locked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS month_lock_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ym TEXT NOT NULL,
        action TEXT NOT NULL,
        note TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS adjustments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ym TEXT NOT NULL,
        staff_id INTEGER NOT NULL,
        adj_date TEXT,
        category TEXT NOT NULL,
        exc_type TEXT DEFAULT '',
        hours REAL DEFAULT 0,
        reason TEXT,
        operator TEXT DEFAULT 'admin',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS staff_group_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        group_name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        change_type TEXT DEFAULT '调组',
        pair_id TEXT,
        note TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS shift_swaps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        swap_date TEXT NOT NULL,
        staff_a INTEGER NOT NULL,
        staff_b INTEGER NOT NULL,
        note TEXT,
        created_at TEXT,
        UNIQUE(swap_date, staff_a, staff_b)
    );
    CREATE TABLE IF NOT EXISTS staff_holiday(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hol_date TEXT NOT NULL,
        staff_id INTEGER NOT NULL,
        note TEXT,
        created_at TEXT,
        UNIQUE(hol_date, staff_id)
    );
    -- 班次定义: 班制的唯一事实来源之一(计划工时不再写死在代码里)
    CREATE TABLE IF NOT EXISTS shift_def(
        code TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        hours REAL NOT NULL DEFAULT 0,
        cross_day INTEGER DEFAULT 0,
        sort INTEGER DEFAULT 0
    );
    -- 轮转规则: 班组在某生效区间内的周期排班; 同班组生效日最新的规则优先
    CREATE TABLE IF NOT EXISTS rot_rule(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL,
        cycle TEXT NOT NULL,
        offset INTEGER DEFAULT 0,
        anchor TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_to TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_rot_group ON rot_rule(group_name, valid_from);
    -- 结算归档: 月结时把当时的明细/汇总/口径落成只读文件, 供审计与纠纷回溯
    CREATE TABLE IF NOT EXISTS month_archive(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ym TEXT NOT NULL,
        ver INTEGER NOT NULL DEFAULT 1,
        dir TEXT NOT NULL,
        xlsx TEXT DEFAULT '',
        json TEXT DEFAULT '',
        meta TEXT DEFAULT '',
        staff_cnt INTEGER DEFAULT 0,
        work REAL DEFAULT 0,
        ot REAL DEFAULT 0,
        leave_h REAL DEFAULT 0,
        operator TEXT DEFAULT 'admin',
        created_at TEXT,
        UNIQUE(ym, ver)
    );
    -- 法定节假日日历: 全局(与班组无关)。kind='法定' 放假 / '调休上班' 补班
    -- 常白班的班型看它; 倒班制只借它给加班登记预选倍率类型
    CREATE TABLE IF NOT EXISTS holiday_calendar(
        date TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT '法定',
        note TEXT DEFAULT '',
        created_at TEXT
    );
    """)
    # 旧库补字段(列已存在时忽略)
    migrations = [
        "ALTER TABLE exceptions ADD COLUMN category TEXT DEFAULT '请假'",
        "ALTER TABLE exceptions ADD COLUMN multiplier REAL DEFAULT 1",
        "ALTER TABLE schedule ADD COLUMN is_holiday INTEGER DEFAULT 0",
        "ALTER TABLE staff ADD COLUMN report_to INTEGER",
        "ALTER TABLE staff ADD COLUMN badge_id TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN gender TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN position TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN photo TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN cloth_size TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN shoe_size TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN helmet_size TEXT DEFAULT ''",
        "ALTER TABLE staff ADD COLUMN shift_type TEXT DEFAULT '倒班制'",
        "ALTER TABLE staff ADD COLUMN hire_date TEXT",
        "ALTER TABLE staff ADD COLUMN leave_date TEXT",
    ]
    for sql in migrations:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    # 索引: 异动按 人+日期+类别+类型 唯一(允许同日"请假 + 加班"), 其余为查询加速
    for sql in [
        # 早期版本建的 (人+日期) 唯一索引会让同日请假+加班写不进去, 先删掉
        "DROP INDEX IF EXISTS idx_exc_staff_date",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_exc ON exceptions(staff_id, exc_date, category, exc_type)",
        "CREATE INDEX IF NOT EXISTS ix_exc_date ON exceptions(exc_date)",
        "CREATE INDEX IF NOT EXISTS ix_sched_date ON schedule(date)",
        "CREATE INDEX IF NOT EXISTS ix_adj_ym ON adjustments(ym)",
        "CREATE INDEX IF NOT EXISTS ix_glog_staff ON staff_group_log(staff_id, start_date)",
        "CREATE INDEX IF NOT EXISTS ix_swap_date ON shift_swaps(swap_date)",
        "CREATE INDEX IF NOT EXISTS ix_shol_date ON staff_holiday(hol_date)",
    ]:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    # 老数据补齐班组履历: 没有履历的人按当前班组建一条"初始"段, 起始日取入职日(未知则很早)
    for r in c.execute("SELECT id,group_name,hire_date FROM staff "
                       "WHERE id NOT IN (SELECT staff_id FROM staff_group_log)").fetchall():
        c.execute("INSERT INTO staff_group_log(staff_id,group_name,start_date,end_date,"
                  "change_type,note) VALUES(?,?,?,'','初始','系统补齐')",
                  (r[0], r[1], r[2] or '1970-01-01'))
    # 锚点: 旧版"甲班为白班"的日期, 仅作 base_shift 兜底用(正式口径走 rot_rule)
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('anchor_date','2026-09-28')")
    anchor_row = c.execute("SELECT value FROM settings WHERE key='anchor_date'").fetchone()
    anchor = (anchor_row[0] if anchor_row else '') or '2026-09-28'
    # 班次定义: 出厂 白 11h / 夜 11.5h / 白8(常白班) 8h / 休 0
    # 用 OR IGNORE 而非"空表才播": 老库补 白8, 但不会覆盖用户改过的工时
    c.executemany(
        "INSERT OR IGNORE INTO shift_def(code,label,hours,cross_day,sort) VALUES(?,?,?,?,?)",
        [('白', '白班', 11.0, 0, 1), ('夜', '夜班', 11.5, 1, 2),
         ('白8', '常白班', 8.0, 0, 3), ('休', '休息', 0, 0, 9)])
    # 轮转规则播种(空表才播): 周期/偏移沿用旧常量, 锚点必须与 settings.anchor_date 一致
    if not c.execute("SELECT COUNT(*) FROM rot_rule").fetchone()[0]:
        for gp, off in (('甲班', 0), ('乙班', 4), ('丙班', 2)):
            c.execute("INSERT INTO rot_rule(group_name,cycle,offset,anchor,valid_from,note) "
                      "VALUES(?,?,?,?,?,?)",
                      (gp, ','.join(CYCLE), off, anchor, '2000-01-01', '初始 6 天周期'))
        c.execute("INSERT INTO rot_rule(group_name,cycle,offset,anchor,valid_from,note) "
                  "VALUES('管理','白',0,'2000-01-01','2000-01-01','管理岗常白班')")
    # 一次性校正: 早期播种用的锚点(2026-09-21)与 settings.anchor_date(2026-09-28)差 7 天,
    # 会让"未落库的月份"整体错位一天。只改自动播种的那几条(用户自建规则不动)。
    if not c.execute("SELECT 1 FROM settings WHERE key='rot_anchor_synced'").fetchone():
        c.execute("UPDATE rot_rule SET anchor=? WHERE note='初始 6 天周期' AND anchor<>?",
                  (anchor, anchor))
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('rot_anchor_synced','1')")
    # 常白班(周工作制)启用: 管理组从 WHITE_SINCE 起 周一至周五 白8 / 周末 休
    # 7 天周期 + 锚点取周一 → 索引 0-4 工作日、5-6 周末, 直接复用现有轮转引擎
    if not c.execute("SELECT 1 FROM settings WHERE key='white_shift_ready'").fetchone():
        white_cycle = ','.join([WHITE_DAY_CODE] * 5 + ['休', '休'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for gp in WHITE_GROUPS:
            # 旧的"每天白班"规则截止到生效前一天(未截止的才改, 已截的不动)
            c.execute("UPDATE rot_rule SET valid_to=? WHERE group_name=? "
                      "AND (valid_to IS NULL OR valid_to='')",
                      (day_before_iso(WHITE_SINCE), gp))
            c.execute("INSERT INTO rot_rule(group_name,cycle,offset,anchor,valid_from,"
                      "valid_to,note,created_at) VALUES(?,?,0,?,?,'','常白班: 周一至周五 8h, 周末休息',?)",
                      (gp, white_cycle, anchor, WHITE_SINCE, now))
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('white_shift_ready','1')")
    # 空库时生成占位人员(甲乙丙各 17 人, 可在"人员管理"里改)
    if c.execute("SELECT COUNT(*) FROM staff").fetchone()[0] == 0:
        for gp in GROUPS:
            for i in range(1, DEFAULT_STAFF_PER_GROUP + 1):
                c.execute("INSERT INTO staff(name,group_name) VALUES(?,?)", (f"{gp}{i:02d}", gp))
    db.commit()
    db.close()
    # 生产模式: WAL 允许读写并发, 明显减少多人同时录入时的锁等待
    try:
        w = sqlite3.connect(config.DB, timeout=10)
        w.execute("PRAGMA journal_mode=WAL")
        w.execute("PRAGMA synchronous=NORMAL")
        w.close()
    except sqlite3.Error:
        pass
    try:
        if with_backup:
            backup_db()
    except Exception:
        pass
