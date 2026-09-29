from flask import Flask, jsonify, render_template, redirect, request, g
import sqlite3
import os
import uuid
from datetime import datetime
import socket
from PIL import Image
from werkzeug.utils import secure_filename
from auth import auth_bp, init_auth_db, resolve_user
from inventory_bp import inventory_bp, init_inventory_db

app = Flask(__name__)

# ---- 登录认证配置（auth 蓝图使用，移植自 login 项目）----
app.config['SECRET_KEY'] = os.environ.get(
    'JWT_SECRET',
    'dev-insecure-secret-please-change-me-to-a-long-random-string-32bytes+'
)
app.config['JWT_ALGORITHM'] = 'HS256'
app.config['JWT_EXPIRE_HOURS'] = 2
# 邮箱验证码（未配置 SMTP_HOST 时验证码打印到服务控制台，便于本地联调）
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', '')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '465'))
app.config['SMTP_USER'] = os.environ.get('SMTP_USER', '')
app.config['SMTP_PASS'] = os.environ.get('SMTP_PASS', '')
app.config['MAIL_FROM'] = os.environ.get('MAIL_FROM', '') or app.config['SMTP_USER']
app.config['VERIFY_CODE_TTL'] = 10 * 60
app.config['VERIFY_CODE_RESEND'] = 60

app.register_blueprint(auth_bp)
app.register_blueprint(inventory_bp)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "data", "db_day.db")

# 整改后图片上传目录：static/assets/img/upload
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "assets", "img", "upload")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
TARGET_W = 600
TARGET_H = 800

# ========== 全局登录拦截：除白名单外，页面与接口一律要求已登录 ==========
PUBLIC_PATHS = {
    '/', '/login', '/favicon.ico',
    '/api/login', '/api/register', '/api/register/send-code',
}

@app.before_request
def require_login():
    path = request.path
    if path in PUBLIC_PATHS or path.startswith('/static'):
        return None
    uid, email = resolve_user()
    if uid is not None:
        g.user_id = uid
        g.email = email
        return None
    # 未登录：API 返回 401 JSON，页面 302 跳回登录页
    if path.startswith('/api/'):
        return jsonify(code=401, msg='未登录或登录已过期'), 401
    return redirect('/login')


# ========== 多页面路由 ==========
@app.route('/')
def home():
    return redirect('/login')

@app.route('/data')
def page_data():
    return render_template("data.html")

@app.route('/hazard')
def page_hazard():
    return render_template("hazard.html")

@app.route('/notice')
def page_notice():
    return render_template("notice.html")

@app.route('/staff')
def page_staff():
    return render_template("staff.html")

@app.route('/download')
def page_download():
    return render_template("download.html")

@app.route('/saferisks')
def page_saferisks():
    return render_template("saferisks.html")


def format_date(s):
    """原始字符串 2026/9/1 → 2026/09/01"""
    if not s:
        return ""
    s = s.strip()
    fmt = "%Y/%m/%d"
    try:
        dt = datetime.strptime(s, fmt)
        return dt.strftime("%Y/%m/%d")
    except ValueError:
        pass
    return s


def parse_raw_date(s):
    """把原始日期字符串转为 datetime，用于排序"""
    s = s.strip()
    fmt = "%Y/%m/%d"
    try:
        return datetime.strptime(s, fmt)
    except ValueError:
        pass
    return None


