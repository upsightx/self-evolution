#!/usr/bin/env python3
"""
Import Legacy Memory Files.

从现有的 memory/*.md 文件提取符合格式的记忆并导入数据库。
支持从以下格式导入:
- 每日会话记录 (YYYY-MM-DD-*.md): 提取会话摘要为 session_summary
- 包含特定格式的决策文件: 提取为 decisions

Usage:
    python import_legacy.py [--dry-run] [--limit N] [--type observation|decision|summary|all]
"""

import os
import sys
import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# 添加父目录到路径以导入 memory_db
sys.path.insert(0, str(Path(__file__).parent))
from memory_db import get_db, add_observation, add_decision, add_session_summary

MEMORY_DIR = Path(os.environ.get("SELF_EVOLUTION_DIR", Path(__file__).parent.parent))


def parse_daily_session(filepath):
    """解析每日会话记录文件，提取 session_summary 信息。
    
    文件格式:
    # Session: 2026-03-03 01:43:10 UTC
    - **Session Key**: agent:main:main
    - **Session ID**: xxx
    - **Source**: gateway:sessions.reset
    
    ## Conversation Summary
    ...
    """
    content = filepath.read_text(encoding='utf-8')
    
    # 提取 session_id
    session_id_match = re.search(r'\*\*Session ID\*\*:\s*([\w-]+)', content)
    session_id = session_id_match.group(1) if session_id_match else None
    
    # 提取日期作为 timestamp
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filepath.name)
    timestamp = date_match.group(1) if date_match else filepath.stem[:10]
    
    # 提取关键请求（第一条 user 消息）
    user_messages = re.findall(r'user:\s*(.+?)(?:\n|$)', content)
    request = user_messages[0] if user_messages else None
    
    # 提取学到的内容（从 assistant 回复中提取关键信息）
    assistant_messages = re.findall(r'assistant:\s*(.+?)(?:\nuser:|\nSystem:|$)', content, re.DOTALL)
    learned = None
    if assistant_messages:
        # 取最长的 assistant 回复作为 learned
        learned = max(assistant_messages, key=len).strip()[:500]
    
    return {
        "session_id": session_id,
        "timestamp": timestamp,
        "request": request,
        "learned": learned,
        "completed": None,
        "next_steps": None,
        "importance_score": 0.5
    }


def detect_memory_type(filepath):
    """根据文件名和内容检测记忆类型。"""
    content = filepath.read_text(encoding='utf-8')
    name = filepath.name.lower()
    
    # 如果文件名包含特定关键词
    if 'decision' in name or '选择' in name or '决定' in name:
        return 'decision'
    if 'bug' in name or 'error' in name or '错误' in name or '修复' in name:
        return 'observation'
    if 'learn' in name or '学习' in name:
        return 'observation'
    
    # 如果是日期格式的文件 (YYYY-MM-DD-*.md)，作为 session summary
    if re.match(r'\d{4}-\d{2}-\d{2}-', filepath.name):
        return 'session_summary'
    
    return 'observation'


