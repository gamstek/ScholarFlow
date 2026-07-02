"""
report_writer.py

报告生成 Agent。

作用：
1. 在采集任务完成后触发；
2. 汇总采集统计、新文献列表、QA 摘要；
3. 生成 Markdown 格式报告并写入 dev_log。

⚠ 待第 8 步实现完整报告生成逻辑。
"""

from __future__ import annotations


def write_report(task_id: int) -> str:
    """
    根据采集任务 ID 生成 Markdown 报告。

    参数：
        task_id: 采集任务 ID。

    返回：
        str: Markdown 格式的报告内容。
    """
    raise NotImplementedError("待第 8 步实现 write_report")
