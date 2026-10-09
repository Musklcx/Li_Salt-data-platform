# -*- coding: utf-8 -*-
"""
锂金属平衡 · 期末盘点蓝图（移植自 D:/MyWork/Flask/Metalbalance/metalbalance/app.py）
-------------------------------------------------
- 库：data/db_balance.db（balance 日数据 + inventory 盘点明细 + periods 会计周期）
- 接口：/inventory 页面、/api/state 聚合、/api/rows 明细增删改、
       /api/unlock 解锁编辑、/api/periods 周期管理、/api/import 盘点表导入
- 解锁编辑密码：admin888（内网平台沿用原项目设定）
"""
import os
import sqlite3
from datetime import datetime
from flask import Blueprint, render_template, request, g
import openpyxl
from resp import ok, fail

inventory_bp = Blueprint('inventory', __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'db_balance.db')
TEMPLATE_XLSX = os.path.join(BASE_DIR, 'data', '金属平衡模板.xlsx')

DEFAULT_MONTH = '2026-08'
EDIT_PASSWORD = 'admin888'


# ---------- DB ----------
def get_db():
    if 'inv_db' not in g:
        g.inv_db = sqlite3.connect(DB_PATH)
        g.inv_db.row_factory = sqlite3.Row
        g.inv_db.execute('PRAGMA foreign_keys = ON')
    return g.inv_db


@inventory_bp.teardown_request
def close_inv_db(_exc=None):
    db = g.pop('inv_db', None)
    if db is not None:
        db.close()


