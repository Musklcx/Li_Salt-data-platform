# -*- coding: utf-8 -*-
"""人员管理蓝图: 增删改 / 离职复职 / 班组变更(调组·对调) / 异动登记"""
import os
import uuid
from datetime import date, datetime

from flask import (Blueprint, current_app, jsonify, redirect, render_template, request,
                   url_for)

from attendance import calc
from attendance.config import GROUPS, OT_TYPES, get_db

bp = Blueprint('att_staff', __name__, url_prefix='/att')

# 解锁编辑密码：与隐患汇总(hazard_bp)、期末盘点(inventory_bp)统一
STAFF_EDIT_PASSWORD = 'admin888'


@bp.route('/staff/unlock', methods=['POST'])
def staff_unlock():
    """解锁编辑（前端拿到 ok 后才放开增删改按钮）"""
    data = request.get_json(force=True) or {}
    if data.get('password') == STAFF_EDIT_PASSWORD:
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'msg': '密码错误'}), 403


@bp.route('/staff', methods=['GET', 'POST'])
def staff():
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action', '')
        if action == 'add':
            name = request.form.get('name', '').strip()
            if name:
                group = request.form.get('group', GROUPS[0])
                hire = (request.form.get('hire_date') or '').strip() or date.today().isoformat()
                _age_raw = (request.form.get('age') or '').strip()
                cur = db.execute(
                    "INSERT INTO staff(name,group_name,status,gender,position,shift_type,hire_date,age) "
                    "VALUES(?,?,'在职',?,?,?,?,?)",
                    (name, group, request.form.get('gender', ''),
                     request.form.get('position', ''),
                     request.form.get('shift_type', '倒班制'), hire,
                     int(_age_raw) if _age_raw.isdigit() else None))
                # 工牌号: 表单有值用手填的, 没填则按 前缀-序号 自动续号;
                # 汇报对象/尺码/安全帽号新增时一并写入, 免得保存后还得再编辑一遍
                badge = request.form.get('badge_id', '').strip() or calc.next_badge_id(db, cur.lastrowid)
                _report_raw = request.form.get('report_to', '').strip()
                db.execute(
                    "UPDATE staff SET badge_id=?, report_to=?, cloth_size=?, shoe_size=?, helmet_size=? "
                    "WHERE id=?",
                    (badge,
                     int(_report_raw) if _report_raw.isdigit() else None,
                     request.form.get('cloth_size', '').strip(),
                     request.form.get('shoe_size', '').strip(),
                     request.form.get('helmet_size', '').strip(),
                     cur.lastrowid))
                # 入职即写入班组履历的第一段, 以后调组只往后追加
                db.execute("INSERT INTO staff_group_log(staff_id,group_name,start_date,end_date,"
                           "change_type,note) VALUES(?,?,?,'','入职','')",
                           (cur.lastrowid, group, hire))
        elif action in ('edit', 'toggle', 'delete', 'leave', 'rejoin'):
            sid = int(request.form['id'])
            cur_row = db.execute("SELECT * FROM staff WHERE id=?", (sid,)).fetchone()
            if not cur_row:
                return '员工不存在。', 409
            if action == 'edit':
                photo = save_photo(request.files.get('photo'), sid)
                fields = {
                    'badge_id': request.form.get('badge_id', '').strip(),
                    'name': request.form.get('name', '').strip(),
                    'gender': request.form.get('gender', ''),
                    'position': request.form.get('position', ''),
                    'report_to': int(request.form['report_to'])
                    if request.form.get('report_to', '').strip() else None,
                    'cloth_size': request.form.get('cloth_size', '').strip(),
                    'shoe_size': request.form.get('shoe_size', '').strip(),
                    'helmet_size': request.form.get('helmet_size', '').strip(),
                    'shift_type': request.form.get('shift_type', '倒班制'),
                    'hire_date': (request.form.get('hire_date') or '').strip() or None,
                    'leave_date': (request.form.get('leave_date') or '').strip() or None,
                    'age': int(request.form.get('age', '').strip())
                    if request.form.get('age', '').strip().isdigit() else None,
                }
                if photo:
                    fields['photo'] = photo
                sets = ', '.join(f"{k}=?" for k in fields)
                db.execute(f"UPDATE staff SET {sets} WHERE id=?", (*fields.values(), sid))
                # 编辑里改了班组(正常走「调组」), 这里兜底补一段履历, 保证考勤口径一致
                new_group = request.form.get('group', '')
                if new_group in GROUPS and new_group != calc.group_on(
                        calc.group_history_map(db), sid, date.today().isoformat(),
                        cur_row['group_name']):
                    err = calc.lock_error(date.today().isoformat())
                    if err:
                        return err, 409
                    calc.set_group(db, sid, new_group, date.today().isoformat(),
                                   '调组', '编辑资料时变更')
            elif action in ('leave', 'toggle'):
                leave = (request.form.get('leave_date') or '').strip() or date.today().isoformat()
                db.execute("UPDATE staff SET status='离职', leave_date=? WHERE id=?",
                           (leave, sid))
            elif action == 'rejoin':
                # 复职: 清空离职日期, 继续沿用原班组
                db.execute("UPDATE staff SET status='在职', leave_date=NULL WHERE id=?", (sid,))
            else:
                db.execute("DELETE FROM staff WHERE id=?", (sid,))
        db.commit()
        return redirect(url_for('.staff'))
    return render_template('att_staff.html', page=calc.staff_payload(), groups=GROUPS)


