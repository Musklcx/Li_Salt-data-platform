# -*- coding: utf-8 -*-
"""
统一数据访问层（主业务库 db_day.db）
-------------------------------------
- 每请求一个连接（挂到 flask.g），请求结束自动关闭
- 提供 query / fetchone / execute 三个方法，业务代码不再直接碰 sqlite3

用法：
    from db import query, fetchone, execute
    rows = query("SELECT * FROM data_103 WHERE 班组 = ?", ["甲"])
    row  = fetchone("SELECT 碳酸锂 FROM month_plan WHERE 月份 = ?", ["2026年9月"])
    execute("UPDATE question_table SET `处理措施`=? WHERE ID=?", [measures, row_id])
"""
import os
import sqlite3
from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data", "db_day.db")


def get_db():
    """取当前请求的数据库连接（不存在则创建）"""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_FILE, timeout=10)
        g.db.row_factory = sqlite3.Row
        # 并发加固：WAL 模式（读写不互斥）+ busy_timeout（写锁等待，避免 database is locked）
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA busy_timeout=5000')
    return g.db


def close_db(exc=None):
    """请求结束关闭连接（由 app.py 注册为 teardown_appcontext）"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query(sql, params=None):
    """查询多行，返回 [{列名: 值}, ...]"""
    rows = get_db().execute(sql, params or []).fetchall()
    return [dict(r) for r in rows]


def fetchone(sql, params=None):
    """查询单行，返回 {列名: 值} 或 None"""
    row = get_db().execute(sql, params or []).fetchone()
    return dict(row) if row else None


def execute(sql, params=None):
    """执行 INSERT / UPDATE / DELETE，自动提交，返回影响行数"""
    db = get_db()
    cur = db.execute(sql, params or [])
    db.commit()
    return cur.rowcount
