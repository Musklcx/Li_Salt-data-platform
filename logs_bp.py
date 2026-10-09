# -*- coding: utf-8 -*-
"""
运行日志与监控蓝图
------------------
- 页面：/logs（仅管理员，日志与健康查看）
- 接口：/api/logs/access（请求日志）、/api/logs/error（错误日志）、/api/health（健康检查）
数据来源：logger.py（logs/app.log、logs/error.log、内存统计）
"""
import os
import sqlite3
from flask import Blueprint, request, render_template
from resp import ok, fail
from logger import APP_LOG, ERROR_LOG, get_stats, read_log_file

logs_bp = Blueprint('logs', __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATHS = {
    'users.db': os.path.join(BASE_DIR, 'data', 'users.db'),
    'db_day.db': os.path.join(BASE_DIR, 'data', 'db_day.db'),
    'db_balance.db': os.path.join(BASE_DIR, 'data', 'db_balance.db'),
}
BACKUP_ROOT = r'D:\MyWork\Flask\Backup\workweb'


@logs_bp.route('/logs')
def page_logs():
    return render_template('logs.html')


@logs_bp.route('/api/logs/access')
def api_logs_access():
    """请求日志：默认返回今天的 app.log 末尾 limit 行（默认 200，最多 500）"""
    limit = min(int(request.args.get('limit', 200)), 500)
    lines = read_log_file(APP_LOG, limit)
    return ok({'lines': lines, 'file': os.path.basename(APP_LOG)})


@logs_bp.route('/api/logs/error')
def api_logs_error():
    limit = min(int(request.args.get('limit', 100)), 500)
    lines = read_log_file(ERROR_LOG, limit)
    return ok({'lines': lines, 'file': os.path.basename(ERROR_LOG)})


@logs_bp.route('/api/health')
def api_health():
    """健康检查：服务状态 / 运行时长 / 今日请求与错误 / 三个库连通性 / 最近备份"""
    stats = get_stats()

    # 三个数据库连通性
    db_status = {}
    for name, path in DB_PATHS.items():
        ok_flag = False
        try:
            conn = sqlite3.connect(path)
            conn.execute('SELECT 1').fetchone()
            conn.close()
            ok_flag = True
        except Exception as e:
            ok_flag = False
        db_status[name] = ok_flag

    # 最近备份：Backup 目录下最新一天的文件数
    backup = {'available': False, 'latest': None, 'file_count': 0}
    if os.path.isdir(BACKUP_ROOT):
        try:
            days = sorted(d for d in os.listdir(BACKUP_ROOT)
                          if os.path.isdir(os.path.join(BACKUP_ROOT, d)))
            if days:
                latest = days[-1]
                files = [f for f in os.listdir(os.path.join(BACKUP_ROOT, latest))
                         if f.endswith('.db')]
                backup = {'available': True, 'latest': latest,
                          'file_count': len(files)}
        except Exception:
            pass

    return ok({
        'status': 'running',
        'start_time': stats['start_time'],
        'uptime_seconds': stats['uptime_seconds'],
        'date': stats['date'],
        'requests_today': stats['requests_today'],
        'errors_today': stats['errors_today'],
        'db_status': db_status,
        'backup': backup,
    })
