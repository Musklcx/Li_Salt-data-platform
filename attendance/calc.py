# -*- coding: utf-8 -*-
"""考勤计算与页面数据组装

月度考勤是"投影", 不是"结果":
    排班(schedule+轮转规则)、异动(exceptions)、换班(shift_swaps)、放假
    (schedule.is_holiday / staff_holiday)、调整单(adjustments) 都是事件,
    月度考勤表每次都由这些事件现算。改规则、补记录、删记录后刷新页面
    即得正确结果; 每格 tip 说明"这个数是怎么来的"。

工时口径:
    净出勤 = max(计划工时 - 当日请假扣减, 0)   请假/迟到早退/旷工属于"冲减类"
    加班工时 = 当日加班/放假出勤累加           属于"叠加类", 不占基础工时
    同一人同一天允许同时存在请假与加班记录(按 日期+类别+类型 唯一)

时间口径:
    当天(date.today())及之前 = 已发生, 照实计算;
    未来日期 = 只显示计划(灰格), 不计任何工时, 汇总自动"截至今日"。

人事口径:
    入职/离职日期界定在职区间, 区间外的日期不计出勤
    班组变更写入 staff_group_log, 考勤按"当天所属班组"的班型重算
    两人对调 = 同日生效的两条班组变更(共享 pair_id)
    两人换班 = shift_swaps 里的一天期班次互换, 只影响当事人, 不动班组排班
    放假支持三档: 全部班组 / 单个班组(schedule.is_holiday) / 个人(staff_holiday)
"""
import calendar
import io
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from flask import request, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from attendance import config as C
from attendance.config import (ADJ_CATEGORIES, ABSENT_TYPE, COMP_OFF_TYPE, GROUPS, HOLIDAY_TYPES,
                         LATE_TYPE, LEAVE_TYPES, OT_TYPES, PAID_PREFIX, REPORT_POSITIONS,
                         SHIFT_GROUPS, WEEK_CN, WHITE_GROUPS, eff_shift, get_db, holiday_kind,
                         is_day_shift, is_night_shift, planned_hours, shift_defs, shift_glyph,
                         shift_hours_map)


# ============ 通用小工具 ============
def num(v):
    """1.0 → 1, 1.5 → 1.5 (仅显示用)"""
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0
    return int(f) if f == int(f) else round(f, 1)


def month_days(y, m):
    return [date(y, m, i) for i in range(1, calendar.monthrange(y, m)[1] + 1)]


def month_prefix(y, m):
    return f"{y:04d}-{m:02d}"


def month_schedule(y, m):
    """一次取出整月排班, 缺失的格子用理论班型兜底 → {(iso, group): {shift, hol}}"""
    sched = {}
    for r in get_db().execute(
            "SELECT date,group_name,shift,is_holiday FROM schedule WHERE date LIKE ?",
            (month_prefix(y, m) + '%',)):
        sched[(r['date'], r['group_name'])] = {'shift': r['shift'], 'hol': r['is_holiday'] or 0}
    for d in month_days(y, m):
        iso = d.isoformat()
        for gp in GROUPS:
            sched.setdefault((iso, gp), {'shift': C.base_shift(d, gp), 'hol': 0})
    return sched


def generate_month(y, m):
    """生成某月三班排班; 保留已手动覆盖(is_override=1)的格子"""
    db = get_db()
    for d in month_days(y, m):
        iso = d.isoformat()
        for gp in GROUPS:
            row = db.execute(
                "SELECT shift FROM schedule WHERE date=? AND group_name=? AND is_override=1",
                (iso, gp)).fetchone()
            db.execute(
                "INSERT INTO schedule(date,group_name,shift,is_override) VALUES(?,?,?,?) "
                "ON CONFLICT(date,group_name) DO UPDATE SET shift=excluded.shift, "
                "is_override=excluded.is_override",
                (iso, gp, row['shift'] if row else C.base_shift(d, gp), 1 if row else 0))
    db.commit()


def month_ym():
    """从 GET/POST 取 year & month, 非法值退回本月"""
    today = date.today()
    try:
        y = int(request.values.get('year', today.year))
        m = int(request.values.get('month', today.month))
    except (TypeError, ValueError):
        return today.year, today.month
    if not 1 <= m <= 12:
        m = today.month
    if not 2000 <= y <= 2100:
        y = today.year
    return y, m


def day_meta(d, today=None):
    meta = {'iso': d.isoformat(), 'day': d.day, 'w': WEEK_CN[d.weekday()],
            'weekend': d.weekday() >= 5}
    if today:
        meta['future'] = d.isoformat() > today
    return meta


def next_badge_id(db, fallback_no):
    """按现有工牌号的 前缀-序号 规则续号, 没有历史数据时退回 PEP####"""
    buckets = defaultdict(list)
    for r in db.execute("SELECT badge_id FROM staff WHERE badge_id LIKE '%-%'"):
        b = (r['badge_id'] or '').strip()
        prefix, _, tail = b.rpartition('-')
        if prefix and tail.isdigit():
            buckets[prefix].append(int(tail))
    if not buckets:
        return f"PEP{fallback_no:04d}"
    prefix = Counter({k: len(v) for k, v in buckets.items()}).most_common(1)[0][0]
    return f"{prefix}-{max(buckets[prefix]) + 1:04d}"


# ============ 班组履历 / 换班 / 放假安排 ============
def group_history_map(db=None):
    """{staff_id: [(start, end, group)]}, 按生效日升序; end='' 表示至今"""
    db = db or get_db()
    hist = defaultdict(list)
    for r in db.execute(
            "SELECT staff_id,group_name,start_date,end_date FROM staff_group_log "
            "ORDER BY staff_id,start_date"):
        hist[r['staff_id']].append((r['start_date'] or '1970-01-01',
                                    r['end_date'] or '', r['group_name']))
    return hist


def group_on(hist, sid, iso, fallback=''):
    """某人某天所属班组: 取生效日 <= 当天 的最后一段, 没有履历则用当前班组兜底"""
    gp = ''
    for start, end, name in hist.get(sid, ()):
        if start <= iso and (not end or end >= iso):
            gp = name
    return gp or fallback


def day_before(iso):
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def sync_staff_group(db, sid):
    """把 staff.group_name 同步成"今天"所在班组(用于列表分组/筛选)"""
    gp = group_on(group_history_map(db), sid, date.today().isoformat())
    if gp:
        db.execute("UPDATE staff SET group_name=? WHERE id=?", (gp, sid))


