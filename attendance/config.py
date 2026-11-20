# -*- coding: utf-8 -*-
"""全局常量 + 数据库路径 + 班次/轮转配置

班制的唯一事实来源在这里:
    shift_def  班次定义表   班次码 / 名称 / 计划工时 / 是否跨天
    rot_rule   轮转规则表   班组 / 周期(逗号分隔班次码) / 偏移 / 锚点 / 生效区间

base_shift() 按"生效区间内最新一条规则"取理论班型; 没有规则时退回内置默认
(旧 6 天周期), 保证空库/未播种时系统仍然能跑。改节奏(四班三倒、常白班、
临时调周期)只需要插一条新规则, 不用动代码。
"""
import os
import sqlite3
from datetime import date

from flask import g

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录: 归入 workweb/data —— 数据库统一放 data/，备份/归档在其子目录
#   workweb/data/
#       attendance.db          主库
#       attendance_backups\    每日快照(30 份) + 结算归档(按月份版本)
# 换机器/沙箱/回归副本时可用环境变量 ATT_DATA_DIR 覆盖, 不改代码
DATA_DIR = os.path.abspath(os.environ.get('ATT_DATA_DIR') or os.path.join(BASE_DIR, 'data'))
DB = os.path.join(DATA_DIR, 'attendance.db')
BACKUP_DIR = os.path.join(DATA_DIR, 'attendance_backups')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'att', 'photos')  # 工牌照片: static/att/photos/


def archive_dir():
    """结算归档根目录: 跟着库走(回归脚本切到临时库时, 归档也落在临时目录)"""
    return os.path.join(BACKUP_DIR, 'archive')

# ============ 业务常量 ============
GROUPS = ['甲班', '乙班', '丙班', '管理']             # 三班 + 管理岗
SHIFT_GROUPS = ['甲班', '乙班', '丙班']               # 参与轮班的班组
WHITE_GROUPS = ['管理']                              # 常白班(周一到周五 8h)班组, 受节假日日历影响
WHITE_DAY_CODE = '白8'                               # 常白班班次码: 8h / 不跨天
CYCLE = ['休', '休', '白', '白', '夜', '夜']          # 默认 6 天循环周期(播种/兜底用)
GROUP_OFFSET = {'甲班': 0, '乙班': 4, '丙班': 2}       # 默认三班错开偏移(兜底用)
REPORT_POSITIONS = ('班长', '车间主任')               # 可作为汇报对象的职位
LEAVE_TYPES = ['事假', '带薪假-病假', '带薪假-婚假', '带薪假-丧假', '带薪假-产假',
               '带薪假-工伤', '带薪假-年休', '调休', '迟到早退', '旷工']
OT_TYPES = {'日常': 1.0, '公休': 2.0, '法定': 3.0}     # 加班类型 → 倍率
# 倍率只作分类标记(存 exceptions.multiplier), 不参与工时乘法;
# 工资核算时按 日常/公休/法定 三档各自的小时数自行套倍率。
COMP_OFF_TYPE = '调休'        # 加班换来的休息: 冲减当天计划工时, 但不扣薪, 汇总单列
LATE_TYPE = '迟到早退'        # 考勤表单列展示
ABSENT_TYPE = '旷工'          # 考勤表单列展示
HOLIDAY_TYPES = ['日常', '公休', '法定']              # 放假日出勤的类型（日常 1 / 公休 2 / 法定 3 倍）
ADJ_CATEGORIES = ['出勤', '请假', '加班']             # 月结后调整单的类别
PAID_PREFIX = '带薪假-'
DEFAULT_STAFF_PER_GROUP = 17
WEEK_CN = '一二三四五六日'
PHOTO_EXT = ('.jpg', '.jpeg', '.png', '.gif')
SHIFT_HOURS_FALLBACK = {'白': 11.0, '夜': 11.5}       # shift_def 表为空时的兜底


def set_db(path):
    """切换数据库路径(回归脚本在数据库副本上跑测试时用)"""
    global DB
    DB = path


def get_db():
    if 'att_db' not in g:
        # timeout: 多人同时录入时等待写锁, 避免直接抛 database is locked
        g.att_db = sqlite3.connect(DB, timeout=10)
        g.att_db.row_factory = sqlite3.Row
        g.att_db.execute("PRAGMA foreign_keys=ON")
        g.att_db.execute("PRAGMA busy_timeout=5000")
        g.att_db.execute("PRAGMA synchronous=NORMAL")
    return g.att_db


# ============ 班次定义 (shift_def) ============
def shift_defs():
    """{班次码: {hours, cross_day, label}}; 单次请求内缓存

    班次的"属性"统一从这里取, 不在代码里硬编码 '白' / '夜' 字面量 ——
    这样将来再加 白8(常白班) / 中班 / 四班两倒 等班型, 计算逻辑不用改。
    """
    if '_shift_defs' not in g:
        rows = get_db().execute("SELECT code,label,hours,cross_day FROM shift_def").fetchall()
        m = {r['code']: {'hours': float(r['hours'] or 0),
                         'cross_day': int(r['cross_day'] or 0),
                         'label': r['label'] or r['code']} for r in rows}
        if not m:                       # 空表兜底(未播种)
            m = {k: {'hours': v, 'cross_day': 1 if k == '夜' else 0, 'label': k}
                 for k, v in SHIFT_HOURS_FALLBACK.items()}
            m['休'] = {'hours': 0.0, 'cross_day': 0, 'label': '休息'}
        g._shift_defs = m
    return g._shift_defs