@bp.route('/staff/group', methods=['POST'])
def staff_group():
    """班组变更: 单人调组 / 两人对调, 都写履历, 考勤按当时班组重算"""
    db = get_db()
    action = request.form.get('action', 'change')
    eff = (request.form.get('eff_date') or '')[:10]
    try:
        date.fromisoformat(eff)
    except ValueError:
        return '请选择生效日期。', 409
    err = calc.lock_error(eff)
    if err:
        return err, 409
    note = request.form.get('note', '').strip()
    try:
        sid = int(request.form['staff_id'])
    except (KeyError, ValueError):
        return '员工不存在。', 409
    row = db.execute("SELECT id,name,group_name,hire_date,leave_date,status FROM staff "
                     "WHERE id=?", (sid,)).fetchone()
    if not row:
        return '员工不存在。', 409
    if row['hire_date'] and eff < row['hire_date']:
        return f"生效日期不能早于入职日期（{row['hire_date']}）。", 409
    if row['leave_date'] and eff > row['leave_date']:
        return f"该员工已于 {row['leave_date']} 离职，不能在此之后调组。", 409

    def swap_mate(pid):
        """该日是否有此人的换班: 有则返回对方姓名(换班与调组叠加会让当天归属来回抵消)"""
        r = db.execute("SELECT staff_a, staff_b FROM shift_swaps WHERE swap_date=? "
                       "AND (staff_a=? OR staff_b=?)", (eff, pid, pid)).fetchone()
        if not r:
            return ''
        mate = r['staff_a'] if r['staff_b'] == pid else r['staff_b']
        m = db.execute("SELECT name FROM staff WHERE id=?", (mate,)).fetchone()
        return m['name'] if m else '其他员工'

    clash = swap_mate(sid)
    if clash:
        return (f"{eff} 已登记 {row['name']} 与 {clash} 的换班。换班只换当天的班，调组从生效日起换班组，"
                f"两者落在同一天会互相抵消、算出来的工时既不是原班组也不是新班组。"
                f"请先到「排班 → 换班」撤销这一天的换班，或把生效日期改到别的日子。"), 409

    if action == 'swap':
        try:
            other = int(request.form['other_id'])
        except (KeyError, ValueError):
            return '请选择对调对象。', 409
        if other == sid:
            return '不能和自己对调。', 409
        r2 = db.execute("SELECT id,name,group_name,hire_date,leave_date FROM staff "
                        "WHERE id=?", (other,)).fetchone()
        if not r2:
            return '对调对象不存在。', 409
        if r2['hire_date'] and eff < r2['hire_date']:
            return f"对调对象的入职日期是 {r2['hire_date']}，生效日期不能早于它。", 409
        if r2['leave_date'] and eff > r2['leave_date']:
            return f"对调对象已于 {r2['leave_date']} 离职。", 409
        clash2 = swap_mate(other)
        if clash2:
            return (f"{eff} 对调对象 {r2['name']} 当天有与 {clash2} 的换班记录，"
                    f"换班和调组叠加会算错工时。请先撤销该换班，或改选生效日期。"), 409
        hist = calc.group_history_map(db)
        ga = calc.group_on(hist, sid, eff, row['group_name'])
        gb = calc.group_on(hist, other, eff, r2['group_name'])
        if ga == gb:
            return '两人当前同属一个班组，无需对调。', 409
        pair = uuid.uuid4().hex[:12]
        note = note or f'{row["name"]} 与 {r2["name"]} 班组成员对调'
        calc.set_group(db, sid, gb, eff, '对调', note, pair)
        calc.set_group(db, other, ga, eff, '对调', note, pair)
    else:
        target = request.form.get('group', '')
        if target not in GROUPS:
            return '请选择目标班组。', 409
        hist = calc.group_history_map(db)
        cur = calc.group_on(hist, sid, eff, row['group_name'])
        if cur == target:
            return f"该员工在 {eff} 已属{target}，无需调组。", 409
        calc.set_group(db, sid, target, eff, '调组', note or f'{cur} → {target}')
    db.commit()
    return redirect(url_for('.staff'))