@app.route("/api/output/all")
def api_all():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sql = '''
    SELECT
    日期 AS raw_date,
    SUM(碳酸锂仓库出库) AS 碳酸锂仓库出库,
    SUM(碳酸锂车间产出) AS 碳酸锂车间产出,
    SUM(硫酸钠) AS 硫酸钠,
    SUM(硫酸钠干料) AS 硫酸钠干料,
    SUM(硫酸钠湿料) AS 硫酸钠湿料,
    SUM(硫酸钠杂质料) AS 硫酸钠杂质料,
    SUM(硫酸钠落地料) AS 硫酸钠落地料,
    SUM(碳酸钠车间消耗) AS 碳酸钠车间消耗,
    SUM(碳酸钠仓库出库) AS 碳酸钠仓库出库,
    SUM(外排水量) AS 外排水量
    FROM data_103
    GROUP BY raw_date
    '''
    rows = cur.execute(sql).fetchall()
    conn.close()

    temp = []
    for r in rows:
        d = dict(r)
        dt_obj = parse_raw_date(d["raw_date"])
        temp.append({"dt_obj": dt_obj, "raw": d})

    # 按真实时间排序，空时间排最后
    temp.sort(key=lambda x: x["dt_obj"] if x["dt_obj"] else datetime.max)

    res = []
    for item in temp:
        raw_row = item["raw"]
        out = {
            "日期": format_date(raw_row["raw_date"]),
            "碳酸锂仓库出库": raw_row["碳酸锂仓库出库"],
            "碳酸锂车间产出": raw_row["碳酸锂车间产出"],
            "硫酸钠": raw_row["硫酸钠"],
            "硫酸钠干料": raw_row["硫酸钠干料"],
            "硫酸钠湿料": raw_row["硫酸钠湿料"],
            "硫酸钠杂质料": raw_row["硫酸钠杂质料"],
            "硫酸钠落地料": raw_row["硫酸钠落地料"],
            "碳酸钠车间消耗": raw_row["碳酸钠车间消耗"],
            "碳酸钠仓库出库": raw_row["碳酸钠仓库出库"],
            "外排水量": raw_row["外排水量"]
        }
        res.append(out)
    return jsonify(res)


@app.route("/api/plan/get")
def api_plan_get():
    """读取month_plan月度计划表，前端参数 yyyy-mm"""
    month_str = request.args.get("month")  # 例如 "2026-09"
    # 把 "2026-09" 转成 "2026年9月"，匹配数据库month_plan表的月份字段
    year, mon = month_str.split("-")
    # 去掉月份前面的0，09 →9，数据库是"2026年9月"不是"2026年09月"
    mon_int = int(mon)
    db_month_text = f"{year}年{mon_int}月"

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sql = "SELECT 碳酸锂,硫酸钠 FROM month_plan WHERE 月份 = ?"
    row = cur.execute(sql, [db_month_text]).fetchone()
    conn.close()
    if row is None:
        return jsonify({"碳酸锂": 0, "硫酸钠": 0})
    return jsonify({
        "碳酸锂": float(row["碳酸锂"]),
        "硫酸钠": float(row["硫酸钠"])
    })


@app.route("/api/notice/list")
def api_notice_list():
    """明细表格数据：年月 + 班组筛选"""
    month_str = request.args.get("month")
    banzu = request.args.get("banzu", "全部")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    year, mon = month_str.split("-")
    year_val = year
    mon_val = str(int(mon))  # 09 → 9，适配数据库 2026/9/1 不带前导零

    sql_base = """
    SELECT
        日期,
        班组,
        `碳酸锂车间产出`,
        `硫酸钠`,
        `去蒸发前液处理量`,
        `合成前液处理量`,
        `压滤机卸渣量`,
        `蒸发冷凝水`,
        `碳酸钠车间消耗`,
        `投活性炭、除氟剂量`,
        `产出锂渣`,
        `回投锂渣`,
        `镍渣`,
        `104返镁液`,
        `104废液`,
        `外排水量`,
        `钴渣量`,
        `清合成釜`,
        `更换滤布`
    FROM data_103
    WHERE
    substr(日期,1,instr(日期,'/')-1) = ?
    AND substr(日期,instr(日期,'/')+1, instr(substr(日期,instr(日期,'/')+1),'/')-1) = ?
    """
    params = [year_val, mon_val]
    if banzu != "全部":
        sql_base += " AND 班组 = ? "
        params.append(banzu)
    rows = cur.execute(sql_base, params).fetchall()
    conn.close()
    res = []
    for r in rows:
        res.append(dict(r))
    return jsonify(res)


