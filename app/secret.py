"""Protect the SMTP password at rest.

On Windows the password is encrypted with DPAPI for the current Windows user, so a
copied database file is useless on another account or machine.  Elsewhere (tests,
Linux) it is stored base64-encoded and the UI says so.
"""
from __future__ import annotations

import base64
import sys

PROTECTED = sys.platform == 'win32'

if PROTECTED:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def _call(fn, data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))  # kept alive for the duration of the call
        source = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        # 0x01 = CRYPTPROTECT_UI_FORBIDDEN
        if not fn(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(out)):
            raise OSError('Windows 数据保护接口调用失败')
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)

    def _protect(data: bytes) -> bytes:
        return _call(ctypes.windll.crypt32.CryptProtectData, data)

    def _unprotect(data: bytes) -> bytes:
        return _call(ctypes.windll.crypt32.CryptUnprotectData, data)


def seal(plain: str) -> str:
    if not plain:
        return ''
    if PROTECTED:
        return 'dpapi:' + base64.b64encode(_protect(plain.encode())).decode()
    return 'b64:' + base64.b64encode(plain.encode()).decode()


def unseal(sealed: str) -> str:
    if not sealed:
        return ''
    scheme, _, payload = sealed.partition(':')
    raw = base64.b64decode(payload)
    if scheme == 'dpapi':
        if not PROTECTED:
            raise OSError('密码由 Windows 加密保存，只能在原电脑原账户下读取')
        return _unprotect(raw).decode()
    return raw.decode()
