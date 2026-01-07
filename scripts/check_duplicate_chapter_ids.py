#!/usr/bin/env python3
"""Scan note JSON files under `data/` for duplicate chapter ids.

Usage: python scripts/check_duplicate_chapter_ids.py [--path data]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict


def find_note_files(root: str):
    for name in os.listdir(root):
        note_dir = os.path.join(root, name)
        if os.path.isdir(note_dir):
            for fname in os.listdir(note_dir):
                if fname.endswith('.json'):
                    yield os.path.join(note_dir, fname)


def analyze_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    chapters = raw.get('chapters', [])
    ids = [c.get('id') for c in chapters]
    counts = Counter(ids)
    duplicates = {id_: cnt for id_, cnt in counts.items() if id_ and cnt > 1}
    details = defaultdict(list)
    if duplicates:
        for idx, c in enumerate(chapters):
            cid = c.get('id')
            if cid in duplicates:
                details[cid].append({'index': idx, 'title': c.get('title'), 'parent_id': c.get('parent_id')})
    return duplicates, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', default='data', help='Path to data directory')
    args = parser.parse_args()
    root = args.path
    any_problems = False
    for path in find_note_files(root):
        duplicates, details = analyze_file(path)
        if duplicates:
            any_problems = True
            print(f"\nFile: {path}")
            for id_, cnt in duplicates.items():
                print(f"  Duplicate id: {id_} (occurs {cnt} times)")
                for d in details[id_]:
                    print(f"    - index={d['index']} parent_id={d['parent_id']} title={d['title']}")
    if not any_problems:
        print('No duplicate chapter ids found in', root)


if __name__ == '__main__':
    main()