def init_inventory_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equip_no TEXT,
        equip_name TEXT,
        data_type TEXT,
        radius REAL,
        height REAL,
        volume REAL,
        concentration REAL,
        metal REAL,
        sort_order INTEGER,
        period TEXT,
        in_ending INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS periods (
        month TEXT PRIMARY KEY,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL
    );
    ''')
    cols = [r[1] for r in db.execute("PRAGMA table_info(inventory)").fetchall()]
    if 'period' not in cols:
        db.execute("ALTER TABLE inventory ADD COLUMN period TEXT DEFAULT '2026-08'")
    if 'in_ending' not in cols:
        db.execute("ALTER TABLE inventory ADD COLUMN in_ending INTEGER DEFAULT 0")
    db.execute("UPDATE inventory SET period='2026-08' WHERE period IS NULL OR period=''")
    n_p = db.execute("SELECT COUNT(*) FROM periods").fetchone()[0]
    if n_p == 0:
        db.execute("INSERT OR IGNORE INTO periods (month, start_date, end_date) VALUES ('2026-08','2026/7/31','2026/8/30')")
    db.commit()
    n = db.execute('SELECT COUNT(*) FROM inventory').fetchone()[0]
    if n == 0 and os.path.exists(TEMPLATE_XLSX):
        _import_inventory_xlsx(db, TEMPLATE_XLSX, DEFAULT_MONTH)
    db.close()


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ('', '\\', '/', '-', '—'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _compute_in_ending(name, dtype):
    name = name or ''
    special = ['期初', '损失', '外售', '投入金属量', '外售金属量', '直收率']
    if dtype == 'SQLite':
        return 0
    if any(k in name for k in special):
        return 0
    return 1


def _import_inventory_xlsx(db, path, period):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for r in range(2, ws.max_row + 1):
        no = ws.cell(r, 1).value
        name = ws.cell(r, 2).value
        dtype = ws.cell(r, 3).value
        if name is None or str(name).strip() == '':
            continue
        if dtype and '直收率' in str(dtype):
            continue
        if no is None and dtype is None:
            continue
        name_s = str(name).strip()
        dtype_s = str(dtype).strip() if dtype else ''
        rows.append((
            str(no) if no is not None else '',
            name_s,
            dtype_s,
            _to_float(ws.cell(r, 4).value),
            _to_float(ws.cell(r, 5).value),
            _to_float(ws.cell(r, 6).value),
            _to_float(ws.cell(r, 7).value),
            _to_float(ws.cell(r, 8).value),
            r,
            period,
            _compute_in_ending(name_s, dtype_s),
        ))
    db.execute('DELETE FROM inventory WHERE period=?', (period,))
    db.executemany(
        'INSERT INTO inventory (equip_no, equip_name, data_type, radius, height, volume, concentration, metal, sort_order, period, in_ending) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        rows)
    db.commit()
    return len(rows)


# ---------- 聚合 ----------
def _date_parts(v):
    """把日期串拆成 [年,月,日]，兼容 2026/7/31 与 2026-07-31 两种格式"""
    s = str(v).strip().replace('-', '/')
    return [int(p) for p in s.split('/') if p != '']


def _date_le(a, b):
    return _date_parts(a) <= _date_parts(b)


def _get_period_range(db, month):
    row = db.execute('SELECT start_date, end_date FROM periods WHERE month=?', (month,)).fetchone()
    if row:
        return row['start_date'], row['end_date']
    return None, None


def aggregate_balance(db, month):
    start, end = _get_period_range(db, month)
    cur = db.execute('SELECT * FROM balance')
    input_metal = 0.0
    sale_metal = 0.0
    days = 0
    bai_vol = bai_metal = 0.0
    ye_vol = ye_metal = 0.0
    sale_t_total = 0.0
    daily = []
    keys = None
    for row in cur:
        if keys is None:
            keys = row.keys()
        d = str(row['日期']).strip()
        if start and not _date_le(start, d):
            continue
        if end and _date_le(d, end) is False:
            continue
        w_vol = float(row['投入气浮量白m³'] or 0)
        w_conc = float(row['气浮含量白g/L'] or 0)
        n_vol = float(row['投入气浮量夜m³'] or 0)
        n_conc = float(row['气浮含量夜g/L'] or 0)
        sale_t = float(row['外卖硫酸锂t'] or 0)
        sale_pct = float(row['硫酸锂含量%'] or 0)
        w_m = w_vol * w_conc / 1000
        n_m = n_vol * n_conc / 1000
        li2so4_m = sale_t * sale_pct / 100
        li2co3_m = float(row['碳酸锂金属量'] or 0) if '碳酸锂金属量' in keys else 0.0
        na2so4_m = float(row['硫酸钠金属锂'] or 0) if '硫酸钠金属锂' in keys else 0.0
        s_m = li2so4_m + li2co3_m + na2so4_m
        bai_vol += w_vol
        bai_metal += w_m
        ye_vol += n_vol
        ye_metal += n_m
        sale_t_total += sale_t
        input_metal += w_m + n_m
        sale_metal += li2so4_m
        daily.append({'date': d, 'input': round(w_m + n_m, 4), 'sale': round(s_m, 4),
                      'li2so4': round(li2so4_m, 4), 'li2co3': round(li2co3_m, 4), 'na2so4': round(na2so4_m, 4)})
        days += 1
    return {
        'input_metal': round(input_metal, 4),
        'sale_metal': round(sale_metal, 4),
        'days': days,
        'bai_vol': round(bai_vol, 3), 'bai_metal': round(bai_metal, 4),
        'ye_vol': round(ye_vol, 3), 'ye_metal': round(ye_metal, 4),
        'sale_t': round(sale_t_total, 3), 'sale_pct_metal': round(sale_metal, 4),
        'daily': daily,
    }


def list_months(db):
    rows = db.execute('SELECT month FROM periods ORDER BY month').fetchall()
    return [r['month'] for r in rows]


def summarize_inventory(db, period=None):
    if period:
        rows = db.execute('SELECT * FROM inventory WHERE period=? ORDER BY sort_order, id', (period,)).fetchall()
    else:
        rows = db.execute('SELECT * FROM inventory ORDER BY sort_order, id').fetchall()
    items = [dict(r) for r in rows]
    ending = 0.0
    opening = 0.0
    loss = 0.0
    sold_li2co3 = 0.0
    sold_na2so4 = 0.0
    for it in items:
        m = it['metal'] or 0
        nm = it['equip_name'] or ''
        if it.get('in_ending'):
            ending += m
        if '期初' in nm:
            opening += m
        elif '损失' in nm:
            loss += m
        elif '碳酸锂外售' in nm:
            sold_li2co3 += m
        elif '硫酸钠外售' in nm:
            sold_na2so4 += m
    return {
        'items': items,
        'ending': round(ending, 4),
        'opening': round(opening, 4),
        'loss': round(loss, 4),
        'sold_li2co3': round(sold_li2co3, 4),
        'sold_na2so4': round(sold_na2so4, 4),
    }


# ---------- 路由 ----------
@inventory_bp.route('/inventory')
def inventory_page():
    
    """期末金属量盘点页面"""
    return render_template('inventory.html')


@inventory_bp.route('/api/state')
def api_state():
    
    """盘点状态与月度趋势（含桑基图数据）"""
    month = request.args.get('month', '') or DEFAULT_MONTH
    db = get_db()
    bal = aggregate_balance(db, month)
    inv = summarize_inventory(db, month)
    total_sold = bal['sale_metal'] + inv['sold_li2co3'] + inv['sold_na2so4']
    denom = inv['opening'] + bal['input_metal'] - inv['ending']
    yield_rate = (total_sold / denom) if denom > 0 else 0
    balance_diff = inv['opening'] + bal['input_metal'] - inv['ending'] - total_sold - inv['loss']
    return ok({
        'month': month,
        'months': list_months(db),
        'db_balance': bal,
        'inventory': inv['items'],
        'summary': {
            'opening': inv['opening'],
            'input': bal['input_metal'],
            'ending': inv['ending'],
            'sale': bal['sale_metal'],
            'sold_li2co3': inv['sold_li2co3'],
            'sold_na2so4': inv['sold_na2so4'],
            'loss': inv['loss'],
            'total_sold': round(total_sold, 4),
            'yield': round(yield_rate, 4),
            'balance_diff': round(balance_diff, 4),
        },
    })


@inventory_bp.route('/api/rows', methods=['POST'])
def api_add_row():
    
    """新增盘点明细行"""
    d = request.get_json(force=True)
    db = get_db()
    period = d.get('period') or DEFAULT_MONTH
    in_ending = d.get('in_ending')
    if in_ending is None:
        in_ending = _compute_in_ending(d.get('equip_name', ''), d.get('data_type', ''))
    cur = db.execute(
        'INSERT INTO inventory (equip_no, equip_name, data_type, radius, height, volume, concentration, metal, sort_order, period, in_ending) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (d.get('equip_no', ''), d.get('equip_name', ''), d.get('data_type', ''),
         d.get('radius'), d.get('height'), d.get('volume'), d.get('concentration'),
         d.get('metal'), 9999, period, 1 if in_ending else 0))
    db.commit()
    return ok({'id': cur.lastrowid})


@inventory_bp.route('/api/rows/<int:rid>', methods=['PUT'])
def api_update_row(rid):
    
    """更新盘点明细行"""
    d = request.get_json(force=True)
    db = get_db()
    db.execute(
        'UPDATE inventory SET equip_no=?, equip_name=?, data_type=?, radius=?, height=?, volume=?, concentration=?, metal=?, in_ending=? WHERE id=?',
        (d.get('equip_no', ''), d.get('equip_name', ''), d.get('data_type', ''),
         d.get('radius'), d.get('height'), d.get('volume'), d.get('concentration'),
         d.get('metal'), 1 if d.get('in_ending') else 0, rid))
    db.commit()
    return ok()


@inventory_bp.route('/api/rows/<int:rid>', methods=['DELETE'])
def api_delete_row(rid):
    
    """删除盘点明细行"""
    db = get_db()
    db.execute('DELETE FROM inventory WHERE id=?', (rid,))
    db.commit()
    return ok()


@inventory_bp.route('/api/unlock', methods=['POST'])
def api_unlock():
    
    """解锁编辑（密码 admin888）"""
    d = request.get_json(force=True) or {}
    if d.get('password') == EDIT_PASSWORD:
        return ok()
    return fail('密码错误', http=403)


@inventory_bp.route('/api/periods', methods=['GET', 'POST'])
def api_periods():
    
    """盘点期间列表（GET）/ 新增期间（POST）"""
    db = get_db()
    if request.method == 'GET':
        rows = db.execute('SELECT month, start_date, end_date FROM periods ORDER BY month').fetchall()
        return ok([dict(r) for r in rows])
    d = request.get_json(force=True) or {}
    month = (d.get('month') or '').strip()
    start = (d.get('start_date') or '').strip()
    end = (d.get('end_date') or '').strip()
    if not month or not start or not end:
        return fail('月份/开始/结束日期都要填')
    exists = db.execute('SELECT 1 FROM periods WHERE month=?', (month,)).fetchone()
    if exists:
        return fail('该月份已存在')
    db.execute('INSERT INTO periods (month, start_date, end_date) VALUES (?,?,?)', (month, start, end))
    db.commit()
    return ok({'months': list_months(db)})


@inventory_bp.route('/api/import', methods=['POST'])
def api_import():
    
    """导入盘点数据"""
    f = request.files.get('file')
    if not f:
        return fail('no file')
    period = request.form.get('period') or DEFAULT_MONTH
    tmp = os.path.join(BASE_DIR, 'data', '_upload_tmp.xlsx')
    f.save(tmp)
    db = get_db()
    n = _import_inventory_xlsx(db, tmp, period)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return ok({'imported': n, 'period': period})
