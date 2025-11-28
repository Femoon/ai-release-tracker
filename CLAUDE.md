# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

版本更新监控工具集，用于检查 AI 编码工具的新版本发布。

## 运行脚本

```bash
# 检查 Claude Code 版本更新
python claude_code_version_check.py

# 检查 OpenAI Codex 版本更新（排除 alpha 版本）
python codex_version_check.py
```

## 依赖

```bash
pip install requests
```

## 架构

两个独立脚本，逻辑相似：
1. 从远程获取版本信息（CHANGELOG.md 或 Atom feed）
2. 解析最新版本号和更新内容
3. 与本地 `*_latest_version.txt` 对比
4. 版本变化时打印更新内容并更新本地记录

| 脚本 | 数据源 | 版本记录文件 |
|------|--------|--------------|
| claude_code_version_check.py | GitHub CHANGELOG.md | claude_code_latest_version.txt |
| codex_version_check.py | GitHub releases Atom feed | codex_latest_version.txt |
