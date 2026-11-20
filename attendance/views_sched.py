# -*- coding: utf-8 -*-
"""排班与异动蓝图: 日历 / 生成 / 放假 / 换班 / 班制设置"""
from datetime import date, datetime

from flask import Blueprint, redirect, render_template, request, url_for

from attendance import calc
from attendance import config as C

bp = Blueprint('att_sched', __name__, url_prefix='/att')


@bp.route('/schedule', methods=['GET', 'POST'])
def schedule():
    y, m = calc.month_ym()
    return render_template('att_schedule.html', page=calc.schedule_payload(y, m), y=y, m=m)


@bp.route('/schedule/generate', methods=['POST'])
def generate():
    y = int(request.form['year'])
    m = int(request.form['month'])
    if calc.month_locked(y, m):
        return f'{y}年{m}月已月结锁定，不能再重新生成排班。', 409
    calc.generate_month(y, m)
    return redirect(url_for('.schedule', year=y, month=m))


@bp.route('/schedule/toggle-holiday', methods=['POST'])
def toggle_holiday():
    """标记/取消放假: 不传 group = 三个班组一起切换; 传 group = 只切该班组"""
    d = request.form['date'][:10]
    err = calc.lock_error(d)
    if err:
        return err, 409
    gp = request.form.get('group', '').strip()
    db = C.get_db()
    cur = {r['group_name']: (r['is_holiday'] or 0) for r in
           db.execute("SELECT group_name,is_holiday FROM schedule WHERE date=?", (d,))}
    if gp in C.SHIFT_GROUPS:
        states = {gp: 0 if cur.get(gp) else 1}
    else:
        new = 0 if all(cur.get(g) for g in C.SHIFT_GROUPS) else 1
        states = {g: new for g in C.SHIFT_GROUPS}
    for g, v in states.items():
        calc.mark_day_holiday(db, d, g, v)
    db.commit()
    return redirect(url_for('.schedule', year=int(d[:4]), month=int(d[5:7])))


@bp.route('/schedule/holiday', methods=['POST'])
def holiday_plan():
    """放假安排: 全部班组 / 指定班组 / 指定人员, 支持起止日期"""
    db = C.get_db()
    action = request.form.get('action', 'add')
    if action == 'remove':
        if request.form.get('kind') == 'person':
            db.execute("DELETE FROM staff_holiday WHERE id=?",
                       (int(request.form['id']),))
            db.commit()
            y, m = calc.month_ym()
            return redirect(url_for('.schedule', year=y, month=m))
        d = request.form['date'][:10]
        err = calc.lock_error(d)
        if err:
            return err, 409
        for g in (request.form.getlist('groups') or C.SHIFT_GROUPS):
            if g in C.SHIFT_GROUPS:
                calc.mark_day_holiday(db, d, g, 0)
        db.commit()
        return redirect(url_for('.schedule', year=int(d[:4]), month=int(d[5:7])))

    start = (request.form.get('start_date') or '').strip()
    end = (request.form.get('end_date') or '').strip()
    days = calc.parse_day_range(start, end)
    if not days:
        return '请选择放假日期。', 409
    for d in days:
        err = calc.lock_error(d)
        if err:
            return err, 409
    scope = request.form.get('scope', 'all')
    note = request.form.get('note', '').strip()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if scope == 'person':
        sids = []
        for x in request.form.getlist('staff_ids'):
            try:
                sids.append(int(x))
            except ValueError:
                pass
        if not sids:
            return '请选择放假人员。', 409
        for d in days:
            for sid in sids:
                db.execute("INSERT OR IGNORE INTO staff_holiday(hol_date,staff_id,note,created_at) "
                           "VALUES(?,?,?,?)", (d, sid, note, now))
    else:
        groups = C.SHIFT_GROUPS if scope == 'all' else [request.form.get('group', '')]
        if scope == 'group' and groups[0] not in C.SHIFT_GROUPS:
            return '请选择要放假的班组。', 409
        for d in days:
            for g in groups:
                calc.mark_day_holiday(db, d, g, 1)
    db.commit()
    return redirect(url_for('.schedule', year=int(days[0][:4]), month=int(days[0][5:7])))


