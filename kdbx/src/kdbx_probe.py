# kdbx_probe.py
# 从 DPAPI 凭据取主密码开 kdbx, 做精确读取 (load) 或关键字扫描 (scan).
# 供 test_kdbx_master_cred.ps1 -Mode Load/Scan 调用; 主密码不出 python 进程.
#
# exit code: 0 ok | 2 AUTH_FAIL | 3 CRED_MISSING | 4 OPEN_FAIL | 5 GROUP_NOT_FOUND | 6 ENTRY_NOT_FOUND | 10 IMPORT_FAIL
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdbx_cred


def open_kdbx(kdbx_path):
    try:
        password = kdbx_cred.load(kdbx_path)
    except kdbx_cred.CredMissing as e:
        print('CRED_MISSING: %s' % e, file=sys.stderr)
        sys.exit(3)
    try:
        from pykeepass import PyKeePass
        from pykeepass.exceptions import CredentialsError
    except Exception as e:
        print('IMPORT_FAIL:', type(e).__name__, e, file=sys.stderr)
        sys.exit(10)
    try:
        return PyKeePass(kdbx_path, password=password)
    except CredentialsError:
        print('AUTH_FAIL: stored password does NOT open the kdbx', file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print('OPEN_FAIL: kdbx file not found', file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        print('OPEN_FAIL:', type(e).__name__, e, file=sys.stderr)
        sys.exit(4)


def find_group(root, name):
    if root is None:
        return None
    if root.name == name:
        return root
    for sub in root.subgroups:
        hit = find_group(sub, name)
        if hit:
            return hit
    return None


def preview(pw):
    if not pw:
        return
    head = pw[:3]
    tail = pw[-3:] if len(pw) >= 6 else ''
    print('PREVIEW: head=%r tail=%r' % (head, tail))


def mode_load(a):
    kp = open_kdbx(a.kdbx)
    target = find_group(kp.root_group, a.group)
    if target is None:
        print('GROUP_NOT_FOUND: %s' % a.group, file=sys.stderr)
        print('--- top-level groups ---', file=sys.stderr)
        for g in kp.groups:
            print('  ' + g.name, file=sys.stderr)
        sys.exit(5)

    entry = None
    if not a.title:
        # 不指定条目: 只验证开库 + 组存在
        print('KDBX_OPEN_OK: group=%s entries=%d (entry check skipped)' % (
            target.name, len(target.entries)))
        print('OK')
        return
    for e in target.entries:
        if e.title == a.title and e.username == a.user:
            entry = e
            break
    if entry is None:
        print('ENTRY_NOT_FOUND: title=%s user=%s under %s' % (a.title, a.user, a.group), file=sys.stderr)
        print('--- entries in group ---', file=sys.stderr)
        for e in target.entries:
            print('  title=' + repr(e.title) + ' user=' + repr(e.username), file=sys.stderr)
        sys.exit(6)

    pw = entry.password or ''
    print('FOUND: group=%s title=%s username=%s url=%s' % (
        target.name, entry.title, entry.username or '', entry.url or ''))
    print('PASSWORD_LEN=%d' % len(pw))
    if not a.no_preview:
        preview(pw)
    print('OK')


def mode_scan(a):
    kp = open_kdbx(a.kdbx)
    key = a.key.lower()
    hits = []

    def path_of_group(g, root):
        chain = []
        cur = g
        while cur is not None and cur is not root:
            chain.append(cur.name)
            cur = cur.parentgroup
        return '/'.join(reversed(chain))

    def walk(g, root):
        for e in g.entries:
            blob = ' '.join([e.title or '', e.username or '', e.url or '']).lower()
            if key in blob:
                hits.append((path_of_group(g, root), e))
        for sub in g.subgroups:
            walk(sub, root)

    walk(kp.root_group, kp.root_group)

    print('=== SCAN: title/user/url contains %r (case-insensitive) ===' % a.key)
    if not hits:
        print('  (no match)')
    for (p, e) in hits:
        pw = e.password or ''
        print('  %s | title=%s user=%s url=%s pwd_len=%d' % (
            p, repr(e.title), repr(e.username or ''), repr(e.url or ''), len(pw)))
        if not a.no_preview:
            preview(pw)
    print('TOTAL_HITS=%d' % len(hits))
    print('OK')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['load', 'scan'])
    ap.add_argument('--kdbx', required=True)
    ap.add_argument('--group', default='')
    ap.add_argument('--title', default='')
    ap.add_argument('--user', default='')
    ap.add_argument('--key', default='')
    ap.add_argument('--no-preview', action='store_true')
    a = ap.parse_args()
    if a.mode == 'load':
        mode_load(a)
    else:
        mode_scan(a)


if __name__ == '__main__':
    main()
