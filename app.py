# -*- coding: utf-8 -*-
"""
锂盐车间共享平台入口
--------------------
职责：应用配置、蓝图注册、全局登录拦截、启动初始化。
业务路由已按模块拆分为：
  - auth_bp      （auth.py）       登录认证
  - inventory_bp （inventory_bp.py）期末金属量盘点
  - data_bp      （data_bp.py）     数据对比
  - hazard_bp    （hazard_bp.py）   30吨蒸发问题汇总
  - notice_bp    （notice_bp.py）   班组工作量（通知公示）
  - staff_bp     （staff_bp.py）    人员概况
  - download_bp  （download_bp.py） 下载专区
  - saferisks_bp （saferisks_bp.py）安全隐患整改台账
统一数据访问：db.py（主库 db_day.db）；users.db 归 auth.py、db_balance.db 归 inventory_bp.py
"""
import os
import socket
from flask import Flask, jsonify, render_template, redirect, request, g
from auth import auth_bp, init_auth_db, resolve_user
from inventory_bp import inventory_bp, init_inventory_db
from data_bp import data_bp
from hazard_bp import hazard_bp
from notice_bp import notice_bp
from staff_bp import staff_bp
from download_bp import download_bp
from saferisks_bp import saferisks_bp
from db import close_db, DB_FILE
from logs_bp import logs_bp
from docs_bp import docs_bp
from logger import init_logging

app = Flask(__name__)

init_logging(app)  # 请求日志 / 错误日志 / 运行统计（logger.py）

# ---- 登录认证配置（auth 蓝图使用，移植自 login 项目）----
app.config['SECRET_KEY'] = os.environ.get(
    'JWT_SECRET',
    'dev-insecure-secret-please-change-me-to-a-long-random-string-32bytes+'
)
app.config['JWT_ALGORITHM'] = 'HS256'
app.config['JWT_EXPIRE_HOURS'] = 2
# 邮箱验证码（未配置 SMTP_HOST 时验证码打印到服务控制台，便于本地联调）
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', '')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '465'))
app.config['SMTP_USER'] = os.environ.get('SMTP_USER', '')
app.config['SMTP_PASS'] = os.environ.get('SMTP_PASS', '')
app.config['MAIL_FROM'] = os.environ.get('MAIL_FROM', '') or app.config['SMTP_USER']
app.config['VERIFY_CODE_TTL'] = 10 * 60
app.config['VERIFY_CODE_RESEND'] = 60

# ---- 蓝图注册 ----
app.register_blueprint(auth_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(data_bp)
app.register_blueprint(hazard_bp)
app.register_blueprint(notice_bp)
app.register_blueprint(staff_bp)
app.register_blueprint(download_bp)
app.register_blueprint(saferisks_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(docs_bp)

# ---- 统一数据库连接：请求结束自动关闭（db.py）----
app.teardown_appcontext(close_db)

# ========== 全局登录拦截：除白名单外，页面与接口一律要求已登录 ==========
PUBLIC_PATHS = {
    '/', '/login', '/favicon.ico',
    '/api/login', '/api/register', '/api/register/send-code',
}

# 只有管理员能访问的路径前缀（期末金属量盘点整组 + 运行日志/监控 + 接口文档 + 用户管理）
ADMIN_ONLY_PREFIXES = ('/inventory', '/api/state', '/api/rows', '/api/unlock', '/api/periods', '/api/import',
                       '/logs', '/api/logs', '/api/health', '/docs', '/api/docs', '/users', '/api/users')


@app.before_request
def require_login():
    path = request.path
    if path in PUBLIC_PATHS or path.startswith('/static'):
        return None
    uid, email, role = resolve_user()
    if uid is not None:
        g.user_id = uid
        g.email = email
        g.role = role
        # 管理员专属路径：非 admin 页面显示 403 提示页，接口返回 403 JSON
        if path.startswith(ADMIN_ONLY_PREFIXES) and role != 'admin':
            if path.startswith('/api/'):
                return jsonify(code=403, msg='无权限访问', data=None), 403
            return render_template('no_permission.html', email=email, role=role), 403
        return None
    # 未登录：API 返回 401 JSON，页面 302 跳回登录页
    if path.startswith('/api/'):
        return jsonify(code=401, msg='未登录或登录已过期', data=None), 401
    return redirect('/login')


# ========== 根路由 ==========
@app.route('/')
def home():
    return redirect('/login')


if __name__ == '__main__':
    with app.app_context():
        init_auth_db()  # 首次运行自动建用户表（已存在则跳过）
        init_inventory_db()  # 期末盘点库建表/补列/首次导入（已存在则跳过）
    hostname = socket.gethostname()
    print(f"局域网主机名访问地址：http://{hostname}:5000")
    print(f"数据库路径：{DB_FILE}")
    # debug=False：关闭 reloader（Windows 上 debug 热重载不稳定，多次导致实例崩溃），
    # 错误详情已由 logger.py 的 500 统一处理 + logs/error.log 兜底
    app.run(host="0.0.0.0", port=5000, debug=False)
