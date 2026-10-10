# -*- coding: utf-8 -*-
"""
登录认证蓝图（移植自 D:/MyWork/Flask/Login/login/app.py）
-------------------------------------------------
- bcrypt 加盐哈希存密码，绝不存明文
- JWT（HS256，默认 2 小时过期）签发/校验，token 存前端 localStorage
- 邮箱验证码注册（未配置 SMTP 时验证码打印到控制台，方便本地联调）
- 用户库：data/users.db（与业务库 db_day.db 分离，直接延用原 login 账号）

受保护接口可用 @login_required 装饰器统一校验。
"""
import os
import re
import secrets
import sqlite3
import smtplib
import datetime
import functools
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import bcrypt
import jwt
from flask import Blueprint, request, jsonify, render_template, g, current_app

auth_bp = Blueprint('auth', __name__)

# ---- 配置（沿用 login 原逻辑）----
AUTH_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db')

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def auth_config(key, default=None):
    """统一从 app.config 取配置（app.py 里可覆盖），缺失用默认值。"""
    return current_app.config.get(key, default)


# ---- 数据库 ----
def get_db():
    if 'auth_db' not in g:
        g.auth_db = sqlite3.connect(AUTH_DB_PATH, timeout=10)
        g.auth_db.row_factory = sqlite3.Row
        g.auth_db.execute('PRAGMA foreign_keys = ON')
        g.auth_db.execute('PRAGMA journal_mode=WAL')
        g.auth_db.execute('PRAGMA busy_timeout=5000')
    return g.auth_db


@auth_bp.teardown_request
def close_auth_db(_exc=None):
    db = g.pop('auth_db', None)
    if db is not None:
        db.close()


def init_auth_db():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS verification_codes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT    NOT NULL,
            code       TEXT    NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# ---- 密码哈希 ----
def hash_password(plain):
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain, hashed):
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except (ValueError, TypeError):
        return False


# ---- 邮箱验证码 ----
def generate_code(length=6):
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))