def set_group(db, sid, new_group, eff, change_type='调组', note='', pair_id=None):
    """某人从 eff 当天起改属 new_group: 命中哪一段就截断/改写, 自动维护履历"""
    rows = db.execute("SELECT * FROM staff_group_log WHERE staff_id=? ORDER BY start_date",
                      (sid,)).fetchall()
    if not rows:
        cur = db.execute("SELECT group_name FROM staff WHERE id=?", (sid,)).fetchone()
        db.execute("INSERT INTO staff_group_log(staff_id,group_name,start_date,end_date,"
                   "change_type,note) VALUES(?,?,?,'','初始','系统补齐')",
                   (sid, (cur['group_name'] if cur else new_group), '1970-01-01'))
        rows = db.execute("SELECT * FROM staff_group_log WHERE staff_id=? ORDER BY start_date",
                          (sid,)).fetchall()
    target = None
    for r in rows:
        if (r['start_date'] or '') <= eff and (not r['end_date'] or r['end_date'] >= eff):
            target = r
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if target and target['start_date'] == eff:
        # 生效日恰好是某段起点 → 直接改这一段
        db.execute("UPDATE staff_group_log SET group_name=?, change_type=?, pair_id=?, note=? "
                   "WHERE id=?", (new_group, change_type, pair_id, note, target['id']))
    elif target:
        # 落在段中间 → 前段截到前一天, 后面新开一段
        db.execute("UPDATE staff_group_log SET end_date=? WHERE id=?",
                   (day_before(eff), target['id']))
        db.execute("INSERT INTO staff_group_log(staff_id,group_name,start_date,end_date,"
                   "change_type,pair_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (sid, new_group, eff, target['end_date'] or '', change_type, pair_id, note, now))
    else:
        # 早于所有段 → 新段止于下一段起点前一天
        nxt = next((r for r in rows if (r['start_date'] or '') > eff), None)
        end = day_before(nxt['start_date']) if nxt else ''
        db.execute("INSERT INTO staff_group_log(staff_id,group_name,start_date,end_date,"
                   "change_type,pair_id,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (sid, new_group, eff, end, change_type, pair_id, note, now))
    sync_staff_group(db, sid)


def parse_day_range(start, end=''):
    """'2026-10-01' + '2026-10-05' → 连续日期列表; 最长 92 天, 防误操作"""
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10]) if end else d0
    except (TypeError, ValueError):
        return []
    if d1 < d0:
        d0, d1 = d1, d0
    if (d1 - d0).days > 92:
        d1 = d0 + timedelta(days=92)
    out, cur = [], d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def mark_day_holiday(db, iso, group, value=1):
    """按班组标记/取消放假, 排班行不存在时补一条"""
    row = db.execute("SELECT 1 FROM schedule WHERE date=? AND group_name=?",
                     (iso, group)).fetchone()
    if row:
        db.execute("UPDATE schedule SET is_holiday=? WHERE date=? AND group_name=?",
                   (value, iso, group))
    else:
        db.execute("INSERT INTO schedule(date,group_name,shift,is_override,is_holiday) "
                   "VALUES(?,?,?,0,?)",
                   (iso, group, C.base_shift(date.fromisoformat(iso), group), value))


def day_holiday_state(db, d):
    """当前是否已标记放假 → 取反值(便于整列切换)"""
    row = db.execute("SELECT MAX(is_holiday) v FROM schedule WHERE date=?", (d,)).fetchone()
    return 0 if (row and row['v']) else 1


# ============ 月结锁定 ============
def lock_row(y, m):
    return get_db().execute("SELECT ym, locked_at FROM month_lock WHERE ym=?",
                            (month_prefix(y, m),)).fetchone()


def month_locked(y, m):
    return lock_row(y, m) is not None


def locked_ym_of(iso_date):
    """按日期字符串取所在月是否锁定"""
    try:
        d = date.fromisoformat(str(iso_date)[:10])
    except (TypeError, ValueError):
        return False
    return month_locked(d.year, d.month)


def lock_error(iso_date):
    """锁定时返回给前端的中文提示, 未锁返回 None"""
    if not locked_ym_of(iso_date):
        return None
    d = date.fromisoformat(str(iso_date)[:10])
    return f'{d.year}年{d.month}月已月结锁定，不能再改动排班或异动；如需更正请在「月度考勤 → 调整单」登记。'


# ============ 单日/连续登记共用: 某人某天"应上班多少小时" ============
def day_plan_map(sids, start_iso, end_iso):
    """一批人在 [start, end] 区间内, 每天属于哪个班组、上什么班、计划多少小时。

    与考勤表同一口径, 同时考虑四件事:
        1. 在职区间: 入职前 / 离职后 → employed=False
        2. 班组履历: 按"当天所属班组"取班型, 不是按今天的班组
        3. 换  班: 当天与对方互换 → 取对方班组的班型
        4. 放  假: 班组放假 / 个人放假 → holiday=True, 计划工时为 0

    返回 {(staff_id, iso): {...}}。连续登记请假用它跳过休息日, 预览提示也用它,
    保证"预览里看到什么"与"最终算出来的工时"是同一份数据。
    """
    db = get_db()
    sids = sorted({int(x) for x in sids if str(x).strip()})
    if not sids or not start_iso or not end_iso:
        return {}
    start = date.fromisoformat(str(start_iso)[:10])
    end = date.fromisoformat(str(end_iso)[:10])
    if end < start:
        start, end = end, start
    if (end - start).days > 92:                 # 一次最多 3 个月, 防止误填年份
        end = start + timedelta(days=92)
    span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    s_iso, e_iso = start.isoformat(), end.isoformat()

    hist = group_history_map(db)
    qs = ','.join('?' * len(sids))
    staff = {r['id']: r for r in db.execute(
        f'SELECT id,name,group_name,hire_date,leave_date FROM staff WHERE id IN ({qs})', sids)}

    # 换班: 当天与谁互换
    partner_of = {}
    for r in db.execute("SELECT staff_a,staff_b,swap_date FROM shift_swaps "
                        "WHERE swap_date BETWEEN ? AND ?", (s_iso, e_iso)):
        partner_of[(r['staff_a'], r['swap_date'])] = r['staff_b']
        partner_of[(r['staff_b'], r['swap_date'])] = r['staff_a']

    # 排班: 一次查区间; 某个月还没生成排班时, 用规则兜底(与考勤表一致)
    sched = {}
    for r in db.execute("SELECT date,group_name,shift,is_holiday FROM schedule "
                        "WHERE date BETWEEN ? AND ?", (s_iso, e_iso)):
        sched[(r['date'], r['group_name'])] = (r['shift'], 1 if r['is_holiday'] else 0)

    person_hol = {(r['staff_id'], r['hol_date']) for r in db.execute(
        "SELECT staff_id,hol_date FROM staff_holiday WHERE hol_date BETWEEN ? AND ?",
        (s_iso, e_iso))}

    hours_map = shift_hours_map()
    out = {}
    for sid in sids:
        s = staff.get(sid)
        if not s:
            continue
        hire, leave = s['hire_date'] or '', s['leave_date'] or ''
        for d in span:
            iso = d.isoformat()
            employed = not ((hire and iso < hire) or (leave and iso > leave))
            group = group_on(hist, sid, iso, s['group_name'])
            partner = partner_of.get((sid, iso))
            if partner:                          # 换班当天按对方班组上班型
                group = group_on(hist, partner, iso, group)
            row = sched.get((iso, group))
            shift, hol = row if row else (eff_shift(d, group), 0)
            if (sid, iso) in person_hol:
                hol = 1
            hours = 0.0 if hol else float(hours_map.get(shift, 0.0))
            out[(sid, iso)] = {
                'sid': sid, 'name': s['name'], 'date': iso,
                'w': WEEK_CN[d.weekday()], 'day': d.day, 'month': d.month,
                'group': group, 'shift': shift, 'hours': hours,
                'holiday': bool(hol), 'rest': hours <= 0,
                'employed': employed, 'partner': partner or 0,
            }
    return out