def _wants_json():
    """连续登记用 fetch 提交, 需要拿到结构化结果(写了几条/跳过哪几天)"""
    return (request.form.get('_json') == '1'
            or 'application/json' in (request.headers.get('Accept') or ''))


def _fail(msg, code=409):
    if _wants_json():
        return jsonify({'ok': False, 'error': msg}), code
    return msg, code


def _day_tag(pl):
    """10-08（周四·白 11h）/ 10-10（周六·休）"""
    if pl['rest']:
        tail = '放' if pl['holiday'] else pl['shift']
    else:
        tail = f"{pl['shift']} {calc.num(pl['hours'])}h"
    return f"{pl['date'][5:]}（周{pl['w']}·{tail}）"


def _range_text(cat, sd, ed_, added, hours, rest_days, exist_days, off_days):
    """连续登记的一句话结果(预览与提交共用, 保证说法一致)"""
    span = (date.fromisoformat(ed_) - date.fromisoformat(sd)).days + 1
    head = sd[5:] if span == 1 else f'{sd[5:]} ~ {ed_[5:]} 共 {span} 天'
    bits = [f'登记 {added} 天' + (f'（合计 {calc.num(hours)}h）' if added else '')]
    if rest_days:
        bits.append(f'跳过 {len(rest_days)} 天休息/放假（' + '、'.join(d[5:] for d in rest_days[:6])
                    + ('…' if len(rest_days) > 6 else '') + '）')
    if exist_days:
        bits.append(f'{len(exist_days)} 天已有同类型记录，不重复写'
                    + '（' + '、'.join(d[5:] for d in exist_days[:4])
                    + ('…' if len(exist_days) > 4 else '') + '）')
    if off_days:
        bits.append(f'{len(off_days)} 天在在职区间外')
    return f'{head}：' + '；'.join(bits)


