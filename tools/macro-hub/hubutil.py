# -*- coding: utf-8 -*-
"""매크로가 함께 쓰는 공용 도구 — DPAPI 암호화와 TOTP. 외부 패키지 없이 표준 라이브러리 + ctypes.

    import hubutil
    hubutil.protect_text('비밀번호')      → 16진수 문자열 (현재 Windows 사용자만 풀 수 있다)
    hubutil.unprotect_text(그 문자열)
    hubutil.totp('JBSWY3DPEHPK3PXP')     → '123456'

protect_text 의 결과는 PowerShell 의 ConvertFrom-SecureString 과 같은 형식이라, 예전 도구(PowerShell)가 쓰던
자격증명 파일을 그대로 읽을 수 있고 그 반대도 된다.
"""
import base64
import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac
import re
import struct
import time


class _BLOB(ctypes.Structure):
    _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wt.LPCWSTR, ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_BLOB)]
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
                                        ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_BLOB)]
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def _call(fn, data, *extra):
    buf = ctypes.create_string_buffer(data, len(data))
    src = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _BLOB()
    if not fn(ctypes.byref(src), *extra, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), 'DPAPI 호출 실패 — 다른 Windows 계정·PC 에서 만든 값이거나 손상됐습니다')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect_bytes(data):
    return _call(lambda s, o: _crypt32.CryptProtectData(s, None, None, None, None, 0, o), data)


def unprotect_bytes(data):
    return _call(lambda s, o: _crypt32.CryptUnprotectData(s, None, None, None, None, 0, o), data)


def protect_text(plain):
    """문자열을 DPAPI(현재 사용자)로 암호화해 16진수로 돌려준다 — ConvertFrom-SecureString 과 같은 형식."""
    return protect_bytes(plain.encode('utf-16-le')).hex()


def unprotect_text(hex_text):
    return unprotect_bytes(bytes.fromhex(hex_text.strip())).decode('utf-16-le')


# ---------------------------------------------------------------- TOTP (RFC 6238)

def _key(base32_secret):
    clean = re.sub(r'[^A-Za-z2-7]', '', base32_secret).upper()
    if not clean:
        raise ValueError('base32 시크릿이 비어 있습니다')
    return base64.b32decode(clean + '=' * (-len(clean) % 8))


def totp(base32_secret, digits=6, period=30, at=None):
    counter = int((time.time() if at is None else at) // period)
    h = hmac.new(_key(base32_secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_remaining(period=30):
    return period - int(time.time()) % period