# ============ 页面数据组装 ============
def _adj_bucket(agg, category, exc_type, hours):
    """把一条调整单/异动累加到汇总桶"""
    if category == '出勤':
        agg['work'] += hours
    elif category == '请假':
        if exc_type == COMP_OFF_TYPE:
            agg['compOff'] += hours          # 调休: 有工时冲减, 但不扣薪
        elif (exc_type or '').startswith(PAID_PREFIX):
            agg['paid'] += hours
        elif exc_type == LATE_TYPE:
            agg['lateEr'] += hours
        elif exc_type == ABSENT_TYPE:
            agg['absent'] += hours
        else:
            agg['leave'] += hours
    elif category == '加班':
        agg[{'日常': 'casual', '公休': 'weekly', '法定': 'legal'}.get(exc_type, 'casual')] += hours


def attendance_payload(y, m):
    """月度考勤表: 每人每天的工时/假别/加班, 以及行末汇总

    每格分两步算:
        1) 请假类做冲减: 净工时 = max(计划工时 - 当日扣减, 0)
        2) 加班类做叠加: 单独计入日常/公休/法定, 不占基础工时
    格子里同时带 marks(小字标记), 让人一眼看出这天的 -扣减 / +加班 / 换班。
    班组和班型都按"当天"取: 先看当天所属班组(履历), 再看是否两人换班, 最后叠加个人放假。
    未来日期只给"计划"灰格(班型/放假/换班/预登记请假), 不计工时 → 汇总即"截至今日"。
    """
    sched = month_schedule(y, m)
    days = month_days(y, m)
    prefix = month_prefix(y, m)
    first_iso, last_iso = days[0].isoformat(), days[-1].isoformat()
    today_iso = date.today().isoformat()
    hours_map = shift_hours_map()
    db = get_db()
    # 在职区间与本月有交集的人都要出现(月中入职/离职的人也要算这一段)
    # 白班制(管理组)与倒班制都在册; 只有显式标记"不参与考勤"的人才排除
    staff_list = db.execute(
        "SELECT id,name,group_name,shift_type,hire_date,leave_date FROM staff "
        "WHERE (shift_type IS NULL OR shift_type<>'不参与考勤') "
        "  AND (status='在职' OR (leave_date IS NOT NULL AND leave_date>=?)) "
        "  AND (hire_date IS NULL OR hire_date<=?) "
        "ORDER BY group_name,id", (first_iso, last_iso)).fetchall()

    hist = group_history_map(db)
    fallback = {r['id']: r['group_name'] for r in db.execute("SELECT id,group_name FROM staff")}
    name_of = {r['id']: r['name'] for r in db.execute("SELECT id,name FROM staff")}
    # 换班: 当天互换班次, 双向登记成一张查找表
    partner_of = {}
    for r in db.execute("SELECT * FROM shift_swaps WHERE swap_date LIKE ?", (prefix + '%',)):
        partner_of[(r['staff_a'], r['swap_date'])] = r['staff_b']
        partner_of[(r['staff_b'], r['swap_date'])] = r['staff_a']
    person_hol = {(r['staff_id'], r['hol_date']) for r in db.execute(
        "SELECT staff_id,hol_date FROM staff_holiday WHERE hol_date LIKE ?", (prefix + '%',))}

    # 一人一天可能有多条异动(请假 + 加班)
    excs = defaultdict(list)
    for r in db.execute("SELECT * FROM exceptions WHERE exc_date LIKE ?", (prefix + '%',)):
        excs[(r['staff_id'], r['exc_date'])].append(r)

    day_adjs, month_adjs = defaultdict(list), defaultdict(list)
    for r in db.execute("SELECT * FROM adjustments WHERE ym=?", (prefix,)):
        if r['adj_date']:
            day_adjs[(r['staff_id'], r['adj_date'])].append(r)
        else:
            month_adjs[r['staff_id']].append(r)

    # 班次中文名统一取自 shift_def(新增班型自动有名字, 不用再改这里)
    shift_cn = {code: d['label'] for code, d in shift_defs().items()}

    rows = []
    for s in staff_list:
        cells, agg = [], Counter()
        adjusted = False
        segs, used_groups, employed, plan_total = [], [], 0, 0.0
        hire, leave = s['hire_date'] or '', s['leave_date'] or ''
        for d in days:
            iso = d.isoformat()
            # 入职前 / 离职后: 空白格, 不计任何工时
            if (hire and iso < hire) or (leave and iso > leave):
                why = '尚未入职' if (hire and iso < hire) else '已离职'
                cells.append({'t': '', 'k': 'off', 'm': [],
                              'tip': f'{why}（{hire or leave}）'})
                continue
            employed += 1
            # 当天所属班组: 本人履历 → 若当天换班则取对方班组
            group = group_on(hist, s['id'], iso, s['group_name'])
            partner = partner_of.get((s['id'], iso))
            partner_name = ''
            if partner:
                partner_name = name_of.get(partner, '')
                group = group_on(hist, partner, iso, fallback.get(partner, group))
            sc = sched[(iso, group)]
            shift, hol = sc['shift'], sc['hol']
            self_hol = (s['id'], iso) in person_hol
            if self_hol:
                hol = 1
            shift_hours = hours_map.get(shift, 0.0)
            base = 0.0 if hol else shift_hours
            plan_total += base               # 全月计划工时(含未来), 用于与实际对比

            # 班组分段(用于"班组"列展示与悬停说明) — 未来日期也要分段
            if not segs or segs[-1]['group'] != group:
                segs.append({'group': group, 'from': d.day, 'to': d.day, 'swap': 0})
            else:
                segs[-1]['to'] = d.day
            if partner_name:            # 这一段是换班带出来的临时班型, 展示时标注一下
                segs[-1]['swap'] += 1
            if group not in used_groups:
                used_groups.append(group)

            if iso > today_iso:
                # ---- 未发生: 只显示计划, 不计任何工时 ----
                notes = []
                if partner_name:
                    notes.append(f"换班计划：与{partner_name}互换，上{group}{shift_cn.get(shift, shift)}")
                for e in excs.get((s['id'], iso), []):
                    if e['category'] == '请假':
                        notes.append(f"预登记：{e['exc_type']} {num(float(e['actual_hours'] or 0))}h")
                    elif e['category'] in ('加班', '放假'):
                        notes.append(f"计划{e['category']}：{e['exc_type']} {num(float(e['actual_hours'] or 0))}h")
                marks = [{'v': '换', 's': 'swap'}] if partner_name else []
                glyph = '放' if hol else shift_glyph(shift)
                cells.append({'t': glyph, 'k': 'future', 'm': marks,
                              'tip': '计划 · 未发生' + (' · ' + ' · '.join(notes) if notes else '')})
                continue

            deduct = paid = comp = late = absent = 0.0
            ot = Counter()
            notes = []
            for e in excs.get((s['id'], iso), []):
                h = float(e['actual_hours'] or 0)
                et = e['exc_type'] or ''
                if e['category'] == '请假':
                    deduct += h
                    if et == COMP_OFF_TYPE:
                        comp += h                   # 调休: 冲减计划工时, 但不扣薪
                    elif et.startswith(PAID_PREFIX):
                        paid += h
                    elif et == LATE_TYPE:
                        late += h
                    elif et == ABSENT_TYPE:
                        absent += h
                    notes.append(f'{et} {num(h)}h')
                elif e['category'] in ('加班', '放假'):
                    ot[et or '日常'] += h
                    notes.append(f"{et or '加班'} {num(h)}h")
                else:
                    notes.append(f'{et or e["category"]}')

            extra = 0.0                     # 调整单直接增减的工时
            for a in day_adjs.get((s['id'], iso), []):
                adjusted = True
                h = float(a['hours'] or 0)
                notes.append(f"调整 {a['category']}{'+' if h >= 0 else ''}{num(h)}h")
                if a['category'] == '出勤':
                    extra += h
                elif a['category'] == '请假':
                    deduct += h
                    if (a['exc_type'] or '') == COMP_OFF_TYPE:
                        comp += h
                    elif (a['exc_type'] or '').startswith(PAID_PREFIX):
                        paid += h
                    elif (a['exc_type'] or '') == LATE_TYPE:
                        late += h
                    elif (a['exc_type'] or '') == ABSENT_TYPE:
                        absent += h
                elif a['category'] == '加班':
                    ot[a['exc_type'] or '日常'] += h
            deduct = max(deduct, 0.0)
            net = max(base - deduct, 0.0)
            # 出勤调整: 白天班(白/白8)直接并入当天工时, 其它班型(夜/休)并入本行出勤列
            shown = net + extra if is_day_shift(shift) else net

            ot_total = sum(v for v in ot.values() if v)
            if ot_total < 0:
                ot_total = 0.0

            marks = []
            if partner_name:
                marks.append({'v': '换', 's': 'swap'})
            if base > 0 and deduct > 0 and shown > 0:
                marks.append({'v': '-' + str(num(deduct)), 's': 'leave'})
            elif base == 0 and deduct > 0:
                marks.append({'v': '假' + str(num(deduct)), 's': 'leave'})
            if ot_total > 0:
                marks.append({'v': '+' + str(num(ot_total)), 's': 'ot'})
            if extra:
                marks.append({'v': '调' + ('+' if extra > 0 else '') + str(num(extra)), 's': 'adj'})

            if base > 0 and shown > 0:
                cell = {'t': num(shown), 'k': 'night' if is_night_shift(shift) else 'day'}
            elif base > 0:
                leave_types = [e['exc_type'] for e in excs.get((s['id'], iso), [])
                               if e['category'] == '请假' and e['exc_type']]
                label = leave_types[0].replace(PAID_PREFIX, '') if leave_types else '假'
                cell = {'t': label, 'k': 'leave'}
            elif hol:
                cell = {'t': '放', 'k': 'hol'}
            else:
                cell = {'t': '休', 'k': 'rest'}
            cell['m'] = marks
            if partner_name:
                head = f'换班（与{partner_name}互换，按{group}{shift_cn.get(shift, shift)}）'
            elif hol:
                head = ('个人放假' if self_hol else '放假') + \
                       (f'（原{shift}班 {num(shift_hours)}h）' if shift_hours else '')
            elif shift_hours:
                head = f"{shift_cn.get(shift, shift)} {num(shift_hours)}h"
            elif self_hol:
                head = '个人放假'
            else:
                head = '休息'
            cell['tip'] = ' · '.join([head] + notes)
            cells.append(cell)

            if is_day_shift(shift):
                agg['work'] += shown
            else:
                agg['work'] += extra          # 出勤调整在非白天班日也照常生效
                if is_night_shift(shift) and net > 0:
                    agg['night'] += 1
                    agg['nightH'] += net      # 夜班工时(净出勤), 用于合计
            agg['leave'] += deduct - paid - comp - late - absent
            agg['paid'] += paid
            agg['compOff'] += comp
            agg['lateEr'] += late
            agg['absent'] += absent
            for k in ('casual', 'weekly', 'legal'):
                agg[k] += ot.get({'casual': '日常', 'weekly': '公休', 'legal': '法定'}[k], 0)

        for a in month_adjs.get(s['id'], []):
            adjusted = True
            _adj_bucket(agg, a['category'], a['exc_type'], float(a['hours'] or 0))

        rows.append({
            'id': s['id'], 'name': s['name'],
            'group': '→'.join(used_groups) or s['group_name'],
            'groups': used_groups or [s['group_name']],
            'groupTip': '；'.join(
                (f"{x['from']}日" if x['from'] == x['to'] else f"{x['from']}–{x['to']}日")
                + f" {x['group']}"
                + ('（换班）' if x['swap'] and x['swap'] == x['to'] - x['from'] + 1 else '')
                for x in segs),
            'hireDate': hire, 'leaveDate': leave, 'days': employed,
            'planWork': num(plan_total),
            'cells': cells,
            'work': num(agg['work']), 'night': agg['night'], 'leave': num(max(agg['leave'], 0)),
            'nightH': num(agg['nightH']),
            'total': num(agg['work'] + agg['nightH']),
            'lateEr': num(max(agg['lateEr'], 0)), 'absent': num(max(agg['absent'], 0)),
            'casual': num(agg['casual']), 'weekly': num(agg['weekly']),
            'legal': num(agg['legal']), 'paid': num(agg['paid']),
            'compOff': num(agg['compOff']),
            'ot': num(agg['casual'] + agg['weekly'] + agg['legal']),
            'shiftType': s['shift_type'] or '倒班制',
            'adjusted': adjusted,
        })

    lock = lock_row(y, m)
    adj_list = [{
        'id': r['id'], 'name': r['name'] or '(人员已删除)', 'group': r['group_name'] or '—',
        'date': r['adj_date'] or '整月', 'category': r['category'], 'type': r['exc_type'] or '',
        'hours': num(r['hours']), 'reason': r['reason'] or '',
        'created_at': r['created_at'] or '',
    } for r in db.execute(
        "SELECT a.*, s.name, s.group_name FROM adjustments a "
        "LEFT JOIN staff s ON s.id = a.staff_id WHERE a.ym=? ORDER BY a.id DESC", (prefix,))]

    totals = {
        'staff': len(rows),
        'work': num(sum(r['work'] for r in rows)),
        'nightH': num(sum(r['nightH'] for r in rows)),
        'total': num(sum(r['total'] for r in rows)),
        'planWork': num(sum(r['planWork'] for r in rows)),
        'night': sum(r['night'] for r in rows),
        'leave': num(sum(r['leave'] + r['paid'] + r['lateEr'] + r['absent'] for r in rows)),
        'leaveOnly': num(sum(r['leave'] for r in rows)),
        'paidOnly': num(sum(r['paid'] for r in rows)),
        'lateEr': num(sum(r['lateEr'] for r in rows)),
        'absent': num(sum(r['absent'] for r in rows)),
        'ot': num(sum(r['ot'] for r in rows)),
        'casual': num(sum(r['casual'] for r in rows)),
        'weekly': num(sum(r['weekly'] for r in rows)),
        'legal': num(sum(r['legal'] for r in rows)),
        'compOff': num(sum(r['compOff'] for r in rows)),
        'holiday': sum(1 for d in days if sched[(d.isoformat(), SHIFT_GROUPS[0])]['hol']),
        'adjustments': len(adj_list),
        'upto': today_iso if today_iso <= last_iso else last_iso,
    }
    # 按班制分组: 白班 8h/天 与 倒班 11h/天 混在一起加总会误导(总工时、人均都失真)
    by_type = {}
    for r in rows:
        b = by_type.setdefault(r['shiftType'], {'staff': 0, 'work': 0.0, 'night': 0,
                                                'nightH': 0.0, 'total': 0.0,
                                                'ot': 0.0, 'leave': 0.0, 'compOff': 0.0})
        b['staff'] += 1
        b['work'] += r['work']
        b['night'] += r['night']
        b['nightH'] += r['nightH']
        b['total'] += r['total']
        b['ot'] += r['ot']
        b['leave'] += r['leave'] + r['paid'] + r['lateEr'] + r['absent']
        b['compOff'] += r['compOff']
    for b in by_type.values():
        for k in ('work', 'nightH', 'total', 'ot', 'leave', 'compOff'):
            b[k] = num(b[k])
    return {
        'y': y, 'm': m, 'today': today_iso,
        'groups': GROUPS,
        'days': [day_meta(d, today_iso) for d in days],
        'rows': rows, 'totals': totals, 'byType': by_type,
        'staffOptions': [{'id': s['id'], 'name': s['name'], 'group': s['group_name']}
                         for s in db.execute(
                             "SELECT id,name,group_name FROM staff WHERE status='在职' "
                             "ORDER BY group_name,id")],
        'leaveTypes': LEAVE_TYPES, 'otTypes': list(OT_TYPES), 'adjCategories': ADJ_CATEGORIES,
        'lock': {'locked': lock is not None, 'at': (lock['locked_at'] if lock else '')},
        'adjustments': adj_list,
        'archive': archive_info(y, m),
    }