@bp.route('/exception/preview', methods=['POST'])
def exception_preview():
    """连续登记预览: 先算出会写哪几天、跳过哪几天, 让人在点"添加"之前就知道结果"""
    cat = request.form.get('category', '请假')
    sd = (request.form.get('start_date') or request.form.get('exc_date') or '')[:10]
    ed_ = (request.form.get('end_date') or sd)[:10]
    if not sd:
        return jsonify({'ok': False, 'error': '请选择日期'}), 409
    if ed_ < sd:
        sd, ed_ = ed_, sd
    try:
        sids = [int(x) for x in request.form.getlist('staff_ids')]
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': '员工参数不正确'}), 409
    if not sids:
        return jsonify({'ok': False, 'error': '请先选择员工'}), 409
    try:
        actual = float(request.form.get('actual_hours') or 0)
    except (TypeError, ValueError):
        actual = 0.0

    plans = calc.day_plan_map(sids, sd, ed_)
    db = get_db()
    etype = request.form.get('exc_type', '') or request.form.get('holiday_type', '')

    days = {}                      # iso -> {'add','rest','exist','off','people'}
    per = {}                       # sid -> {'name','add','rest','exist','off','hours'}
    for (sid, iso), pl in sorted(plans.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        p = per.setdefault(sid, {'id': sid, 'name': pl['name'], 'add': 0, 'rest': 0,
                                 'exist': 0, 'off': 0, 'hours': 0.0})
        d = days.setdefault(iso, {'date': iso, 'tag': _day_tag(pl), 'add': 0, 'rest': 0,
                                  'exist': 0, 'off': 0, 'hours': 0.0, 'people': []})
        if not pl['employed']:
            kind = 'off'
        elif cat == '请假' and pl['rest']:
            kind = 'rest'
        elif db.execute("SELECT 1 FROM exceptions WHERE staff_id=? AND exc_date=? "
                        "AND category=? AND exc_type=?", (sid, iso, cat, etype)).fetchone():
            kind = 'exist'
        else:
            kind = 'add'
            d['hours'] += actual if (cat == '请假' and actual > 0) else pl['hours']
            p['hours'] += actual if (cat == '请假' and actual > 0) else pl['hours']
        d[kind] += 1
        p[kind] += 1
        if kind in ('add', 'rest', 'exist'):
            d['people'].append(pl['name'])

    added = sum(d['add'] for d in days.values())
    rest_days = [d['date'] for d in days.values() if d['add'] == 0 and d['rest'] > 0]
    exist_days = [d['date'] for d in days.values() if d['add'] == 0 and d['rest'] == 0
                  and d['exist'] > 0]
    off_days = [d['date'] for d in days.values() if d['add'] == 0 and d['rest'] == 0
                and d['exist'] == 0 and d['off'] > 0]
    hours = sum(d['hours'] for d in days.values())
    lines = [_range_text(cat, sd, ed_, added, hours, rest_days, exist_days, off_days)]
    if len(per) > 1:               # 多人时补充每个人的差异(班型不同, 天数可能不一样)
        for p in per.values():
            if p['add'] or p['rest'] or p['off']:
                lines.append(f"{p['name']}：登记 {p['add']} 天"
                             + (f" / 跳过休息 {p['rest']} 天" if p['rest'] else '')
                             + (f" / 区间外 {p['off']} 天" if p['off'] else ''))
    locked = [d['date'] for d in days.values() if d['add'] and calc.lock_error(d['date'])]
    if locked:
        lines.append(f'注意：{locked[0]} 所在月份已月结锁定，提交会被拒绝')

    return jsonify({
        'ok': True, 'added': added, 'hours': round(hours, 2),
        'rest': len(rest_days), 'exist': len(exist_days), 'off': len(off_days),
        'days': sorted(days.values(), key=lambda x: x['date']),
        'people': list(per.values()), 'lines': lines, 'locked': locked,
    })


@bp.route('/exception', methods=['POST'])
def exception():
    """异动记录(请假 / 加班 / 放假日出勤), 支持多人同日批量登记"""
    db = get_db()
    action = request.form.get('action', '')
    cat = request.form.get('category', '请假')
    target_y, target_m = calc.month_ym()

    if action == 'add':
        mode = request.form.get('date_mode', 'single')
        if mode == 'range' and cat != '请假':
            return _fail('连续登记目前只用于请假；加班和放假日出勤请按天登记。')
        if mode == 'range':
            sd = (request.form.get('start_date') or '')[:10]
            ed_ = (request.form.get('end_date') or '')[:10]
            if not sd or not ed_:
                return _fail('请选择开始和结束日期。')
            if ed_ < sd:
                sd, ed_ = ed_, sd
        else:
            sd = ed_ = (request.form.get('exc_date') or '')[:10]
            if not sd:
                return _fail('请选择日期。')
        target_y, target_m = int(sd[:4]), int(sd[5:7])

        etype = request.form.get('exc_type', '')
        if cat == '放假':
            etype = request.form.get('holiday_type', '日常')
            mult = OT_TYPES.get(etype, 1.0)
        elif cat == '加班':
            mult = OT_TYPES.get(etype, 1.0)
        else:
            mult = 1.0
        try:
            actual = float(request.form.get('actual_hours') or 0)
        except (TypeError, ValueError):
            return _fail('实际工时格式不正确。')
        # 放假日出勤的时长不固定, 必须按实际填; 填 0 等于没登记, 直接拦掉
        if cat in ('加班', '放假') and actual <= 0:
            return _fail(('放假日出勤' if cat == '放假' else '加班') + '需要填写实际工时（大于 0）。')
        note = request.form.get('note', '').strip()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            sids = [int(x) for x in request.form.getlist('staff_ids')]
        except (TypeError, ValueError):
            return _fail('员工参数不正确。')
        if not sids:
            return _fail('请先选择员工。')

        # 每人每天"应上什么班、计划多少小时": 与考勤表同一口径(履历/换班/放假/在职区间)
        plans = calc.day_plan_map(sids, sd, ed_)
        if not plans:
            return _fail('没有匹配到员工，请刷新页面后重试。')

        if cat == '放假':
            # 放假日出勤 = 那天班组整体放假, 但这个人仍然来上班, 时长按实际填。
            # 班组没放假却记一条, 会和正常出勤重复计工时, 所以先核实"放假"这个事实。
            for (pid, iso), pl in plans.items():
                if pl['holiday']:
                    continue
                return _fail(
                    f"{iso} {pl['name']} 所在的{pl['group']}当天没有放假标记，这条放假日出勤登记不了。"
                    f"正常上班请登记「加班」；这天确实放假的话，先用左侧日历把该班组标成"
                    f"「放」，或在右侧给他做「按人放假」。")

        # 锁定的月份一条都不能写: 先整体校验, 避免写完一半才发现
        for (sid, iso), pl in plans.items():
            if not pl['employed'] or (cat == '请假' and pl['rest']):
                continue
            err = calc.lock_error(iso)
            if err:
                return _fail(f'{iso}：{err}')

        added, hours, total_plan = 0, 0.0, 0.0
        rest_days, exist_days, off_days = [], [], []
        for (sid, iso), pl in sorted(plans.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            if not pl['employed']:
                off_days.append(iso)
                continue
            # 请假: 当天本来是休息/放假, 不计计划工时 → 不用登记, 直接跳过
            if cat == '请假' and pl['rest']:
                rest_days.append(iso)
                continue
            # 同一人同一天: 同类同类型只允许一条; 请假与加班可以并存(各算各的)
            if db.execute("SELECT 1 FROM exceptions WHERE staff_id=? AND exc_date=? "
                          "AND category=? AND exc_type=?", (sid, iso, cat, etype)).fetchone():
                exist_days.append(iso)
                continue
            h = actual
            if cat == '请假' and actual <= 0:
                h = pl['hours']        # 留 0 = 按当天班次全扣(白 11 / 夜 11.5 / 常白 8)
            db.execute(
                "INSERT INTO exceptions(staff_id,exc_date,category,exc_type,planned_hours,"
                "actual_hours,multiplier,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (sid, iso, cat, etype, pl['hours'], h, mult, note, now))
            added += 1
            hours += h
            total_plan += pl['hours']
        db.commit()

        # 单日请假撞上休息日: 明确说明为什么没记上, 不静默丢弃
        if cat == '请假' and mode == 'single' and added == 0 and rest_days:
            pl = next(iter(plans.values()))
            return _fail(f"{pl['name']} {sd} 当天是"
                         f"{'放假' if pl['holiday'] else '休息'}，本来就不计计划工时，不用登记请假。")

        msg = _range_text(cat, sd, ed_, added, hours, sorted(set(rest_days)),
                          sorted(set(exist_days)), sorted(set(off_days)))
        if _wants_json():
            return jsonify({'ok': True, 'added': added, 'hours': round(hours, 2),
                            'plan': round(total_plan, 2), 'rest': len(set(rest_days)),
                            'exist': len(set(exist_days)), 'off': len(set(off_days)),
                            'message': msg})
    elif action == 'delete':
        eid = int(request.form['id'])
        row = db.execute("SELECT category, exc_date FROM exceptions WHERE id=?", (eid,)).fetchone()
        cat = row['category'] if row else '请假'
        if row:
            target_y, target_m = int(row['exc_date'][:4]), int(row['exc_date'][5:7])
            err = calc.lock_error(row['exc_date'])
            if err:
                return err, 409
        db.execute("DELETE FROM exceptions WHERE id=?", (eid,))
        db.commit()

    anchor = {'请假': '#leave-sec', '加班': '#ot-sec', '放假': '#hol-sec'}.get(cat, '#leave-sec')
    return redirect(url_for('att_sched.schedule', year=target_y, month=target_m) + anchor)


def save_photo(file, sid):
    """保存头像, 返回文件名; 没有文件或格式不支持时返回 None"""
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif'):
        return None
    filename = f"photo_{sid}{ext}"
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
    return filename
