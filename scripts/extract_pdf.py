"""Bounded text extraction in a separate process (not a layout rendering)."""
import sys
from pypdf import PdfReader
if __name__=='__main__':
    reader=PdfReader(sys.argv[1])
    text='\n\n'.join((page.extract_text() or '') for page in reader.pages[:50])
    print(text[:2_000_000] if text.strip() else '无可提取文本，可能为扫描 PDF。')
    if len(reader.pages)>50:
        print('\n仅提取前 50 页，完整文件已保存。')
