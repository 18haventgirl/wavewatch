"""Bounded PDF text extraction, run in a child process by app.files.

Usage: python extract_pdf.py <file> [max_pages]
"""
import sys

from pypdf import PdfReader

if __name__ == '__main__':
    reader = PdfReader(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    pages = [(page.extract_text() or '').strip() for page in reader.pages[:limit]]
    text = '\n\n'.join(p for p in pages if p)
    print(text[:2_000_000] if text.strip() else '无可提取文字（可能是扫描件），可下载原文件查看。')
    if len(reader.pages) > limit:
        print(f'\n仅提取前 {limit} 页（共 {len(reader.pages)} 页），完整文件已保存。')