def schedule_payload(y, m):
    """排班日历 + 三类异动记录(请假/加班/放假) + 换班 + 放假安排 + 班制配置"""
    db = get_db()
    sched = month_schedule(y, m)
    days = month_days(y, m)

    grid, holiday_dates, summary = [], [], []
    for d in days:
        iso = d.isoformat()
        meta = day_meta(d)
        shifts = {gp: sched[(iso, gp)]['shift'] for gp in SHIFT_GROUPS}
        hols = {gp: 1 if sched[(iso, gp)]['hol'] else 0 for gp in SHIFT_GROUPS}
        meta.update({'hol': 1 if all(hols.values()) else 0, 'hols': hols,
                     'someHol': 1 if any(hols.values()) else 0, 'shifts': shifts})
        grid.append(meta)
        # 只收集"标记放假且当天本来要上班"的日期(放·休 不算)
        if any(hols.values()) and any(v in ('白', '夜') for v in shifts.values()):
            holiday_dates.append(iso)
    for gp in SHIFT_GROUPS:
        vals = [sched[(d.isoformat(), gp)]['shift'] for d in days]
        w, n = vals.count('白'), vals.count('夜')
        summary.append({'group': gp, 'day': w, 'night': n, 'rest': len(days) - w - n})

    records = {'请假': [], '加班': [], '放假': []}
    # 只取本月记录; LEFT JOIN: 人员被删除后, 其历史异动记录仍应可见、可删
    for r in db.execute(
            "SELECT e.id, e.exc_date, e.category, e.exc_type, e.planned_hours, e.actual_hours, "
            "       e.multiplier, e.note, COALESCE(s.name, '(人员已删除)') name, s.group_name "
            "FROM exceptions e LEFT JOIN staff s ON e.staff_id = s.id "
            "WHERE e.exc_date LIKE ? "
            "ORDER BY e.exc_date DESC, e.id DESC", (month_prefix(y, m) + '%',)):
        records.setdefault(r['category'], []).append({
            'id': r['id'], 'name': r['name'], 'group': r['group_name'] or '—',
            'date': r['exc_date'], 'type': r['exc_type'],
            'hours': num(r['actual_hours']), 'multiplier': num(r['multiplier']),
            'planned': num(r['planned_hours']), 'note': r['note'] or '',
        })

    # ---- 换班记录: 带上"换完之后各自上什么班"便于核对 ----
    hist = group_history_map(db)
    fallback = {r['id']: r['group_name'] for r in db.execute("SELECT id,group_name FROM staff")}
    swaps = []
    for r in db.execute(
            "SELECT w.*, a.name an, b.name bn FROM shift_swaps w "
            "LEFT JOIN staff a ON a.id=w.staff_a LEFT JOIN staff b ON b.id=w.staff_b "
            "WHERE w.swap_date LIKE ? ORDER BY w.swap_date DESC, w.id DESC",
            (month_prefix(y, m) + '%',)):
        def shift_of(sid):
            sid = sid or 0
            g = group_on(hist, sid, r['swap_date'], fallback.get(sid, ''))
            row = sched.get((r['swap_date'], g))
            return (row['shift'] if row else '休'), g
        a_shift, a_group = shift_of(r['staff_a'])
        b_shift, b_group = shift_of(r['staff_b'])
        swaps.append({
            'id': r['id'], 'date': r['swap_date'],
            'a': r['an'] or '(已删除)', 'b': r['bn'] or '(已删除)',
            'aGroup': a_group, 'bGroup': b_group,
            'aAfter': b_shift, 'bAfter': a_shift,
            'note': r['note'] or '',
        })

    # ---- 放假安排: 班组级(schedule.is_holiday) + 个人级(staff_holiday) ----
    plans = []
    for d in days:
        iso = d.isoformat()
        gs = [gp for gp in SHIFT_GROUPS if sched[(iso, gp)]['hol']]
        if gs:
            plans.append({'kind': 'group', 'date': iso,
                          'scope': '全部班组' if len(gs) == 3 else '、'.join(gs),
                          'groups': gs, 'note': ''})
    for r in db.execute(
            "SELECT h.id, h.hol_date, h.note, COALESCE(s.name,'(已删除)') name "
            "FROM staff_holiday h LEFT JOIN staff s ON s.id=h.staff_id "
            "WHERE h.hol_date LIKE ? ORDER BY h.hol_date DESC, h.id DESC",
            (month_prefix(y, m) + '%',)):
        plans.append({'kind': 'person', 'id': r['id'], 'date': r['hol_date'],
                      'scope': r['name'] + '（个人）', 'groups': [], 'note': r['note'] or ''})
    plans.sort(key=lambda x: x['date'], reverse=True)

    # 异动登记(请假/加班/放假日出勤/按人放假)要覆盖白班制的管理岗, 不再排除;
    # 换班只发生在倒班班组之间, 单独给一份 staffSwap
    staff = [{'id': r['id'], 'name': r['name'], 'group': r['group_name'],
              'type': r['shift_type'] or '倒班制'}
             for r in db.execute(
                 "SELECT id,name,group_name,shift_type FROM staff WHERE status='在职' "
                 "ORDER BY group_name,id")]
    staff_swap = [x for x in staff if x['group'] in SHIFT_GROUPS]

    # ---- 班制配置: 班次定义 + 轮转规则 ----
    shifts = [{'code': r['code'], 'label': r['label'], 'hours': num(r['hours']),
               'crossDay': r['cross_day'] or 0} for r in db.execute(
        "SELECT code,label,hours,cross_day FROM shift_def ORDER BY sort,code")]
    rules = [{'id': r['id'], 'group': r['group_name'], 'cycle': r['cycle'],
              'offset': r['offset'], 'anchor': r['anchor'],
              'validFrom': r['valid_from'], 'validTo': r['valid_to'] or '',
              'note': r['note'] or ''} for r in db.execute(
        "SELECT * FROM rot_rule ORDER BY valid_from DESC, id DESC")]

    lock = lock_row(y, m)
    return {
        'y': y, 'm': m, 'today': date.today().isoformat(),
        'groups': SHIFT_GROUPS,
        'days': [{'iso': g['iso'], 'day': g['day'], 'w': g['w']} for g in grid],
        'grid': grid, 'summary': summary, 'staff': staff, 'staffSwap': staff_swap,
        'holidayDates': holiday_dates,
        'leaveTypes': LEAVE_TYPES, 'otTypes': list(OT_TYPES), 'holidayTypes': HOLIDAY_TYPES,
        'records': records, 'swaps': swaps, 'holidayPlans': plans,
        'shiftConfig': {'shifts': shifts, 'rules': rules},
        'lock': {'locked': lock is not None, 'at': (lock['locked_at'] if lock else '')},
    }


