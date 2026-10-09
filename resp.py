# -*- coding: utf-8 -*-
"""resp.py — 统一 API 返回格式

所有接口统一返回: {"code": 0, "msg": "ok", "data": ...}
成功: code=0；失败: code 非 0（HTTP 状态码仍由 fail 的 http 参数控制）

用法:
    from resp import ok, fail
    return ok(get_all_rows())          # 成功, data=列表
    return ok(msg="保存成功")           # 成功, 无数据(data=None)
    return fail("密码错误", http=403)   # 失败, HTTP 403
"""
from flask import jsonify


def ok(data=None, msg="ok"):
    """成功响应: {"code": 0, "msg": msg, "data": data}"""
    return jsonify({"code": 0, "msg": msg, "data": data})


def fail(msg="操作失败", code=1, http=400):
    """失败响应: {"code": code, "msg": msg, "data": None}, HTTP 状态码 http"""
    return jsonify({"code": code, "msg": msg, "data": None}), http
