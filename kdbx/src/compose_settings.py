# compose_settings.py
# provider record (kdbx notes) + token -> 完整 settings JSON
#
# notes 结构 (纯数据, 无 schema/order 元字段):
#   { "base_url": ..., "extra_env": {...}(可省), "profiles": { name: {"model": ...,
#      "haiku"/"opus"/"sonnet": 覆盖(可省)} } }
#
# 合成规则: 骨架(恒定) + base_url + ANTHROPIC_AUTH_TOKEN(=entry.password)
#           + profile 模型覆盖 + extra_env
#
# CLI:
#   list   stdin  TSV: title\tbase64(password)\tbase64(notes)  (每行一条供应商记录)
#          stdout TSV: profile\tbase64(settings_json)
#          顺序 = kdbx 条目序 + notes profiles 声明序 (同一供应商编号连续)
#          非供应商记录输出:  title\t!SKIP
#
# 库用法: from compose_settings import compose, serialize
import sys, json, base64

# 恒定骨架 (12 份旧 notes 逐字节相同的部分)
SKELETON_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
    "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "500000",
}
ALLOW = ["Bash", "Edit", "MultiEdit", "Write", "Read", "Glob", "Grep", "LS",
         "WebFetch", "WebSearch", "Rm"]


def compose(notes, token, profile_name):
    """notes=供应商记录 dict, token=entry.password, profile_name=profiles 的 key.
    返回 dict (未序列化)."""
    if not isinstance(notes, dict) or 'profiles' not in notes or 'base_url' not in notes:
        raise ValueError('not a provider record')
    prof = notes['profiles'][profile_name]
    model = prof['model']
    env = {}
    env.update(notes.get('extra_env') or {})          # extra_env 在最前 (kimi 旧格式如此)
    env['ANTHROPIC_BASE_URL'] = notes['base_url']
    env['ANTHROPIC_AUTH_TOKEN'] = token
    env['ANTHROPIC_DEFAULT_HAIKU_MODEL'] = prof.get('haiku', model)
    env['ANTHROPIC_DEFAULT_OPUS_MODEL'] = prof.get('opus', model)
    env['ANTHROPIC_DEFAULT_SONNET_MODEL'] = prof.get('sonnet', model)
    env['ANTHROPIC_MODEL'] = model
    env.update(SKELETON_ENV)
    is_openrouter = ('openrouter' in profile_name.lower()
                     or 'openrouter' in notes['base_url'].lower())
    picker = None
    if not is_openrouter:
        picker = {
            "options": [
                {"behavesAs": "claude-haiku-5-5",
                 "label": "%s (Haiku)" % env['ANTHROPIC_DEFAULT_HAIKU_MODEL'],
                 "model": env['ANTHROPIC_DEFAULT_HAIKU_MODEL']},
                {"behavesAs": "claude-sonnet-5-5",
                 "label": "%s (Sonnet)" % env['ANTHROPIC_DEFAULT_SONNET_MODEL'],
                 "model": env['ANTHROPIC_DEFAULT_SONNET_MODEL']},
                {"behavesAs": "claude-opus-5-5",
                 "label": "%s (Opus)" % env['ANTHROPIC_DEFAULT_OPUS_MODEL'],
                 "model": env['ANTHROPIC_DEFAULT_OPUS_MODEL']},
            ]
        }
    result = {
        "current_Model_Provider": profile_name,
        "env": env,
        "permissions": {"defaultMode": "bypassPermissions", "allow": ALLOW},
        "skipDangerousModePermissionPrompt": True,
    }
    if picker is not None:
        # 插在 env 与 permissions 之间, 与 ~/.claude/settings.json 字段序一致
        result = {
            "current_Model_Provider": result["current_Model_Provider"],
            "env": result["env"],
            "modelPicker": picker,
            "permissions": result["permissions"],
            "skipDangerousModePermissionPrompt": result["skipDangerousModePermissionPrompt"],
        }
    return result


def serialize(obj):
    """复刻旧 notes 字节格式: 2 空格缩进, allow 数组单行紧凑(逗号后无空格), 末尾 \\n"""
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    old = '"allow": [\n' + ''.join(
        '      "%s"%s\n' % (a, ',' if i < len(ALLOW) - 1 else '')
        for i, a in enumerate(ALLOW)) + '    ]'
    new = '"allow": [' + ','.join('"%s"' % a for a in ALLOW) + ']'
    assert old in s, 'allow block not found in dumps output'
    return s.replace(old, new) + '\n'


def flatten(title, password, notes_text):
    """一条供应商记录 -> [(profile, settings_dict), ...] 按 notes 声明序."""
    notes = json.loads(notes_text)
    if not isinstance(notes, dict) or 'profiles' not in notes or 'base_url' not in notes:
        return None
    return [(name, compose(notes, password, name)) for name in notes['profiles']]


def main():
    if len(sys.argv) != 2 or sys.argv[1] != 'list':
        print('usage: compose_settings.py list  (TSV via stdin/stdout)', file=sys.stderr)
        sys.exit(64)
    for line in sys.stdin:
        line = line.rstrip('\n').rstrip('\r')
        if not line:
            continue
        title, pwd_b64, notes_b64 = line.split('\t')
        password = base64.b64decode(pwd_b64).decode('utf-8')
        notes_text = base64.b64decode(notes_b64).decode('utf-8')
        try:
            rows = flatten(title, password, notes_text)
        except Exception:
            rows = None
        if rows is None:
            print('%s\t!SKIP' % title)
            continue
        for profile, obj in rows:
            b64 = base64.b64encode(serialize(obj).encode('utf-8')).decode('ascii')
            print('%s\t%s' % (profile, b64))
    print('===END===')


if __name__ == '__main__':
    main()
