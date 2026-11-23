"""Line diffs for revisions: statistics, short summaries and side-by-side rows."""
from __future__ import annotations

import difflib


def compare(old: str, new: str) -> list[dict]:
    """Rows for a side-by-side view.  Unchanged runs longer than 6 lines are folded."""
    a, b = old.splitlines(), new.splitlines()
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            block = list(zip(range(i1, i2), range(j1, j2)))
            if len(block) > 6:
                for i, j in block[:3]:
                    out.append({'type': 'same', 'old': a[i], 'new': b[j], 'old_no': i + 1, 'new_no': j + 1})
                out.append({'type': 'fold', 'count': len(block) - 6})
                block = block[-3:]
            for i, j in block:
                out.append({'type': 'same', 'old': a[i], 'new': b[j], 'old_no': i + 1, 'new_no': j + 1})
            continue
        left, right = a[i1:i2], b[j1:j2]
        for k in range(max(len(left), len(right))):
            o = left[k] if k < len(left) else None
            n = right[k] if k < len(right) else None
            kind = 'changed' if o is not None and n is not None else 'removed' if o is not None else 'added'
            out.append({'type': kind, 'old': o, 'new': n,
                        'old_no': i1 + k + 1 if o is not None else None,
                        'new_no': j1 + k + 1 if n is not None else None,
                        'spans': inline_spans(o, n) if kind == 'changed' else None})
    return out


def inline_spans(old: str, new: str) -> dict:
    """Character ranges that differ, for highlighting inside a changed line."""
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'delete'):
            removed.append([i1, i2])
        if tag in ('replace', 'insert'):
            added.append([j1, j2])
    return {'old': removed, 'new': added}


def stats(old: str, new: str) -> dict:
    added = removed = 0
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith('+ '):
            added += 1
        elif line.startswith('- '):
            removed += 1
    return {'added': added, 'removed': removed}


def summary(old: str, new: str) -> str:
    s = stats(old, new)
    parts = []
    if s['added']:
        parts.append(f"新增 {s['added']} 行")
    if s['removed']:
        parts.append(f"删除 {s['removed']} 行")
    return '，'.join(parts) or '仅格式变化'


def excerpt(old: str, new: str, limit: int = 12) -> list[tuple[str, str]]:
    """Changed lines for an email: [('+'|'-', text), ...]."""
    lines: list[tuple[str, str]] = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm='', n=0):
        if line.startswith(('+++', '---', '@@')):
            continue
        if line[:1] in '+-':
            text = line[1:].strip()
            if text:
                lines.append((line[0], text[:300]))
        if len(lines) >= limit:
            break
    return lines
