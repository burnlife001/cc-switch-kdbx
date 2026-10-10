# kdbx_read_entries.py
# 读 kdbx 指定组全部条目 -> stdout TSV: title \t base64(password) \t base64(notes)
# 主密码由 kdbx_cred 从 DPAPI 凭据文件读取, 全程不经过 PowerShell 变量/管道/命令行.
#
# exit code: 0 ok | 2 AUTH_FAIL | 3 CRED_MISSING | 4 OPEN_FAIL | 5 GROUP_NOT_FOUND | 10 IMPORT_FAIL
import argparse
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdbx_cred


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kdbx', required=True)
    ap.add_argument('--group', required=True)
    a = ap.parse_args()

    try:
        password = kdbx_cred.load(a.kdbx)
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
        kp = PyKeePass(a.kdbx, password=password)
    except CredentialsError:
        print('AUTH_FAIL', file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print('OPEN_FAIL:', type(e).__name__, e, file=sys.stderr)
        sys.exit(4)

    g = find_group(kp.root_group, a.group)
    if g is None:
        print('GROUP_NOT_FOUND: %s' % a.group, file=sys.stderr)
        sys.exit(5)

    for e in g.entries:
        pw = base64.b64encode((e.password or '').encode('utf-8')).decode('ascii')
        nt = base64.b64encode((e.notes or '').encode('utf-8')).decode('ascii')
        print(e.title.replace('\t', ' ') + '\t' + pw + '\t' + nt)


if __name__ == '__main__':
    main()