def parse_decision_file(filepath):
    """解析决策文件。
    
    尝试识别:
    - decision: 决策内容
    - rejected_alternatives: 被拒绝的选项
    - rationale: 理由
    """
    content = filepath.read_text(encoding='utf-8')
    
    title = filepath.stem[:50]  # 文件名作为标题
    
    # 尝试提取决策内容
    decision_match = re.search(r'(?:decision|决定|决策)[:：]\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
    decision = decision_match.group(1).strip() if decision_match else content[:200]
    
    # 尝试提取被拒绝的选项
    rejected = re.findall(r'(?:reject|放弃|未选择)[:：]\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
    rejected_alternatives = rejected if rejected else None
    
    # 尝试提取理由
    rationale_match = re.search(r'(?:reason|理由|because|因为)[:：]\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
    rationale = rationale_match.group(1).strip() if rationale_match else None
    
    return {
        "title": title,
        "decision": decision,
        "rejected_alternatives": rejected_alternatives,
        "rationale": rationale
    }


def import_file(filepath, dry_run=False, import_type='all'):
    """导入单个文件。"""
    print(f"\n📄 Processing: {filepath.name}")
    
    mem_type = detect_memory_type(filepath)
    
    if import_type == 'all':
        pass  # 使用自动检测的类型
    elif import_type in ('observation', 'decision', 'summary'):
        if import_type == 'summary' and mem_type != 'session_summary':
            return None
        if import_type == 'observation' and mem_type == 'session_summary':
            return None
        if import_type == 'decision':
            pass  # 决策文件单独处理
    else:
        print(f"  ⚠️ Skipping: unknown type '{import_type}'")
        return None
    
    try:
        if mem_type == 'session_summary':
            data = parse_daily_session(filepath)
            if dry_run:
                print(f"  🔍 [DRY RUN] Would add session_summary:")
                print(f"    session_id: {data['session_id']}")
                print(f"    request: {data['request'][:50]}..." if data['request'] else "    request: None")
                return data
            else:
                add_session_summary(
                    request=data['request'],
                    learned=data['learned'],
                    completed=data['completed'],
                    next_steps=data['next_steps'],
                    session_id=data['session_id'],
                    importance_score=data['importance_score']
                )
                print(f"  ✅ Added session_summary")
                return data
        
        elif mem_type == 'decision':
            data = parse_decision_file(filepath)
            if dry_run:
                print(f"  🔍 [DRY RUN] Would add decision:")
                print(f"    title: {data['title']}")
                print(f"    decision: {data['decision'][:50]}..." if data['decision'] else "    decision: None")
                return data
            else:
                add_decision(
                    title=data['title'],
                    decision=data['decision'],
                    rejected_alternatives=data['rejected_alternatives'],
                    rationale=data['rationale']
                )
                print(f"  ✅ Added decision")
                return data
        
        else:  # observation
            content = filepath.read_text(encoding='utf-8')
            # 简单处理：取前200字符作为标题
            title = filepath.stem[:50]
            # 尝试从内容中提取更多信息
            type_ = 'change'
            if 'bug' in filepath.name.lower() or 'error' in filepath.name.lower():
                type_ = 'bugfix'
            elif 'fix' in filepath.name.lower():
                type_ = 'bugfix'
            elif 'api' in filepath.name.lower():
                type_ = 'discovery'
            
            # 提取 source
            source = 'file'
            
            # 尝试提取 tags
            tags = []
            if 'feishu' in filepath.name.lower() or '飞书' in filepath.name.lower():
                tags.append('飞书')
            if 'api' in filepath.name.lower():
                tags.append('API')
            
            if dry_run:
                print(f"  🔍 [DRY RUN] Would add observation:")
                print(f"    type: {type_}")
                print(f"    title: {title}")
                print(f"    source: {source}")
                print(f"    tags: {tags}")
                return {"type": type_, "title": title, "source": source, "tags": tags}
            else:
                obs_id = add_observation(
                    type=type_,
                    title=title,
                    narrative=content[:1000],
                    source=source,
                    verified=False,
                    tags=tags if tags else None
                )
                print(f"  ✅ Added observation #{obs_id}")
                return {"id": obs_id, "type": type_, "title": title}
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Import legacy memory files to structured database')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without importing')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of files to process (0=all)')
    parser.add_argument('--type', choices=['observation', 'decision', 'summary', 'all'], default='all',
                        help='Type of memories to import')
    parser.add_argument('--dir', type=str, default=None, help='Memory directory path')
    
    args = parser.parse_args()
    
    memory_dir = Path(args.dir) if args.dir else MEMORY_DIR
    
    # 查找所有 .md 文件（排除 structured 目录）
    md_files = []
    for f in memory_dir.rglob('*.md'):
        # 排除 structured 目录和 index.md
        if 'structured' not in f.parts and f.name != 'index.md':
            md_files.append(f)
    
    # 按修改时间排序
    md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    
    if args.limit > 0:
        md_files = md_files[:args.limit]
    
    print(f"Found {len(md_files)} markdown files")
    print(f"Type filter: {args.type}")
    print(f"Dry run: {args.dry_run}")
    print("-" * 50)
    
    results = {
        "processed": 0,
        "success": 0,
        "failed": 0,
        "by_type": {}
    }
    
    for filepath in md_files:
        results["processed"] += 1
        result = import_file(filepath, dry_run=args.dry_run, import_type=args.type)
        
        if result:
            results["success"] += 1
            # 统计类型
            mem_type = detect_memory_type(filepath)
            results["by_type"][mem_type] = results["by_type"].get(mem_type, 0) + 1
        else:
            results["failed"] += 1
    
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Processed: {results['processed']}")
    print(f"  Success: {results['success']}")
    print(f"  Failed: {results['failed']}")
    print(f"  By type: {results['by_type']}")
    
    if args.dry_run:
        print("\n⚠️  This was a dry run. No data was actually imported.")
        print("   Run without --dry-run to import.")


if __name__ == "__main__":
    main()
