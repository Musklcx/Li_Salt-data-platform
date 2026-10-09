# -*- coding: utf-8 -*-
"""
logger.py — 统一日志与监控模块
-------------------------------
1. 请求访问日志：每个 HTTP 请求一条（时间/方法/路径/状态/耗时/来源IP/用户），
   落盘到 logs/app.log（按天轮转，保留 30 天），同时输出到终端。
2. 错误日志：异常堆栈写 logs/error.log（按天轮转，保留 30 天）。
3. 运行监控：请求计数（今日）、服务启动时间，供 /api/health 使用。

接入方式（app.py）：
    from logger import init_logging, log_access, log_error, get_stats
    init_logging(app)
"""
import os
import logging
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from flask import request, g, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

APP_LOG = os.path.join(LOG_DIR, 'app.log')       # 访问日志（轮转后 app.log.2026-10-09）
ERROR_LOG = os.path.join(LOG_DIR, 'error.log')   # 错误日志

# 运行统计（内存态）：今日请求数、启动时间
_STATS = {
    'date': datetime.now().strftime('%Y-%m-%d'),
    'requests': 0,
    'errors': 0,
    'start_time': time.time(),
}

_access_logger = None
_error_logger = None


def _build_logger(name, filename):
    lg = logging.getLogger(name)
    if lg.handlers:  # 已初始化（reloader 重启时避免重复添加）
        return lg
    lg.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(message)s', datefmt='%H:%M:%S')
    fh = TimedRotatingFileHandler(filename, when='midnight', backupCount=30, encoding='utf-8')
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    lg.addHandler(fh)
    lg.addHandler(sh)
    lg.propagate = False
    return lg


def init_logging(_app):
    """在 app.py 中调用：注册请求日志钩子与全局异常处理"""
    global _access_logger, _error_logger
    _access_logger = _build_logger('workweb.access', APP_LOG)
    _error_logger = _build_logger('workweb.error', ERROR_LOG)

    @_app.before_request
    def _log_start():
        g._req_start = time.time()

    @_app.after_request
    def _log_response(resp):
        # 静态资源/健康探测请求不记日志（减少噪音）
        path = request.path
        if path.startswith('/static') or path == '/favicon.ico' or path == '/api/health':
            return resp
        try:
            ms = int((time.time() - g.get('_req_start', time.time())) * 1000)
        except Exception:
            ms = 0
        status = resp.status_code
        ip = request.remote_addr or '-'
        user = getattr(g, 'username', None) or '-'
        _access_logger.info(f"{status} {request.method} {path} {ms}ms {ip} user={user}")
        # 今日计数（跨天自动重置）
        today = datetime.now().strftime('%Y-%m-%d')
        if _STATS['date'] != today:
            _STATS['date'] = today
            _STATS['requests'] = 0
            _STATS['errors'] = 0
        _STATS['requests'] += 1
        if status >= 500:
            _STATS['errors'] += 1
        return resp

    @_app.errorhandler(500)
    def _log_exception(e):
        # 未捕获异常统一记录堆栈到 error.log，并返回统一 500 响应
        _STATS['errors'] += 1
        if _error_logger:
            _error_logger.error(f"{request.method} {request.path} 异常: {e}",
                                exc_info=True)
        if request.path.startswith('/api/'):
            return jsonify(code=500, msg='服务器内部错误，请查看运行日志', data=None), 500
        return ('<h3>服务器内部错误</h3><p>请查看运行日志 logs/error.log 获取详情。</p>', 500)


def log_access(msg):
    if _access_logger:
        _access_logger.info(msg)


def log_error(msg):
    if _error_logger:
        _error_logger.error(msg)


def get_stats():
    """运行统计：启动时间、今日请求数、今日错误数"""
    return {
        'start_time': _STATS['start_time'],
        'uptime_seconds': int(time.time() - _STATS['start_time']),
        'date': _STATS['date'],
        'requests_today': _STATS['requests'],
        'errors_today': _STATS['errors'],
    }


def read_log_file(filename, limit=200):
    """读日志文件末尾 N 行（按行分割的纯文本）"""
    if not os.path.exists(filename):
        return []
    with open(filename, encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()
    return lines[-limit:]
