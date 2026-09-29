# -*- coding: utf-8 -*-
"""
人员概况蓝图
------------
- 页面：/staff（纯展示页，无独立接口）
"""
from flask import Blueprint, render_template

staff_bp = Blueprint('staff', __name__)


@staff_bp.route('/staff')
def page_staff():
    return render_template("staff.html")
