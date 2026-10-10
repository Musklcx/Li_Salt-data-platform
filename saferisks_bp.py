# -*- coding: utf-8 -*-
"""
安全隐患整改台账蓝图
--------------------
- 页面：/saferisks
- 接口：/api/risk/list、update_remark、update_finish_time、upload_img、update_img、delete_img
数据访问统一走 db.py（主库 db_day.db）；图片上传保存到 static/assets/img/upload
"""
import os
from flask import Blueprint, request, render_template
from PIL import Image
from db import query, execute
from resp import ok, fail

saferisks_bp = Blueprint('saferisks', __name__)

# 整改后图片上传目录：static/assets/img/upload
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "assets", "img", "upload")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
TARGET_W = 600
TARGET_H = 800


@saferisks_bp.route('/saferisks')
def page_saferisks():
    
    """安全隐患整改页面"""
    return render_template("saferisks.html")


@saferisks_bp.route('/api/risk/list')
def risk_list():
    
    """整改台账列表"""
    rows = query("SELECT ID,问题隐患,整改措施,隐患排查时间,要求整改时间,整改完成时间,备注,imgBefore,imgAfter FROM safeRisks;")
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
    return ok(res_list)


@saferisks_bp.route('/api/risk/update_remark', methods=["POST"])
def risk_update_remark():
    
    """更新整改备注"""
    data = request.get_json()
    execute("UPDATE safeRisks SET 备注=? WHERE ID=?", (data["remark"], data["id"]))
    return ok(msg="备注保存成功")


@saferisks_bp.route('/api/risk/update_finish_time', methods=["POST"])
def risk_update_finish_time():
    
    """更新整改完成时间"""
    data = request.get_json()
    execute("UPDATE safeRisks SET 整改完成时间=? WHERE ID=?", (data["finishTime"], data["id"]))
    return ok(msg="整改完成时间保存成功")


@saferisks_bp.route('/api/risk/upload_img', methods=["POST"])
def risk_upload_img():
    
    """上传整改图片"""
    if "file" not in request.files:
        return fail("没有收到文件")
    file = request.files["file"]
    if file.filename == "":
        return fail("文件名为空")
    row_id = request.form.get("row_id", "")
    if not row_id:
        return fail("缺少行ID")
    if not row_id.isdigit():
        return fail("行ID不合法")
    # 文件大小限制 5MB
    if (request.content_length or 0) > 5 * 1024 * 1024:
        return fail("图片不能超过 5MB")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return fail("只支持 png/jpg/jpeg/gif/bmp/webp 格式")
    try:
        # 限制解码像素总量（防止超大图片耗尽内存）
        Image.MAX_IMAGE_PIXELS = 50_000_000
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
    except Exception as e:
        return fail("图片处理失败，请确认文件是有效图片")
    img_url = f"/static/assets/img/upload/{save_name}"
    return ok(msg="上传成功", data={"url": img_url})


@saferisks_bp.route('/api/risk/update_img', methods=["POST"])
def risk_update_img():
    
    """更新整改图片"""
    data = request.get_json()
    row_id = data["id"]
    field = data["field"]
    img_url = data["url"]
    if field not in ("imgAfter",):
        return fail("字段不合法")
    if not str(row_id).isdigit():
        return fail("行ID不合法")
    execute(f"UPDATE safeRisks SET {field}=? WHERE ID=?", (img_url, row_id))
    return ok(msg="保存成功")


@saferisks_bp.route('/api/risk/delete_img', methods=["POST"])
def risk_delete_img():
    
    """删除整改图片"""
    data = request.get_json()
    row_id = data["id"]
    field = data["field"]
    img_url = data.get("url", "")
    # 列名白名单校验（防 SQL 注入：field 由 f-string 拼入 SQL）
    if field not in ("imgBefore", "imgAfter"):
        return fail("字段不合法")
    if not str(row_id).isdigit():
        return fail("行ID不合法")
    if img_url and img_url.startswith("/static/assets/img/upload/"):
        file_name = img_url.split("/")[-1]
        if file_name and file_name != "." and ".." not in file_name:
            file_path = os.path.join(UPLOAD_FOLDER, file_name)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print("删除文件失败:", e)
    execute(f"UPDATE safeRisks SET {field}=? WHERE ID=?", ("", row_id))
    return ok(msg="删除成功")
