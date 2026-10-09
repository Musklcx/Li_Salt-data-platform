# -*- coding: utf-8 -*-
"""
下载专区蓝图
------------
- 页面：/download（纯展示页，无独立接口）
"""
from flask import Blueprint, render_template

download_bp = Blueprint('download', __name__)


@download_bp.route('/download')
def page_download():
    
    """下载专区页面"""
    return render_template("download.html")