def shift_hours_map():
    """{班次码: 计划工时}"""
    return {k: v['hours'] for k, v in shift_defs().items()}


def shift_hours(code):
    return shift_defs().get(code, {}).get('hours', 0.0)


def is_night_shift(code):
    """跨天班次(夜班): 出勤按"班次数"统计, 不累加白天工时"""
    return bool(shift_defs().get(code, {}).get('cross_day', 0))


def is_day_shift(code):
    """白天班(白 / 白8 / 常白): 有计划工时且不跨天 → 计入出勤工时"""
    d = shift_defs().get(code)
    return bool(d) and d['hours'] > 0 and not d['cross_day']


# 考勤格内只放一个字(班型全名放悬停提示), 避免"白8"把日期列撑宽
SHIFT_GLYPH = {WHITE_DAY_CODE: '白'}


def shift_glyph(code):
    return SHIFT_GLYPH.get(code, code)


# ============ 轮转规则 (rot_rule) ============
def rotation_rules():
    """{班组: [rule...]} 同班组按生效日倒序; 单次请求内缓存"""
    if '_rot_rules' not in g:
        rules = {}
        for r in get_db().execute(
                "SELECT group_name, cycle, offset, anchor, valid_from, valid_to "
                "FROM rot_rule ORDER BY valid_from DESC, id DESC"):
            rules.setdefault(r['group_name'], []).append(r)
        g._rot_rules = rules
    return g._rot_rules


def parse_cycle(raw):
    """'休,休,白,白,夜,夜' / '休休白白夜夜' → ['休','休','白','白','夜','夜']"""
    raw = (raw or '').strip().replace('，', ',')
    if ',' in raw:
        return [x.strip() for x in raw.split(',') if x.strip()]
    return list(raw)


def rule_shift(rule, d):
    """按规则算某天的班型: (d-锚点) 对周期长度取模, 再加班组偏移"""
    codes = parse_cycle(rule['cycle'])
    if not codes:
        return ''
    try:
        anchor = date.fromisoformat(str(rule['anchor'])[:10])
    except (TypeError, ValueError):
        return ''
    pos = ((d - anchor).days % len(codes) + len(codes)) % len(codes)
    try:
        off = int(rule['offset'] or 0)
    except (TypeError, ValueError):
        off = 0
    return codes[(pos + off) % len(codes)]


def rule_covers(rule, iso):
    return (rule['valid_from'] or '') <= iso and \
           (not rule['valid_to'] or rule['valid_to'] >= iso)


# ============ 法定节假日日历 (holiday_calendar) ============
def holiday_map():
    """{iso: kind}; kind='法定'(放假) / '调休上班'(补班)。全年几十条, 一次全取"""
    if '_holiday_map' not in g:
        try:
            rows = get_db().execute("SELECT date, kind FROM holiday_calendar").fetchall()
            g._holiday_map = {r['date']: (r['kind'] or '') for r in rows}
        except sqlite3.OperationalError:      # 老库还没建表
            g._holiday_map = {}
    return g._holiday_map


def holiday_kind(d):
    """某天的日历性质: '法定' / '调休上班' / ''(普通日子)"""
    return holiday_map().get(d.isoformat(), '')


def base_shift(d, group):
    """理论班型, 优先级: 节假日日历(仅常白班) > 轮转规则 > 兜底常量

    日历只作用于 WHITE_GROUPS: 倒班制的班型由周期决定, 与星期几/节假日无关,
    他们的法定节假日出勤靠人工登记加班类型区分, 不能被日历强行改成"休"。
    """
    if group in WHITE_GROUPS:
        kind = holiday_kind(d)
        if kind == '法定':
            return '休'
        if kind == '调休上班':
            return WHITE_DAY_CODE
    for r in rotation_rules().get(group, ()):
        if rule_covers(r, d.isoformat()):
            s = rule_shift(r, d)
            if s:
                return s
    # 兜底: 未播种/规则缺失时按旧常量, 保证系统不空转
    if group == '管理':
        return '白'
    off = GROUP_OFFSET.get(group)
    if off is None:
        return '休'
    row = get_db().execute("SELECT value FROM settings WHERE key='anchor_date'").fetchone()
    anchor = date.fromisoformat(row['value']) if row else date.today()
    return CYCLE[((d - anchor).days % 6 + off) % 6]


def eff_shift(d, group):
    """有效班型: 优先取手动覆盖, 否则理论班型"""
    row = get_db().execute("SELECT shift FROM schedule WHERE date=? AND group_name=?",
                           (d.isoformat(), group)).fetchone()
    return row['shift'] if row else base_shift(d, group)


def planned_hours(d, group):
    """计划工时: 来自班次定义(白 11h / 夜 11.5h 出厂默认)"""
    return shift_hours(eff_shift(d, group))
