# -*- coding: utf-8 -*-
"""
接口文档蓝图
------------
- 页面：/docs（仅管理员，自动生成的接口清单）
- 接口：/api/docs（返回全部业务路由：模块 / 方法 / 路径 / 说明）
说明来源：视图函数 docstring 第一行；未写注释的显示为「—」（可后续逐个补充）
"""
import inspect
import os
import datetime
from flask import Blueprint, render_template, current_app, request
from resp import ok
import check_report as cr

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


@docs_bp.route('/api/checkcard/generate', methods=['POST'])
def api_checkcard_generate():
    """生成数据核对卡（图片）到桌面：取所选日期前一天的数据"""
    today = datetime.date.today()
    sel = request.args.get('date')  # 前端选择的日期 YYYY-MM-DD（默认今天）
    if sel:
        try:
            base = datetime.datetime.strptime(sel, '%Y-%m-%d').date()
        except ValueError:
            return ok({'skipped': True, 'reason': '日期格式不正确，应为 YYYY-MM-DD'})
    else:
        base = today
    data_date = base - datetime.timedelta(days=1)
    date_str = data_date.strftime('%Y/%m/%d')

    rows = cr.load_day_rows(date_str)
    if cr.is_all_empty(rows):
        return ok({'skipped': True, 'reason': f'{date_str} 无记录（全空），未生成'})
    if cr.is_all_zero(rows):
        return ok({'skipped': True, 'reason': f'{date_str} 核对字段全 0，未生成'})

    shifts = cr.shifts_of(data_date)
    c = cr.collect(data_date, rows, shifts)
    tag = data_date.strftime('%m-%d')
    img_path = os.path.join(cr.SAVE_DIR, f'数据核对_{tag}.png')
    cr.render_image(c, img_path)

    return ok({
        'skipped': False,
        'date': date_str,
        'img': img_path,
    })
