#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
版本更新监控工具入口
检查所有 AI 编码工具的版本更新
"""

import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CHECKERS = [
    {
        "name": "Claude Code",
        "script": os.path.join(SCRIPT_DIR, "products", "claude_code", "checker.py"),
    },
    {
        "name": "OpenAI Codex",
        "script": os.path.join(SCRIPT_DIR, "products", "codex", "checker.py"),
    },
]


def run_checker(checker):
    """运行单个版本检查脚本"""
    print(f"\n{'=' * 50}")
    print(f"检查 {checker['name']} 版本更新")
    print("=" * 50)

    try:
        result = subprocess.run(
            [sys.executable, checker["script"]],
            capture_output=True,
            text=True,
        )
        # 输出子进程的标准输出
        if result.stdout:
            print(result.stdout, end='')
        # 输出子进程的错误信息
        if result.stderr:
            print(result.stderr, end='')
        if result.returncode != 0:
            print(f"脚本退出码: {result.returncode}")
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        print(f"运行 {checker['name']} 检查脚本失败: {e}")
        return False


def main():
    print("版本更新监控工具")
    print("=" * 50)

    success_count = 0
    for checker in CHECKERS:
        if run_checker(checker):
            success_count += 1

    print(f"\n{'=' * 50}")
    print(f"检查完成: {success_count}/{len(CHECKERS)} 个工具检查成功")
    print("=" * 50)


if __name__ == "__main__":
    main()