@app.route("/api/notice/sum")
def api_notice_sum():
    """按月聚合，甲、乙、丙各班汇总产量，用于顶部卡片"""
    month_str = request.args.get("month")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    year, mon = month_str.split("-")
    year_val = year
    mon_val = str(int(mon))

    sql = """
    SELECT
        班组,
        SUM(`碳酸锂车间产出`) AS sum_li,
        SUM(`硫酸钠`) AS sum_na
    FROM data_103
    WHERE
    substr(日期,1,instr(日期,'/')-1) = ?
    AND substr(日期,instr(日期,'/')+1, instr(substr(日期,instr(日期,'/')+1),'/')-1) = ?
    GROUP BY 班组
    """
    rows = cur.execute(sql, [year_val, mon_val]).fetchall()
    conn.close()
    out = {"甲":{"sum_li":0,"sum_na":0}, "乙":{"sum_li":0,"sum_na":0}, "丙":{"sum_li":0,"sum_na":0}}
    for r in rows:
        bz = r["班组"]
        if bz in out:
            out[bz]["sum_li"] = float(r["sum_li"] or 0)
            out[bz]["sum_na"] = float(r["sum_na"] or 0)
    return jsonify(out)


@app.route("/")
def index():
    # Flask标准模板渲染，读取 templates/index.html
    return render_template("index.html")


# 获取隐患表全部数据（首页内嵌隐患记录页用）
@app.route("/api/hazard/list")
def hazard_list():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT ID,`问题描述`,`存在隐患`,`处理措施`,`是否完成` FROM question_table;")
    rows = cur.fetchall()
    res_list = []
    img_dir = os.path.join("static", "assets", "img", "table")
    for row in rows:
        row_id = str(row["ID"])
        # 判断对应ID的jpg图片是否存在，存在就用实拍图，不存在用默认占位图
        custom_img = os.path.join(img_dir, f"{row_id}.jpg")
        if os.path.exists(custom_img):
            img_url = f"/static/assets/img/table/{row_id}.jpg"
        else:
            img_url = "/static/assets/img/table/546.gif"
        res_list.append({
            "id": row_id,
            "question": row["问题描述"],
            "safety": row["存在隐患"],
            "measures": row["处理措施"],
            "done": row["是否完成"],
            "imgUrl": img_url
        })
    conn.close()
    return jsonify(res_list)

@app.route("/api/hazard/update", methods=["POST"])
def hazard_update():
    data = request.get_json()
    row_id = data["id"]
    measures = data["measures"]
    done = data["done"]
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "UPDATE question_table SET `处理措施`=?, `是否完成`=? WHERE ID=?",
        (measures, done, row_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"code": 0, "msg": "保存成功"})


# 解锁编辑密码：与期末盘点（inventory_bp.EDIT_PASSWORD）统一为 admin888
HAZARD_EDIT_PASSWORD = 'admin888'

@app.route("/api/hazard/unlock", methods=["POST"])
def hazard_unlock():
    data = request.get_json(force=True) or {}
    if data.get("password") == HAZARD_EDIT_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码错误"}), 403


# ========== 安全隐患整改台账接口 ==========
@app.route('/api/risk/list')
def risk_list():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT ID,问题隐患,整改措施,隐患排查时间,要求整改时间,整改完成时间,备注,imgBefore,imgAfter FROM safeRisks;")
    rows = cur.fetchall()
    res_list = []
    for row in rows:
        res_list.append({
            "id": row["ID"],
            "problem": row["问题隐患"],
            "measure": row["整改措施"],
            "checkTime": row["隐患排查时间"],
            "requireTime": row["要求整改时间"],
            "finishTime": row["整改完成时间"],
            "remark": row["备注"],
            "imgBefore": row["imgBefore"] or "",
            "imgAfter": row["imgAfter"] or ""
        })
    conn.close()
    return jsonify(res_list)

