# -*- coding: utf-8 -*-
"""
接口文档蓝图
------------
- 页面：/docs（仅管理员，自动生成的接口清单）
- 接口：/api/docs（返回全部业务路由：模块 / 方法 / 路径 / 说明）
说明来源：视图函数 docstring 第一行；未写注释的显示为「—」（可后续逐个补充）
"""
import inspect
from flask import Blueprint, render_template, current_app
from resp import ok

docs_bp = Blueprint('docs', __name__)

# 不需要出现在文档里的路径
SKIP_PATHS = ('/static', '/favicon.ico', '/docs', '/api/docs', '/logs', '/api/logs', '/api/health')

# 蓝图显示名（友好名称）
MODULE_NAMES = {
    'auth': '登录认证',
    'data': '数据对比',
    'notice': '班组工作量',
    'hazard': '现场问题汇总',
    'saferisks': '安全隐患整改',
    'staff': '人员概况',
    'download': '下载专区',
    'inventory': '期末金属量',
    'logs': '运行日志',
    'docs': '接口文档',
}


def _extract_desc(view_func):
    """从视图函数 docstring 取第一行作说明"""
    if not view_func:
        return ''
    doc = inspect.getdoc(view_func)
    if not doc:
        return ''
    first = doc.strip().splitlines()[0].strip()
    return first[:60]


@docs_bp.route('/docs')
def page_docs():
    return render_template('docs.html')


@docs_bp.route('/api/docs')
def api_docs():
    """接口清单：按蓝图分组，列出方法 / 路径 / 说明"""
    routes = []
    for rule in current_app.url_map.iter_rules():
        path = rule.rule
        if path in SKIP_PATHS or path.startswith('/static'):
            continue
        endpoint = rule.endpoint
        module = endpoint.split('.')[0] if '.' in endpoint else ''
        view_func = current_app.view_functions.get(endpoint)
        methods = sorted(m for m in rule.methods if m in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH'))
        if not methods:
            continue
        routes.append({
            'module': MODULE_NAMES.get(module, module),
            'method': ','.join(methods),
            'path': path,
            'desc': _extract_desc(view_func),
        })
    routes.sort(key=lambda r: (r['module'], r['path']))
    return ok({'routes': routes})
