# -*- coding: utf-8 -*-
"""
每日自动备份脚本
----------------
- 备份对象：data/ 下 3 个 SQLite 库（users.db / db_day.db / db_balance.db）
- 备份位置：D:\\MyWork\\Flask\\Backup\\workweb\\<日期>\\  （外部目录，不随项目打包、不被 git 追踪）
- 保留策略：只保留最近 30 天的备份，更早的自动清理
- 使用：手动运行  .venv\\Scripts\\python.exe backup.py
        或由 Windows 计划任务每日自动执行（任务名 Workweb每日备份，03:00）
"""
import os
import shutil
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE, 'data')
BACKUP_ROOT = r'D:\MyWork\Flask\Backup\workweb'   # ← 备份位置（可自行修改）
KEEP = 30                                          # ← 保留天数（可自行修改）

DBS = ['users.db', 'db_day.db', 'db_balance.db']


def main():
    today = datetime.date.today().strftime('%Y-%m-%d')
    dest_dir = os.path.join(BACKUP_ROOT, today)
    os.makedirs(dest_dir, exist_ok=True)

    copied = []
    for name in DBS:
        src = os.path.join(DB_DIR, name)
        if not os.path.exists(src):
            print('[跳过] 不存在:', src)
            continue
        shutil.copy2(src, os.path.join(dest_dir, name))
        copied.append(name)

    # 清理：只保留最近 KEEP 个日期目录
    if os.path.isdir(BACKUP_ROOT):
        all_dirs = sorted(
            d for d in os.listdir(BACKUP_ROOT)
            if os.path.isdir(os.path.join(BACKUP_ROOT, d))
        )
        while len(all_dirs) > KEEP:
            rm = all_dirs.pop(0)
            shutil.rmtree(os.path.join(BACKUP_ROOT, rm), ignore_errors=True)
            print('[清理] 删除旧备份', rm)

    print('[完成]', today, '备份:', ', '.join(copied) if copied else '无', '→', dest_dir)


if __name__ == '__main__':
    main()