def send_verify_email(to_email, code):
    host = auth_config('SMTP_HOST', '')
    if not host:
        print(f'[DEV] 注册验证码 -> {to_email} : {code}（未配置 SMTP，仅打印到控制台）')
        return True
    ttl_min = auth_config('VERIFY_CODE_TTL', 600) // 60
    body = (
        f'您正在进行账号注册，本次验证码为：{code}\n\n'
        f'验证码 {ttl_min} 分钟内有效，请勿向他人泄露。\n'
        f'如非本人操作，请忽略本邮件。'
    )
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header('【注册验证码】' + code, 'utf-8')
    msg['From'] = formataddr(('注册验证', auth_config('MAIL_FROM', '') or auth_config('SMTP_USER', '')))
    msg['To'] = to_email
    try:
        port = auth_config('SMTP_PORT', 465)
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        server.login(auth_config('SMTP_USER', ''), auth_config('SMTP_PASS', ''))
        server.sendmail(auth_config('MAIL_FROM', '') or auth_config('SMTP_USER', ''), [to_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'[SMTP] 发送验证码失败: {e}')
        return False


# ---- JWT ----
def issue_token(user_id, email, role):
    now = datetime.datetime.utcnow()
    payload = {
        'sub': str(user_id),
        'email': email,
        'role': role,
        'iat': now,
        'exp': now + datetime.timedelta(hours=auth_config('JWT_EXPIRE_HOURS', 2)),
    }
    return jwt.encode(payload, auth_config('SECRET_KEY'), algorithm=auth_config('JWT_ALGORITHM', 'HS256'))


def _extract_token():
    """优先取请求头 Authorization: Bearer <token>，其次取 Cookie 里的 token"""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth.split(' ', 1)[1].strip()
    return request.cookies.get('token') or ''


def resolve_user():
    """全局校验：token 有效返回 (user_id, email, role)，否则返回 (None, None, None)"""
    token = _extract_token()
    if not token:
        return None, None, None
    try:
        payload = jwt.decode(token, auth_config('SECRET_KEY'),
                             algorithms=[auth_config('JWT_ALGORITHM', 'HS256')])
    except jwt.ExpiredSignatureError:
        return None, None, None
    except jwt.InvalidTokenError:
        return None, None, None
    return int(payload['sub']), payload.get('email'), payload.get('role', 'operator')


def login_required(view):
    """装饰器：校验 Authorization: Bearer <token> 或 Cookie token，用户信息挂到 g 上。"""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify(code=401, msg='未登录或缺少凭证', data=None), 401
        try:
            payload = jwt.decode(token, auth_config('SECRET_KEY'),
                                 algorithms=[auth_config('JWT_ALGORITHM', 'HS256')])
        except jwt.ExpiredSignatureError:
            return jsonify(code=401, msg='登录已过期，请重新登录', data=None), 401
        except jwt.InvalidTokenError:
            return jsonify(code=401, msg='凭证无效', data=None), 401
        g.user_id = int(payload['sub'])
        g.email = payload['email']
        return view(*args, **kwargs)
    return wrapper


# ---- 页面 ----
@auth_bp.route('/login')
def login_page():
    
    """登录页面"""
    return render_template('login.html')


# ---- API：发送注册验证码 ----
@auth_bp.post('/api/register/send-code')
def send_code():
    
    """发送邮箱注册验证码"""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not EMAIL_RE.match(email):
        return jsonify(code=400, msg='邮箱格式不正确', data=None), 400

    db = get_db()
    exists = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if exists:
        return jsonify(code=409, msg='该邮箱已被注册', data=None), 409

    now = datetime.datetime.utcnow()
    recent = db.execute(
        'SELECT id, created_at FROM verification_codes WHERE email = ? ORDER BY id DESC LIMIT 1',
        (email,)
    ).fetchone()
    if recent is not None:
        last_at = datetime.datetime.fromisoformat(recent['created_at'])
        if (now - last_at).total_seconds() < auth_config('VERIFY_CODE_RESEND', 60):
            return jsonify(code=429, msg='发送太频繁，请 60 秒后再试', data=None), 429

    code = generate_code()
    expires_at = (now + datetime.timedelta(seconds=auth_config('VERIFY_CODE_TTL', 600))).isoformat()
    db.execute('UPDATE verification_codes SET used = 1 WHERE email = ?', (email,))
    db.execute(
        'INSERT INTO verification_codes (email, code, expires_at, used, created_at) VALUES (?, ?, ?, 0, ?)',
        (email, code, expires_at, now.isoformat())
    )
    db.commit()

    if not send_verify_email(email, code):
        db.execute(
            'DELETE FROM verification_codes WHERE email = ? AND used = 0 AND code = ?',
            (email, code)
        )
        db.commit()
        return jsonify(code=500, msg='验证码发送失败，请稍后重试或联系管理员', data=None), 500
    return jsonify(code=0, msg='验证码已发送，请查收邮件', data=None)


# ---- API：注册 ----
@auth_bp.post('/api/register')
def register():
    
    """注册新账号（邮箱+验证码）"""
    # 注册开关（默认关闭）：仅管理员通过「用户管理→新增用户」开通账号
    if not current_app.config.get('REGISTER_ENABLED'):
        return jsonify(code=403, msg='注册通道已关闭，请联系管理员开通账号', data=None), 403
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    code = (data.get('code') or '').strip()

    if not username:
        return jsonify(code=400, msg='请输入用户名', data=None), 400
    if not EMAIL_RE.match(email):
        return jsonify(code=400, msg='邮箱格式不正确', data=None), 400
    if len(password) < 6:
        return jsonify(code=400, msg='密码长度至少 6 位', data=None), 400

    db = get_db()
    exists = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if exists:
        return jsonify(code=409, msg='该邮箱已被注册', data=None), 409

    if not code:
        return jsonify(code=400, msg='请输入邮箱验证码', data=None), 400
    vrow = db.execute(
        'SELECT id, code, expires_at, used FROM verification_codes '
        'WHERE email = ? ORDER BY id DESC LIMIT 1',
        (email,)
    ).fetchone()
    now = datetime.datetime.utcnow()
    if vrow is None or vrow['used'] == 1 or vrow['code'] != code:
        return jsonify(code=400, msg='验证码错误，请重新输入', data=None), 400
    if datetime.datetime.fromisoformat(vrow['expires_at']) < now:
        return jsonify(code=400, msg='验证码已过期，请重新获取', data=None), 400
    db.execute('UPDATE verification_codes SET used = 1 WHERE id = ?', (vrow['id'],))

    pw_hash = hash_password(password)
    db.execute(
        'INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)',
        (username, email, pw_hash, datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return jsonify(code=0, msg='注册成功，请登录', data={'username': username, 'email': email})


# ---- API：登录 ----
@auth_bp.post('/api/login')
def login():
    
    """账号密码登录，返回 token"""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify(code=400, msg='请输入邮箱和密码', data=None), 400

    db = get_db()
    row = db.execute(
        'SELECT id, username, email, password_hash, role FROM users WHERE email = ?',
        (email,)
    ).fetchone()

    if row is None or not verify_password(password, row['password_hash']):
        return jsonify(code=401, msg='邮箱或密码错误', data=None), 401

    token = issue_token(row['id'], row['email'], row['role'])
    resp = jsonify(code=0, msg='登录成功', data={
        'token': token,
        'user': {
            'id': row['id'],
            'username': row['username'],
            'email': row['email'],
            'role': row['role'],
        }
    })
    # 种 HttpOnly Cookie：地址栏直接访问业务页面/接口也能自动携带凭证
    resp.set_cookie(
        'token', token,
        httponly=True, samesite='Lax', path='/',
        max_age=auth_config('JWT_EXPIRE_HOURS', 2) * 3600
    )
    return resp


# ---- API：退出登录（清 Cookie）----
@auth_bp.post('/api/logout')
def logout():
    
    """退出登录（清除 token）"""
    resp = jsonify(code=0, msg='已退出登录', data=None)
    resp.delete_cookie('token', path='/')
    return resp


# ---- API：当前用户（受 JWT 保护）----
@auth_bp.get('/api/me')
@login_required
def me():
    db = get_db()
    row = db.execute(
        'SELECT id, username, email, role, created_at FROM users WHERE id = ?',
        (g.user_id,)
    ).fetchone()
    if row is None:
        return jsonify(code=401, msg='用户不存在', data=None), 401
    return jsonify(code=0, msg='ok', data={
        'id': row['id'],
        'username': row['username'],
        'email': row['email'],
        'role': row['role'],
        'created_at': row['created_at'],
    })


# ---- API：管理员用户管理（仅管理员，由 app.py 全局权限拦截）----
@auth_bp.route('/users')
def users_page():
    """用户管理页面（管理员）"""
    return render_template('users.html')


@auth_bp.get('/api/users')
def admin_users():
    """用户列表（管理员）"""
    db = get_db()
    rows = db.execute(
        'SELECT id, username, email, role, created_at FROM users ORDER BY id'
    ).fetchall()
    return jsonify(code=0, msg='ok', data=[{
        'id': r['id'],
        'username': r['username'],
        'email': r['email'],
        'role': r['role'],
        'created_at': r['created_at'],
    } for r in rows])


@auth_bp.post('/api/users/reset-password')
def admin_reset_password():
    """管理员重置用户密码（仅管理员）"""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    new_password = data.get('new_password') or ''
    if not email or not new_password:
        return jsonify(code=400, msg='邮箱和新密码都不能为空', data=None), 400
    if len(new_password) < 6:
        return jsonify(code=400, msg='新密码长度至少 6 位', data=None), 400
    db = get_db()
    row = db.execute(
        'SELECT id, username FROM users WHERE email = ?', (email,)
    ).fetchone()
    if row is None:
        return jsonify(code=404, msg='该邮箱用户不存在', data=None), 404
    new_hash = hash_password(new_password)
    db.execute('UPDATE users SET password_hash = ? WHERE email = ?', (new_hash, email))
    db.commit()
    return jsonify(code=0, msg=f'已重置用户 [{row["username"]}] 的密码', data=None)


@auth_bp.post('/api/users/create')
def admin_create_user():
    """管理员新增用户（仅管理员；注册关闭后的受控开号通道）"""
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    role = (data.get('role') or 'operator').strip().lower()
    if not username:
        return jsonify(code=400, msg='请输入用户名', data=None), 400
    if not EMAIL_RE.match(email):
        return jsonify(code=400, msg='邮箱格式不正确', data=None), 400
    if len(password) < 6:
        return jsonify(code=400, msg='密码长度至少 6 位', data=None), 400
    if role not in ('admin', 'operator'):
        return jsonify(code=400, msg='角色只能是 管理员 或 操作员', data=None), 400
    db = get_db()
    exists = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    if exists:
        return jsonify(code=409, msg='该邮箱已存在', data=None), 409
    new_hash = hash_password(password)
    db.execute(
        'INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?,?,?,?,?)',
        (username, email, new_hash, role, datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return jsonify(code=0, msg=f'已创建用户 [{username}]（{role}）', data=None)
