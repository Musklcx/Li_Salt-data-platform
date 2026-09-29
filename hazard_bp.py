# -*- coding: utf-8 -*-
"""
30吨蒸发问题汇总蓝图
--------------------
- 页面：/hazard
- 接口：/api/hazard/list、/api/hazard/update、/api/hazard/unlock
数据访问统一走 db.py（主库 db_day.db）
"""
import os
from flask import Blueprint, jsonify, request, render_template
from db import query, execute

hazard_bp = Blueprint('hazard', __name__)

# 解锁编辑密码：与期末盘点（inventory_bp.EDIT_PASSWORD）统一为 admin888
HAZARD_EDIT_PASSWORD = 'admin888'


@hazard_bp.route('/hazard')
def page_hazard():
    return render_template("hazard.html")


# 获取隐患表全部数据
@hazard_bp.route("/api/hazard/list")
def hazard_list():
    rows = query("SELECT ID,`问题描述`,`存在隐患`,`处理措施`,`是否完成` FROM question_table;")
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
    return jsonify(res_list)


@hazard_bp.route("/api/hazard/update", methods=["POST"])
def hazard_update():
    data = request.get_json()
    row_id = data["id"]
    measures = data["measures"]
    done = data["done"]
    execute(
        "UPDATE question_table SET `处理措施`=?, `是否完成`=? WHERE ID=?",
        (measures, done, row_id)
    )
    return jsonify({"code": 0, "msg": "保存成功"})


@hazard_bp.route("/api/hazard/unlock", methods=["POST"])
def hazard_unlock():
    data = request.get_json(force=True) or {}
    if data.get("password") == HAZARD_EDIT_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码错误"}), 403
