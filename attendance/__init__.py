# -*- coding: utf-8 -*-
"""考勤模块包（自 D:\\MyWork\\Flask\\Attendance 项目整体迁入 Workweb，2026/11/18）
--------------------------------------------------------------------------------
模块划分与原项目一致：
    config.py      常量 + 数据库路径（workweb/data/attendance.db）+ 班次/轮转配置
    db.py          建表 / 迁移 / 每日备份
    calc.py        工时口径与页面数据组装（月度考勤 = 排班/异动/调整事件的投影）
    views_att.py   蓝图 att       前缀 /att   月度考勤 / 月结锁定 / 调整单 / 导出 / 归档
    views_sched.py 蓝图 att_sched 前缀 /att   排班与异动（日历/生成/放假/换班/班制）
    views_staff.py 蓝图 att_staff 前缀 /att   人员管理（增删改/离职复职/调组/异动）

与原项目的差异（迁移适配点）：
    1. 数据库从 D:\\MyWork\\AttendanceData\\attendance.db 迁到 workweb/data/attendance.db，
       备份/归档目录随之改为 data/attendance_backups/（ATT_DATA_DIR 环境变量仍可覆盖）
    2. 请求级连接挂 g.att_db（原 g.db 与 Workweb 主库 db.py 冲突），close_db 同步改键
    3. 蓝图名 sched→att_sched、staff→att_staff（与 Workweb 既有蓝图不重名），
       页面路由统一挂 /att 前缀：/att/attendance、/att/schedule、/att/staff
    4. 模板改 att_ 前缀（att_attendance / att_schedule / att_staff），
       前端 JS 移到 static/js02/att_*.js，接口路径已统一加 /att 前缀
    5. 页面骨架由"左侧深色导航"改为 Workweb 统一顶部下拉导航（见 templates/att_*.html）
"""
