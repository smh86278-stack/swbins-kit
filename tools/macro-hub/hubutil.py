# -*- coding: utf-8 -*-
"""자동화가 함께 쓰는 공용 도구 — DPAPI 암호화와 TOTP. 외부 패키지 없이 표준 라이브러리 + ctypes.

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


# ---------------------------------------------------------------- secrets.local.json 암호화
#
# 값은 'dpapi:<16진수>' 로 둔다 — 이 PC·이 Windows 계정에서만 풀린다(파일이 새도 못 읽는다, 다른 PC 로 옮기면 다시 넣어야 한다).
# 사람이 평문으로 넣어 두면 허브가 뜰 때·처음 읽을 때 encrypt_secrets_file 이 그 자리에서 암호화해 바꿔 쓴다.
# '_' 로 시작하는 키(설명)와 빈 값은 그대로 둔다.

SECRET_PREFIX = 'dpapi:'


def seal(plain):
    return SECRET_PREFIX + protect_text(plain)


def open_secret(value):
    """'dpapi:…' 이면 풀고, 아니면(평문·숫자 등) 그대로."""
    if isinstance(value, str) and value.startswith(SECRET_PREFIX):
        return unprotect_text(value[len(SECRET_PREFIX):])
    return value


def _plain_keys(data):
    return [k for k, v in data.items()
            if not k.startswith('_') and isinstance(v, str) and v and not v.startswith(SECRET_PREFIX)]


def write_secrets(path, data):
    import json
    import os
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def encrypt_secrets_file(path):
    """평문 값을 암호화해 다시 쓴다 — 바꾼 키 수. 파일이 없거나 깨졌으면 0(읽는 쪽이 알린다)."""
    import json
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    keys = _plain_keys(data) if isinstance(data, dict) else []
    if keys:
        for k in keys:
            data[k] = seal(data[k])
        write_secrets(path, data)
    return len(keys)


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


# ---------------------------------------------------------------- 비밀값 가리기

_REDACT = [
    (re.compile(r'(?i)(\bauthorization\s*[:=]\s*)\S.*'), r'\1●●●'),                     # Authorization: Basic …  — 줄 끝까지
    (re.compile(r'(?i)(\bbearer\s+)[A-Za-z0-9\-._~+/]+=*'), r'\1●●●'),
    (re.compile(r'(?i)(\b(?:password|passwd|pwd|pass|token|access_token|refresh_token|secret|client_secret|'
                r'api[_-]?key|apikey|private_key|cookie|session(?:id)?)\b["\']?\s*[:=]\s*["\']?)([^\s"\'&,;}]+)'), r'\1●●●'),
    (re.compile(r'(https?://[^\s:/@]+:)[^\s@/]+@'), r'\1●●●@'),                            # https://user:비밀번호@host
]


def redact(text, values=()):
    """로그 한 줄에서 비밀값을 ●●● 로 — 'password=…'·'token: …'·'Bearer …'·'Authorization: …'·URL 속 비밀번호,
    그리고 values(ctx.secret 으로 읽은 값 등 4글자 이상) 자체. 실행 로그 끝부분이 runs.jsonl·실패 알림 메일·웹훅·
    🩹 고쳐 달라기로 나가기 전에 허브가 줄마다 부른다(2026-10-19 보안 점검)."""
    s = str(text)
    for v in values:
        if v and len(v) >= 4:
            s = s.replace(v, '●●●')
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    return s


def _path_rules(python=None, root=None, home=None):
    """short_paths 의 바꿀 목록 — 긴 것부터(파이썬 실행 파일 → 파이썬 폴더 → 키트 폴더 → 사용자 폴더)."""
    import os
    import sys
    rules = []
    for exe in {python, sys.executable}:
        if exe:
            rules.append((os.path.normpath(exe), 'python'))
    py_dir = None
    if python:                                   # .venv\Scripts\python.exe → .venv · 내장 runtime\python.exe → runtime
        py_dir = os.path.dirname(python)
        if os.path.basename(py_dir).lower() in ('scripts', 'bin'):
            py_dir = os.path.dirname(py_dir)
    for pre in {sys.prefix, sys.base_prefix, py_dir}:
        if pre:
            rules.append((os.path.normpath(pre), '<python>'))
    root = root or os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
    rules.append((os.path.normpath(root) + os.sep, ''))
    home = home or os.path.expanduser('~')
    if home and home != '~':
        rules.append((os.path.normpath(home), '%USERPROFILE%'))
    out = []
    for src, rep in sorted(set(rules), key=lambda r: -len(r[0])):
        if len(src) < 4:                         # 'C:\' 같은 짧은 것은 바꾸지 않는다
            continue
        for v in {src, src.replace('\\', '/'), src.replace('\\', '\\\\')}:
            out.append((re.compile(re.escape(v), re.I), rep))
    return out


_PATHS = {}


def short_paths(text, python=None, root=None, home=None):
    """사용자에게 보이는 로그·알림에서 이 PC 의 실행 환경 경로를 줄인다 — 파이썬 실행 파일은 'python',
    파이썬(가상 환경) 폴더는 '<python>', 키트 폴더는 상대 경로(tools\\macro-hub\\…), 사용자 폴더는 %USERPROFILE%.
    파일 이름·줄 번호는 그대로라 디버깅에는 지장이 없다(데모 녹화 2026-10-23 — .venv 절대 경로가 실패 로그에 찍혔다)."""
    key = (python, root, home)
    if key not in _PATHS:
        _PATHS[key] = _path_rules(python, root, home)
    s = str(text)
    for rx, rep in _PATHS[key]:
        s = rx.sub(lambda m, r=rep: r, s)
    return s
