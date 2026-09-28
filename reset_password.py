# -*- coding: utf-8 -*-
"""
管理员重置密码工具（命令行直接跑）
用法：
    cd /d D:\MyWork\Flask\Workweb\workweb
    .venv\Scripts\python.exe reset_password.py chunxiao8823@qq.com 123456
"""
import sys
import sqlite3
import bcrypt
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db')


def reset(email: str, new_password: str):
    if len(new_password) < 6:
        print('新密码长度至少 6 位')
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT id, username FROM users WHERE email = ?', (email,)).fetchone()
    if row is None:
        print(f'邮箱 {email} 不存在')
        sys.exit(1)

    new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn.execute('UPDATE users SET password_hash = ? WHERE email = ?', (new_hash, email))
    conn.commit()
    conn.close()
    print(f'已重置用户 [{row[1]}] ({email}) 的密码，请用新密码登录。')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    reset(sys.argv[1].strip().lower(), sys.argv[2])
