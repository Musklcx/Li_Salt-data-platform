# -*- coding: utf-8 -*-
"""月度考勤蓝图: 考勤表 / 月结锁定 / 调整单 / Excel 导出 / 结算归档"""
import os
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, send_file, url_for

from attendance import calc
from attendance import config as C
from attendance.config import (ADJ_CATEGORIES, LEAVE_TYPES, OT_TYPES, get_db)

bp = Blueprint('att', __name__, url_prefix='/att')


@bp.route('/')
def index():
    return redirect(url_for('.attendance'))


@bp.route('/attendance', methods=['GET', 'POST'])
def attendance():
    y, m = calc.month_ym()
    return render_template('att_attendance.html', page=calc.attendance_payload(y, m), y=y, m=m)


@bp.route('/month/lock', methods=['POST'])
def month_lock():
    y, m = calc.month_ym()
    ym = calc.month_prefix(y, m)
    action = request.form.get('action', 'lock')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db = get_db()
    if action == 'lock':
        db.execute("INSERT OR IGNORE INTO month_lock(ym, locked_at) VALUES(?,?)", (ym, now))
    else:
        db.execute("DELETE FROM month_lock WHERE ym=?", (ym,))
    db.execute("INSERT INTO month_lock_log(ym, action, note, created_at) VALUES(?,?,?,?)",
               (ym, action, request.form.get('note', ''), now))
    db.commit()
    return redirect(url_for('.attendance', year=y, month=m))


@bp.route('/adjustment', methods=['POST'])
def adjustment():
    """调整单: 仅锁定月份可登记, 只能新增不能修改/删除(红冲请登记反向调整)"""
    y, m = calc.month_ym()
    ym = calc.month_prefix(y, m)
    if not calc.month_locked(y, m):
        return '本月尚未月结锁定，调整单只在锁定后使用；请先执行「月结锁定」。', 409
    if request.form.get('action') != 'add':
        return '调整单不支持删除，请登记一笔反向调整来冲正。', 409

    try:
        sid = int(request.form['staff_id'])
        hours = float(request.form.get('hours') or 0)
    except (KeyError, TypeError, ValueError):
        return '员工或工时格式不正确。', 409
    category = request.form.get('category', '')
    if category not in ADJ_CATEGORIES:
        return '调整类别不正确。', 409
    if not hours:
        return '调整工时不能为 0。', 409
    exc_type = request.form.get('exc_type', '').strip()
    if category == '请假' and exc_type not in LEAVE_TYPES:
        return '请假调整必须选择假别。', 409
    if category == '加班' and exc_type not in OT_TYPES:
        return '加班调整必须选择加班类型。', 409
    if category == '出勤':
        exc_type = ''
    adj_date = (request.form.get('adj_date') or '').strip() or None
    if adj_date and not adj_date.startswith(ym):
        return f'调整日期必须落在 {y}年{m}月 内。', 409
    reason = request.form.get('reason', '').strip()
    if not reason:
        return '请填写调整原因，调整单必须留痕。', 409

    db = get_db()
    db.execute(
        "INSERT INTO adjustments(ym,staff_id,adj_date,category,exc_type,hours,reason,operator,"
        "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (ym, sid, adj_date, category, exc_type, hours, reason, 'admin',
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    return redirect(url_for('.attendance', year=y, month=m))


@bp.route('/attendance/export')
def attendance_export():
    y, m = calc.month_ym()
    return calc.export_attendance(y, m)


@bp.route('/attendance/archive', methods=['POST'])
def archive():
    """结算归档: 锁定后的月份把当时的明细/汇总/口径落成只读文件(可重复归档, 版本+1)"""
    y, m = calc.month_ym()
    if not calc.month_locked(y, m):
        return '请先执行「月结锁定」，锁定后才能生成结算归档。', 409
    calc.archive_month(y, m)
    return redirect(url_for('.attendance', year=y, month=m))


@bp.route('/attendance/archive/download')
def archive_download():
    y, m = calc.month_ym()
    kind = request.args.get('kind', 'xlsx')
    row = get_db().execute(
        "SELECT xlsx, json, meta FROM month_archive WHERE ym=? ORDER BY ver DESC LIMIT 1",
        (calc.month_prefix(y, m),)).fetchone()
    path = (row[kind] if row and kind in ('xlsx', 'json', 'meta') else '') or ''
    # 只允许下载归档目录内的文件, 防路径穿越
    root = os.path.abspath(C.archive_dir())
    full = os.path.abspath(path) if path else ''
    if not full or not full.startswith(root) or not os.path.exists(full):
        return '该月份还没有结算归档, 或归档文件已丢失。', 404
    return send_file(full, as_attachment=True, download_name=os.path.basename(full))