def staff_payload():
    db = get_db()
    rows = db.execute(
        "SELECT id,name,badge_id,gender,position,group_name,status,report_to,photo,"
        "       cloth_size,shoe_size,helmet_size,shift_type,hire_date,leave_date,age "
        "FROM staff ORDER BY id").fetchall()
    name_of = {r['id']: r['name'] for r in rows}
    members = []
    for gp in GROUPS:
        lst = [{
            'id': r['id'], 'name': r['name'], 'badge': r['badge_id'] or '',
            'gender': r['gender'] or '', 'position': r['position'] or '',
            'group': r['group_name'], 'status': r['status'] or '在职',
            'reportTo': r['report_to'], 'reportName': name_of.get(r['report_to'], ''),
            'photo': r['photo'] or '', 'cloth': r['cloth_size'] or '',
            'shoe': r['shoe_size'] or '', 'helmet': r['helmet_size'] or '',
            'shift': r['shift_type'] or '倒班制',
            'hireDate': r['hire_date'] or '', 'leaveDate': r['leave_date'] or '',
            'age': r['age'],
            'history': [],
        } for r in rows if r['group_name'] == gp]
        members.append({'group': gp, 'list': lst})
    # 履历明细(含变更类型/备注), 单独查一次, 结构简单
    logs = defaultdict(list)
    for r in db.execute(
            "SELECT staff_id,group_name,start_date,end_date,change_type,note "
            "FROM staff_group_log ORDER BY staff_id,start_date"):
        logs[r['staff_id']].append({
            'group': r['group_name'], 'start': r['start_date'] or '',
            'end': r['end_date'] or '', 'type': r['change_type'] or '调组',
            'note': r['note'] or '',
        })
    for mbr in members:
        for s in mbr['list']:
            s['history'] = logs.get(s['id'], [])
    reporters = [{'id': r['id'], 'name': r['name'], 'position': r['position']}
                 for r in rows if r['status'] == '在职' and r['position']
                 and any(p in r['position'] for p in REPORT_POSITIONS)]
    return {'groups': GROUPS, 'members': members, 'reporters': reporters,
            'today': date.today().isoformat()}


