# kdbx_cred.py
# kdbx 主密码凭据存取: Windows DPAPI (CryptProtectData, 当前用户范围), 落盘为 base64 文本文件.
#
# 为什么不用 Windows Credential Manager:
#   该机写入的 generic 凭据 (LOCAL_MACHINE persist) 会在会话间莫名丢失 (CredWrite 成功,
#   同会话 CredRead 成功, 之后新进程 CredRead 1168), 不可靠.
# 为什么不经过 PowerShell 管道:
#   Windows PowerShell 5.1 管道给原生进程 stdin 会自动加 BOM (﻿), 密码多一个字符 -> AUTH_FAIL.
# 安全等级: 与 Credential Manager generic 凭据等效 — 都是 user-scope DPAPI.
#
# 用法:
#   python kdbx_cred.py store  --kdbx <path>   # getpass 输入 -> 试开 kdbx 校验 -> DPAPI 落盘
#   python kdbx_cred.py check  --kdbx <path>   # 读回 + 试开 kdbx;  exit 0 通
#   python kdbx_cred.py probe  --kdbx <path>   # 只验证凭据文件可解密 (不开 kdbx)
#   python kdbx_cred.py delete --kdbx <path>   # 删除凭据文件
#   import kdbx_cred; pw = kdbx_cred.load(kdbx_path)   # 库用法
#
# exit code: 0 ok | 2 密码开不了 kdbx | 3 凭据缺失/不可解密 | 4 kdbx 打不开(其它原因)
import argparse
import base64
import ctypes
import ctypes.wintypes as wt
import os
import sys

CRED_FILENAME = '.kdbx_master.cred'


class CredMissing(Exception):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wt.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _crypt_protect(data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _crypt_unprotect(data: bytes) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def cred_path(kdbx_path: str) -> str:
    # 凭据文件放在 kdbx 同目录 (kdbx_cpq/), 已加入 .gitignore
    return os.path.join(os.path.dirname(os.path.abspath(kdbx_path)), CRED_FILENAME)


def load(kdbx_path: str) -> str:
    """读凭据文件并 DPAPI 解密, 返回主密码明文. 缺文件/解密失败抛 CredMissing."""
    path = cred_path(kdbx_path)
    if not os.path.exists(path):
        raise CredMissing('credential file not found: %s' % path)
    try:
        blob = base64.b64decode(open(path, 'r', encoding='ascii').read().strip())
        return _crypt_unprotect(blob).decode('utf-8')
    except Exception as e:
        raise CredMissing('credential undecryptable: %s (%s)' % (path, e))


def verify_kdbx(kdbx_path: str, password: str) -> None:
    """试开 kdbx; 失败直接 sys.exit (2=密码错 4=其它)."""
    from pykeepass import PyKeePass
    from pykeepass.exceptions import CredentialsError
    try:
        PyKeePass(kdbx_path, password=password)
    except CredentialsError:
        print('AUTH_FAIL: password does NOT open the kdbx', file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print('OPEN_FAIL:', type(e).__name__, e, file=sys.stderr)
        sys.exit(4)


def prompt_password(prompt='Enter kdbx master password:') -> str:
    """逐键读密码, 每键回显 '*', 支持退格; 非交互终端直接失败 (防后台/管道场景卡死)."""
    if not sys.stdin.isatty():
        print('store requires an interactive terminal', file=sys.stderr)
        sys.exit(1)
    import msvcrt
    sys.stderr.write(prompt)
    sys.stderr.flush()
    chars = []
    while True:
        ch = msvcrt.getwch()
        if ch in ('\r', '\n'):
            sys.stderr.write('\n')
            break
        if ch == '\x03':            # Ctrl+C
            raise KeyboardInterrupt
        if ch == '\x08':            # Backspace
            if chars:
                chars.pop()
                sys.stderr.write('\b \b')
            continue
        if ch in ('\x00', '\xe0'):  # 功能键前缀, 吞掉后续扫描码
            msvcrt.getwch()
            continue
        chars.append(ch)
        sys.stderr.write('*')
        sys.stderr.flush()
    return ''.join(chars)


def store(kdbx_path: str, password: str = None) -> str:
    if password is None:
        password = prompt_password()
    if not password:
        print('empty password', file=sys.stderr)
        sys.exit(1)
    print('[store] verifying password against kdbx before writing credential...', file=sys.stderr)
    verify_kdbx(kdbx_path, password)
    print('[store] VERIFY_OK: password opens the kdbx', file=sys.stderr)
    blob = _crypt_protect(password.encode('utf-8'))
    path = cred_path(kdbx_path)
    with open(path, 'w', encoding='ascii') as f:
        f.write(base64.b64encode(blob).decode('ascii'))
    return path


def main():
    ap = argparse.ArgumentParser(description='kdbx master password DPAPI credential store')
    ap.add_argument('mode', choices=['store', 'check', 'probe', 'delete'])
    ap.add_argument('--kdbx', required=True)
    a = ap.parse_args()
    path = cred_path(a.kdbx)

    if a.mode == 'store':
        p = store(a.kdbx)
        print('STORED: %s (DPAPI, current-user scope)' % p, file=sys.stderr)
        return

    if a.mode == 'delete':
        if not os.path.exists(path):
            print('NOT_FOUND: nothing to delete')
            return
        os.remove(path)
        print('DELETED: %s' % path)
        return

    if a.mode == 'probe':
        try:
            pw = load(a.kdbx)
        except CredMissing as e:
            print('NOT_FOUND: %s' % e)
            sys.exit(3)
        print('FOUND: %s (decrypts ok, %d chars, NOT echoed)' % (path, len(pw)))
        return

    if a.mode == 'check':
        try:
            pw = load(a.kdbx)
        except CredMissing as e:
            print('CRED_MISSING: %s' % e, file=sys.stderr)
            sys.exit(3)
        verify_kdbx(a.kdbx, pw)
        print('CHECK_OK: credential decrypts and opens the kdbx')
        return


if __name__ == '__main__':
    main()
