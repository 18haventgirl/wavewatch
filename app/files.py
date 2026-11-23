"""Content-addressed attachment storage and bounded PDF text extraction."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config


def path_for(digest: str) -> Path:
    return config.FILES / digest[:2] / digest


def save(body: bytes) -> str:
    """Store bytes under their SHA-256; writing is atomic and idempotent."""
    digest = hashlib.sha256(body).hexdigest()
    target = path_for(digest)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix='.part-')
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
        os.replace(tmp, target)
    return digest


def pdf_text(path: Path) -> str:
    """Extract text in a separate process so a hostile or huge PDF cannot hang the service."""
    script = config.ROOT / 'scripts' / 'extract_pdf.py'
    try:
        result = subprocess.run([sys.executable, '-X', 'utf8', str(script), str(path), str(config.PDF_MAX_PAGES)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=config.PDF_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 'PDF 文本提取超时；文件版本已保存，可下载查看。'
    if result.returncode != 0:
        return 'PDF 文本提取未完成；文件版本已保存，可下载查看。'
    return result.stdout.strip()


def describe(body: bytes, digest: str, content_type: str) -> str:
    """Version text for a file: fingerprint plus extracted text when possible."""
    head = f'SHA-256：{digest}\n大小：{len(body):,} 字节'
    if body.startswith(b'%PDF'):
        return head + '\n\n' + pdf_text(path_for(digest))
    return head + '\n\n此格式不提取文字，只比较文件指纹；文件可下载查看。'