def attendance_xlsx_bytes(y, m):
    """整页导出月度考勤表(xlsx 字节流): 31 天明细 + 汇总列 + 合计行 + 调整单附页"""
    p = attendance_payload(y, m)
    days, rows, totals = p['days'], p['rows'], p['totals']
    n_fixed, n_day, n_sum = 3, len(days), 10
    last_col = n_fixed + n_day + n_sum

    wb = Workbook()
    ws = wb.active
    ws.title = f'{y}-{m:02d}'

    thin = Side(style='thin', color='D9E1E1')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center', wrap_text=False)
    head_fill = PatternFill('solid', fgColor='EDF3F1')
    wk_fill = PatternFill('solid', fgColor='F4F6F6')
    fills = {'day': PatternFill('solid', fgColor='EEF5FB'),
             'night': PatternFill('solid', fgColor='F1ECFE'),
             'leave': PatternFill('solid', fgColor='FDEBF3'),
             'ot': PatternFill('solid', fgColor='FFF1E6'),
             'hol': PatternFill('solid', fgColor='FDE7E7')}
    colors = {'day': '185FA5', 'night': '5B3FD6', 'leave': 'BE185D',
              'ot': 'C2410C', 'hol': 'C0392B', 'rest': 'A6AFBE', 'future': 'B7C0CC'}

    # 标题 + 说明
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    t = ws.cell(row=1, column=1, value=f'{y} 年 {m} 月  月度考勤表')
    t.font = Font(size=15, bold=True)
    t.alignment = center
    ws.row_dimensions[1].height = 30

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    lock_txt = (f"已月结锁定（{p['lock']['at']}）" if p['lock']['locked'] else '未锁定')
    note = (f'工时单位：小时（h）；合计 = 白班工时 + 夜班工时（夜班按班次标准 11.5h 计），'
            f'夜班列本身为班次数。格内 -x 为当日请假扣减，+x 为当日加班/'
            f'放假日出勤。汇总截至今日（{totals["upto"]}），灰格为未发生的计划。'
            f'月结状态：{lock_txt}')
    n = ws.cell(row=2, column=1, value=note)
    n.font = Font(size=9, color='5F6B7A')
    n.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[2].height = 18

    # 表头
    head_row = 3
    heads = ['序号', '姓名', '班组'] + [f"{d['day']}\n{d['w']}" for d in days] + \
            ['合计', '夜班', '事假', '早/退', '旷工', '调休', '日常', '公休', '法定', '带薪']
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=head_row, column=i, value=h)
        c.font = Font(size=9, bold=True, color='374151')
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text='\n' in h)
        c.fill = head_fill
        c.border = border
    for i, d in enumerate(days, start=n_fixed + 1):
        if d['weekend']:
            ws.cell(row=head_row, column=i).fill = wk_fill
    ws.row_dimensions[head_row].height = 26

    # 数据行
    r0 = head_row + 1
    for idx, row in enumerate(rows):
        r = r0 + idx
        vals = [idx + 1, row['name'], row['group']]
        for cell in row['cells']:
            txt = str(cell['t'])
            if cell.get('m'):
                txt += '(' + ' '.join(mk['v'] for mk in cell['m']) + ')'
            vals.append(txt)
        vals += [row['total'], row['night'], row['leave'], row['lateEr'], row['absent'],
                 row['compOff'], row['casual'], row['weekly'], row['legal'], row['paid']]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.border = border
            c.alignment = center
            c.font = Font(size=9)
        for i, cell in enumerate(row['cells']):
            c = ws.cell(row=r, column=n_fixed + 1 + i)
            if cell['k'] in fills:
                c.fill = fills[cell['k']]
            if cell['k'] in colors:
                c.font = Font(size=9, color=colors[cell['k']])
        # 汇总列加粗数值
        for j in range(n_sum):
            ws.cell(row=r, column=n_fixed + n_day + 1 + j).font = Font(size=9, bold=True)
        # 有调整单的行: 姓名后加标记
        if row.get('adjusted'):
            ws.cell(row=r, column=2).value = row['name'] + ' *'

    # 合计行
    total_row = r0 + len(rows)
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=3)
    c = ws.cell(row=total_row, column=1, value=f"合计（{totals['staff']} 人，截至 {totals['upto']}）")
    c.font = Font(size=9, bold=True)
    c.alignment = center
    c.fill = head_fill
    for i in range(1, last_col + 1):
        ws.cell(row=total_row, column=i).border = border
        ws.cell(row=total_row, column=i).fill = head_fill
    sums = [totals['total'], totals['night'], totals['leaveOnly'], totals['lateEr'],
            totals['absent'], totals['compOff'], totals['casual'], totals['weekly'],
            totals['legal'], totals['paidOnly']]
    for j, val in enumerate(sums):
        c = ws.cell(row=total_row, column=n_fixed + n_day + 1 + j, value=val)
        c.font = Font(size=9, bold=True)
        c.alignment = center

    # 列宽 / 冻结 / 打印
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 11
    ws.column_dimensions['C'].width = 11   # 可能出现「甲班→乙班」
    for i in range(n_fixed + 1, n_fixed + n_day + 1):
        ws.column_dimensions[get_column_letter(i)].width = 4.6
    for i in range(n_fixed + n_day + 1, last_col + 1):
        ws.column_dimensions[get_column_letter(i)].width = 6.2
    ws.freeze_panes = 'D4'
    ws.print_title_rows = '3:3'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    # 调整单附页
    if p['adjustments']:
        ws2 = wb.create_sheet('调整单')
        heads2 = ['日期', '员工', '班组', '类别', '类型', '调整工时', '原因', '登记时间']
        for i, h in enumerate(heads2, start=1):
            c = ws2.cell(row=1, column=i, value=h)
            c.font = Font(size=10, bold=True)
            c.fill = head_fill
            c.border = border
            c.alignment = center
        for idx, a in enumerate(p['adjustments'], start=2):
            vals = [a['date'], a['name'], a['group'], a['category'], a['type'],
                    a['hours'], a['reason'], a['created_at']]
            for i, v in enumerate(vals, start=1):
                c = ws2.cell(row=idx, column=i, value=v)
                c.font = Font(size=10)
                c.border = border
                c.alignment = Alignment(vertical='center', wrap_text=(i == 7))
        for i, w in enumerate([12, 12, 8, 8, 16, 10, 36, 18], start=1):
            ws2.column_dimensions[get_column_letter(i)].width = w
        ws2.freeze_panes = 'A2'

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_attendance(y, m):
    """下载用: 直接返回 xlsx 附件"""
    return send_file(
        io.BytesIO(attendance_xlsx_bytes(y, m)), as_attachment=True,
        download_name=f'月度考勤表_{y}-{m:02d}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ============ 结算归档 ============
def archive_month(y, m, operator='admin'):
    """月结归档: 把当月"当时算出来的结果"落成只读文件包, 供审计/纠纷回溯

    产出 archive/YYYY-MM[_vN]/ 下三份文件:
        月度考勤表_YYYY-MM.xlsx   给财务/审计看的结算表(与页面导出一致)
        snapshot.json            明细 + 汇总 + 异动 + 调整单 + 当时的班制配置
        meta.txt                 人读摘要(锁定时间/口径/条数/校验值)
    每次归档版本号 +1, 历史版本全部保留, 不覆盖 —— 追溯要的就是"当时那个数"。
    """
    p = attendance_payload(y, m)
    ym = month_prefix(y, m)
    db = get_db()
    ver = (db.execute("SELECT COALESCE(MAX(ver), 0) FROM month_archive WHERE ym=?",
                      (ym,)).fetchone()[0] or 0) + 1
    name = ym if ver == 1 else f'{ym}_v{ver}'
    folder = os.path.join(C.archive_dir(), name)
    os.makedirs(folder, exist_ok=True)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1) 结算表
    xlsx_path = os.path.join(folder, f'月度考勤表_{ym}.xlsx')
    with open(xlsx_path, 'wb') as f:
        f.write(attendance_xlsx_bytes(y, m))

    # 2) 快照(含当时口径, 日后口径变了也能解释这笔数是怎么来的)
    excs = [{
        'id': r['id'], 'staff_id': r['staff_id'], 'date': r['exc_date'],
        'category': r['category'], 'type': r['exc_type'] or '',
        'hours': num(r['actual_hours']), 'note': r['note'] or '',
    } for r in db.execute("SELECT * FROM exceptions WHERE exc_date LIKE ? ORDER BY exc_date, id",
                          (ym + '%',))]
    cfg = {
        'shift_def': [dict(r) for r in db.execute(
            "SELECT code,label,hours,cross_day FROM shift_def ORDER BY sort, code")],
        'rot_rule': [dict(r) for r in db.execute(
            "SELECT group_name,cycle,offset,anchor,valid_from,valid_to FROM rot_rule "
            "ORDER BY group_name, valid_from")],
    }
    snap = {
        'ym': ym, 'version': ver, 'archived_at': now, 'operator': operator,
        'locked_at': p['lock']['at'], 'totals': p['totals'],
        'days': p['days'], 'config': cfg, 'exceptions': excs,
        'adjustments': p['adjustments'],
        'rows': [{'id': r['id'], 'name': r['name'], 'group': r['group'],
                  'groups': r.get('groups'), 'planWork': r['planWork'],
                  'work': r['work'], 'night': r['night'],
                  'nightH': r['nightH'], 'total': r['total'],
                  'lateEr': r['lateEr'], 'absent': r['absent'],
                  'leave': r['leave'], 'paid': r['paid'], 'ot': r['ot'],
                  'casual': r['casual'], 'weekly': r['weekly'],
                  'legal': r['legal'], 'compOff': r['compOff'],
                  'cells': [None if c is None else
                            {'t': c['t'], 'k': c['k'],
                             'm': [x['v'] for x in c.get('m') or []],
                             'tip': c.get('tip', '')} for c in r['cells']]}
                 for r in p['rows']],
    }
    json_path = os.path.join(folder, 'snapshot.json')
    io.open(json_path, 'w', encoding='utf-8').write(
        json.dumps(snap, ensure_ascii=False, indent=1))

    # 3) 人读摘要
    t = p['totals']
    meta_path = os.path.join(folder, 'meta.txt')
    io.open(meta_path, 'w', encoding='utf-8').write('\n'.join([
        f'{y} 年 {m} 月  结算归档（第 {ver} 版）',
        f'归档时间: {now}',
        f'月结锁定: {"是，锁定于 " + p["lock"]["at"] if p["lock"]["locked"] else "否（未锁定的归档仅供预览）"}',
        f'在岗人数: {t["staff"]} 人',
        f'出勤工时合计: {t["total"]} h（白班 {t["work"]} + 夜班 {t["nightH"]}；截至 {t["upto"]}，'
        f'全月计划 {t["planWork"]} h）',
        f'夜班班次: {t["night"]} 次',
        f'请假合计: {t["leave"]} h（事假 {t["leaveOnly"]} / 带薪 {t["paidOnly"]}）',
        f'加班及放假日出勤: {t["ot"]} h（日常 {t["casual"]} / 公休 {t["weekly"]} / 法定 {t["legal"]}）',
        f'调整单: {t["adjustments"]} 笔',
        f'异动记录: {len(excs)} 条',
        '',
        '口径: 净出勤 = max(计划工时 - 当日请假扣减, 0)。请假/迟到早退/旷工为冲减类，',
        '      加班/放假日出勤为叠加类，不占基础工时。未来日期只显示计划，不计工时。',
        f'明细见 snapshot.json；结算表见 月度考勤表_{ym}.xlsx。',
    ]) + '\n')

    db.execute(
        "INSERT INTO month_archive(ym,ver,dir,xlsx,json,meta,staff_cnt,work,ot,leave_h,"
        "operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (ym, ver, folder, xlsx_path, json_path, meta_path, t['staff'], t['work'],
         t['ot'], t['leave'], operator, now))
    db.commit()
    return {'ym': ym, 'ver': ver, 'dir': folder, 'at': now,
            'xlsx': xlsx_path, 'json': json_path}


def archive_info(y, m):
    """当月归档概要(取最新一版), 供页面显示"""
    row = get_db().execute(
        "SELECT * FROM month_archive WHERE ym=? ORDER BY ver DESC LIMIT 1",
        (month_prefix(y, m),)).fetchone()
    if not row:
        return {'archived': False}
    return {'archived': True, 'ver': row['ver'], 'at': row['created_at'] or '',
            'staff': row['staff_cnt'], 'work': num(row['work']),
            'xlsx': bool(row['xlsx'] and os.path.exists(row['xlsx']))}