@bp.route('/schedule/swap', methods=['POST'])
def shift_swap():
    """两人换班: 当天 A 上 B 的班、B 上 A 的班; 只影响当事人, 不动班组排班"""
    db = C.get_db()
    if request.form.get('action') == 'delete':
        row = db.execute("SELECT swap_date FROM shift_swaps WHERE id=?",
                         (int(request.form['id']),)).fetchone()
        if row:
            err = calc.lock_error(row['swap_date'])
            if err:
                return err, 409
        db.execute("DELETE FROM shift_swaps WHERE id=?", (int(request.form['id']),))
        db.commit()
        y, m = calc.month_ym()
        if row:
            y, m = int(row['swap_date'][:4]), int(row['swap_date'][5:7])
        return redirect(url_for('.schedule', year=y, month=m))

    d = (request.form.get('swap_date') or '')[:10]
    err = calc.lock_error(d)
    if err:
        return err, 409
    try:
        a = int(request.form['staff_a'])
        b = int(request.form['staff_b'])
    except (KeyError, ValueError):
        return '请选择要互换的两位员工。', 409
    if a == b:
        return '请选择两位不同的员工。', 409
    ra = db.execute("SELECT id,name,group_name FROM staff WHERE id=?", (a,)).fetchone()
    rb = db.execute("SELECT id,name,group_name FROM staff WHERE id=?", (b,)).fetchone()
    if not ra or not rb:
        return '员工不存在。', 409
    if ra['group_name'] == '管理' or rb['group_name'] == '管理':
        return '管理岗不参与倒班换班。', 409
    if db.execute("SELECT 1 FROM shift_swaps WHERE swap_date=? AND "
                  "(staff_a IN (?,?) OR staff_b IN (?,?))",
                  (d, a, b, a, b)).fetchone():
        return '该员工当天已有换班记录，请先删除原记录再登记。', 409
    hist = calc.group_history_map(db)
    ga = calc.group_on(hist, a, d, ra['group_name'])
    gb = calc.group_on(hist, b, d, rb['group_name'])
    if ga == gb:
        return '两人当天同属一个班组，班型相同，无需换班。', 409
    db.execute("INSERT OR IGNORE INTO shift_swaps(swap_date,staff_a,staff_b,note,created_at) "
               "VALUES(?,?,?,?,?)",
               (d, a, b, request.form.get('note', '').strip(),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    return redirect(url_for('.schedule', year=int(d[:4]), month=int(d[5:7])))


# ============ 班制设置(班次定义 + 轮转规则) ============
@bp.route('/schedule/shiftdef', methods=['POST'])
def shiftdef_save():
    """修改班次定义(计划工时): 立即影响未锁定月份的重算与后续排班生成"""
    db = C.get_db()
    changed = 0
    for r in db.execute("SELECT code, hours FROM shift_def").fetchall():
        raw = request.form.get('hours_' + r['code'], '')
        if raw == '':
            continue
        try:
            h = float(raw)
        except ValueError:
            return f"班次「{r['code']}」的工时不是数字。", 409
        if h < 0:
            return '计划工时不能为负数。', 409
        if h != float(r['hours'] or 0):
            db.execute("UPDATE shift_def SET hours=? WHERE code=?", (h, r['code']))
            changed += 1
    db.commit()
    y, m = calc.month_ym()
    return redirect(url_for('.schedule', year=y, month=m))


@bp.route('/schedule/rotation', methods=['POST'])
def rotation_save():
    """轮转规则: 新增(自动截止同班组旧规则) / 结止"""
    db = C.get_db()
    action = request.form.get('action', 'add')

    if action == 'end':
        try:
            rid = int(request.form['id'])
        except (KeyError, ValueError):
            return '规则不存在。', 409
        row = db.execute("SELECT * FROM rot_rule WHERE id=?", (rid,)).fetchone()
        if not row:
            return '规则不存在。', 409
        end = (request.form.get('valid_to') or '').strip()
        try:
            date.fromisoformat(end)
        except ValueError:
            return '请填写正确的结止日期。', 409
        if end < row['valid_from']:
            return '结止日期不能早于规则的生效日。', 409
        db.execute("UPDATE rot_rule SET valid_to=? WHERE id=?", (end, rid))
        db.commit()
        y, m = calc.month_ym()
        return redirect(url_for('.schedule', year=y, month=m))

    group = request.form.get('group', '')
    if group not in C.GROUPS:
        return '请选择班组。', 409
    codes = C.parse_cycle(request.form.get('cycle', ''))
    if not codes:
        return '周期不能为空，例如：休,休,白,白,夜,夜。', 409
    if len(codes) < 2:
        return '周期至少 2 天（单班常白班请直接把周期写成 白,白）。', 409
    known = C.shift_hours_map()
    unknown = [x for x in codes if x not in known]
    if unknown:
        return f"周期里有未定义的班次 {'、'.join(unknown)}（现有班次：{'、'.join(known)}）。", 409
    try:
        off = int(request.form.get('offset') or 0)
        anchor = date.fromisoformat(request.form.get('anchor', '')[:10])
        vf = date.fromisoformat(request.form.get('valid_from', '')[:10])
    except ValueError:
        return '锚点 / 生效日期格式不正确。', 409
    # 新规则必须比该班组所有现有规则都晚生效(同班组生效日最新者优先)
    later = db.execute("SELECT valid_from FROM rot_rule WHERE group_name=? AND valid_from>=?",
                       (group, vf.isoformat())).fetchone()
    if later:
        return f"该班组已存在 {later['valid_from']} 起生效的规则，新规则的生效日必须更晚。", 409
    # 同班组更早的未结束规则, 自动截止到新规则生效日前一天
    db.execute("UPDATE rot_rule SET valid_to=? WHERE group_name=? AND valid_from<? "
               "AND (valid_to='' OR valid_to>=?)",
               (calc.day_before(vf.isoformat()), group, vf.isoformat(), vf.isoformat()))
    db.execute("INSERT INTO rot_rule(group_name,cycle,offset,anchor,valid_from,note,created_at) "
               "VALUES(?,?,?,?,?,?,?)",
               (group, ','.join(codes), off, anchor.isoformat(), vf.isoformat(),
                request.form.get('note', '').strip(),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    y, m = calc.month_ym()
    return redirect(url_for('.schedule', year=y, month=m))
