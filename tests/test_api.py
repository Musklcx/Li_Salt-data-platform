# -*- coding: utf-8 -*-
"""
接口自动化冒烟测试（只读，不污染数据库）
------------------------------------------
覆盖：
  1. 未登录拦截：API → 401，页面 → 302 /login
  2. 权限控制：操作员访问管理员接口 → 403
  3. 各业务接口正常返回 + 统一响应格式 {code, msg, data}
  4. 登录失败路径（错误参数返回 code!=0）
运行方式：
  双击 run_tests.bat，或命令行：.venv\\Scripts\\python.exe -m unittest tests.test_api -v
"""
import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module            # 导入 Flask 应用（不会启动服务器）
from auth import issue_token        # 直接签发测试令牌，无需真实密码


def make_token(role):
    """按角色签发测试 JWT（用户 id/邮箱取正式库里的记录）"""
    import sqlite3
    db = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      '..', 'data', 'users.db'))
    row = db.execute("SELECT id, email, role FROM users WHERE role=? LIMIT 1", (role,)).fetchone()
    db.close()
    if not row:
        raise RuntimeError('users.db 中无 role=%s 的用户' % role)
    return issue_token(row[0], row[1], row[2])


class ApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config['TESTING'] = True
        cls.client = app_module.app.test_client()
        with app_module.app.app_context():
            cls.admin_token = make_token('admin')
            cls.operator_token = make_token('operator')

    def headers(self, token=None):
        h = {}
        if token:
            h['Authorization'] = 'Bearer ' + token
        return h

    # ---------- 1. 未登录拦截 ----------
    def test_unauth_api_401(self):
        r = self.client.get('/api/notice/list?month=2026-08')
        self.assertEqual(r.status_code, 401)
        j = r.get_json()
        self.assertEqual(j['code'], 401)
        self.assertIn('data', j)

    def test_unauth_page_redirect_login(self):
        r = self.client.get('/data')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login', r.headers.get('Location', ''))

    # ---------- 2. 权限控制 ----------
    def test_operator_blocked_admin_api(self):
        r = self.client.get('/api/state?month=2026-08', headers=self.headers(self.operator_token))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['code'], 403)

    def test_operator_blocked_admin_page(self):
        r = self.client.get('/inventory', headers=self.headers(self.operator_token))
        self.assertEqual(r.status_code, 403)

    def test_operator_ok_normal_api(self):
        r = self.client.get('/api/notice/list?month=2026-08', headers=self.headers(self.operator_token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['code'], 0)

    # ---------- 3. 各业务接口 200 + 统一格式 ----------
    def _assert_ok(self, path):
        r = self.client.get(path, headers=self.headers(self.admin_token))
        self.assertEqual(r.status_code, 200, '接口 %s 状态码应为 200' % path)
        j = r.get_json()
        self.assertIsInstance(j, dict, '接口 %s 应返回 JSON 对象' % path)
        self.assertEqual(set(('code', 'msg', 'data')), set(j.keys()),
                         '接口 %s 应包含 code/msg/data 三键' % path)
        self.assertEqual(j['code'], 0, '接口 %s 业务码应为 0' % path)
        return j

    def test_business_apis(self):
        self._assert_ok('/api/output/all')
        self._assert_ok('/api/plan/get?month=2026-09')
        self._assert_ok('/api/notice/list?month=2026-08')
        self._assert_ok('/api/notice/sum?month=2026-08')
        self._assert_ok('/api/hazard/list')
        self._assert_ok('/api/risk/list')
        self._assert_ok('/api/state?month=2026-08')
        self._assert_ok('/api/periods')
        self._assert_ok('/api/health')
        self._assert_ok('/api/docs')

    def test_docs_list_has_routes(self):
        j = self._assert_ok('/api/docs')
        self.assertGreater(len(j['data']['routes']), 10, '接口文档应列出 10 个以上路由')

    # ---------- 4. 登录失败路径 ----------
    def test_login_bad_params(self):
        r = self.client.post('/api/login', json={})
        j = r.get_json()
        self.assertNotEqual(j['code'], 0)
        self.assertIsNone(j['data'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