@app.route('/api/risk/update_remark', methods=["POST"])
def risk_update_remark():
    data = request.get_json()
    row_id = data["id"]
    remark = data["remark"]
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("UPDATE safeRisks SET 备注=? WHERE ID=?", (remark, row_id))
    conn.commit()
    conn.close()
    return jsonify({"code": 0, "msg": "备注保存成功"})

@app.route('/api/risk/update_finish_time', methods=["POST"])
def risk_update_finish_time():
    data = request.get_json()
    row_id = data["id"]
    finishTime = data["finishTime"]
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("UPDATE safeRisks SET 整改完成时间=? WHERE ID=?", (finishTime, row_id))
    conn.commit()
    conn.close()
    return jsonify({"code": 0, "msg": "整改完成时间保存成功"})

@app.route('/api/risk/upload_img', methods=["POST"])
def risk_upload_img():
    if "file" not in request.files:
        return jsonify({"code": 1, "msg": "没有收到文件"})
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"code": 1, "msg": "文件名为空"})
    row_id = request.form.get("row_id", "")
    if not row_id:
        return jsonify({"code": 1, "msg": "缺少行ID"})
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify({"code": 1, "msg": "只支持 png/jpg/jpeg/gif/bmp/webp 格式"})
    img = Image.open(file.stream)
    img_ratio = img.width / img.height
    target_ratio = TARGET_W / TARGET_H
    if img_ratio > target_ratio:
        new_h = TARGET_H
        new_w = int(new_h * img_ratio)
    else:
        new_w = TARGET_W
        new_h = int(new_w / img_ratio)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - TARGET_W) / 2
    top = (new_h - TARGET_H) / 2
    right = left + TARGET_W
    bottom = top + TARGET_H
    img = img.crop((left, top, right, bottom))
    # 按行ID命名：af_行ID.jpg
    save_name = f"af_{row_id}.jpg"
    save_path = os.path.join(UPLOAD_FOLDER, save_name)
    img.convert("RGB").save(save_path, quality=85)
    img_url = f"/static/assets/img/upload/{save_name}"
    return jsonify({"code": 0, "msg": "上传成功", "url": img_url})

@app.route('/api/risk/update_img', methods=["POST"])
def risk_update_img():
    data = request.get_json()
    row_id = data["id"]
    field = data["field"]
    img_url = data["url"]
    if field not in ("imgAfter",):
        return jsonify({"code": 1, "msg": "字段不合法"})
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(f"UPDATE safeRisks SET {field}=? WHERE ID=?", (img_url, row_id))
    conn.commit()
    conn.close()
    return jsonify({"code": 0, "msg": "保存成功"})

@app.route('/api/risk/delete_img', methods=["POST"])
def risk_delete_img():
    data = request.get_json()
    row_id = data["id"]
    field = data["field"]
    img_url = data.get("url", "")
    if img_url and img_url.startswith("/static/assets/img/upload/"):
        file_name = img_url.split("/")[-1]
        file_path = os.path.join(UPLOAD_FOLDER, file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print("删除文件失败:", e)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(f"UPDATE safeRisks SET {field}=? WHERE ID=?", ("", row_id))
    conn.commit()
    conn.close()
    return jsonify({"code": 0, "msg": "删除成功"})


if __name__ == '__main__':
    with app.app_context():
        init_auth_db()  # 首次运行自动建用户表（已存在则跳过）
        init_inventory_db()  # 期末盘点库建表/补列/首次导入（已存在则跳过）
    hostname = socket.gethostname()
    print(f"局域网主机名访问地址：http://{hostname}:5000")
    print(f"数据库路径：{DB_FILE}")
    app.run(host="0.0.0.0", port=5000, debug=True)
