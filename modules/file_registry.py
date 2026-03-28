#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

BASE = Path('/root/.openclaw/workspace')
MEMORY_DIR = BASE / 'memory'
STRUCTURED_DIR = MEMORY_DIR / 'structured'
REGISTRY_JSONL = MEMORY_DIR / 'file-registry.jsonl'
REGISTRY_MD = MEMORY_DIR / 'file-registry.md'


def append_markdown(entry: dict):
    REGISTRY_MD.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_MD.exists():
        REGISTRY_MD.write_text('# 文件记忆台账\n\n', encoding='utf-8')

    lines = []
    lines.append(f"## {entry['title']}")
    lines.append(f"- 时间: {entry['timestamp']}")
    lines.append(f"- 类型: {entry.get('kind') or 'file'}")
    if entry.get('channel'):
        lines.append(f"- 渠道: {entry['channel']}")
    if entry.get('platform'):
        lines.append(f"- 平台: {entry['platform']}")
    if entry.get('filename'):
        lines.append(f"- 文件名: {entry['filename']}")
    if entry.get('doc_title'):
        lines.append(f"- 文档名: {entry['doc_title']}")
    if entry.get('url'):
        lines.append(f"- 链接: {entry['url']}")
    if entry.get('folder_token'):
        lines.append(f"- folder_token: {entry['folder_token']}")
    if entry.get('task'):
        lines.append(f"- 关联任务: {entry['task']}")
    if entry.get('summary'):
        lines.append(f"- 说明: {entry['summary']}")
    if entry.get('tags'):
        lines.append(f"- 标签: {', '.join(entry['tags'])}")
    lines.append('')

    with REGISTRY_MD.open('a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def remember_structured(entry: dict):
    import sys
    sys.path.insert(0, str(STRUCTURED_DIR))
    from memory_service import remember

    title = entry['title']
    summary = entry.get('summary') or ''
    parts = []
    if entry.get('filename'):
        parts.append(f"文件名: {entry['filename']}")
    if entry.get('doc_title'):
        parts.append(f"文档名: {entry['doc_title']}")
    if entry.get('url'):
        parts.append(f"链接: {entry['url']}")
    if entry.get('channel'):
        parts.append(f"渠道: {entry['channel']}")
    if entry.get('task'):
        parts.append(f"关联任务: {entry['task']}")
    if summary:
        parts.append(f"说明: {summary}")
    content = '\n'.join(parts)
    tags = sorted(set((entry.get('tags') or []) + ['file-memory', 'file-registry']))
    return remember(
        content=content,
        type='file_record',
        title=title,
        tags=tags,
        task_type='documentation',
    )


def add_entry(entry: dict):
    REGISTRY_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_JSONL.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    append_markdown(entry)
    return remember_structured(entry)


def main():
    p = argparse.ArgumentParser(description='Record file/document memory entries')
    p.add_argument('--title', required=True)
    p.add_argument('--kind', default='file')
    p.add_argument('--channel', default='')
    p.add_argument('--platform', default='')
    p.add_argument('--filename', default='')
    p.add_argument('--doc-title', dest='doc_title', default='')
    p.add_argument('--url', default='')
    p.add_argument('--folder-token', dest='folder_token', default='')
    p.add_argument('--task', default='')
    p.add_argument('--summary', default='')
    p.add_argument('--tags', default='')
    args = p.parse_args()

    entry = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'title': args.title,
        'kind': args.kind,
        'channel': args.channel,
        'platform': args.platform,
        'filename': args.filename,
        'doc_title': args.doc_title,
        'url': args.url,
        'folder_token': args.folder_token,
        'task': args.task,
        'summary': args.summary,
        'tags': [t.strip() for t in args.tags.split(',') if t.strip()],
    }
    res = add_entry(entry)
    print(json.dumps({'ok': True, 'entry': entry, 'memory': res}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
