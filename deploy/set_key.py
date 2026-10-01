"""API 키를 화면에 보이지 않게 입력받아 로컬 .env와 서버 server.env에 넣는다.

    .venv\\Scripts\\python.exe deploy\\set_key.py HASA_API_KEY --set LLM_PROVIDER=hasa

- 키는 getpass로 받아 화면·셸 기록·채팅에 남지 않는다. 출력에는 앞 6자만 보인다.
- 서버에는 SSH 표준 입력으로 보내므로 명령줄(프로세스 목록)에도 키가 나오지 않는다.
- 서버 접속 주소는 RIFTFLOW_HOST(기본 minipc, ~/.ssh/config의 별칭)로 정한다.
- --set NAME=VALUE는 키가 아닌 설정(제공자, 모델 이름)을 함께 바꿀 때 쓴다.
"""
import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r'^[A-Z][A-Z0-9_]*$')

# 서버에서 실행하는 코드. 표준 입력의 JSON({name: value})으로 server.env를 고치고 API를 다시 시작한다.
REMOTE = r'''
import json, os, subprocess, sys, time, urllib.request
values = json.loads(sys.stdin.read())
path = os.path.expanduser("~/riftflow/server.env")
lines = open(path, encoding="utf-8").read().splitlines()
add = values.pop("__add__", None)
if add:
    current = next((line.split("=", 1)[1] for line in lines if line.startswith(add + "=")), "")
    keys = [k.strip() for k in current.split(",") if k.strip()]
    if values[add] not in keys:
        keys.append(values[add])
    values[add] = ",".join(keys)
for name, value in values.items():
    for i, line in enumerate(lines):
        if line.startswith(name + "="):
            lines[i] = name + "=" + value
            break
    else:
        lines.append(name + "=" + value)
fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
os.replace(path + ".tmp", path)
subprocess.run(["systemctl", "--user", "restart", "riftflow-api"], check=True)
time.sleep(3)
count = len([k for k in values.get(add, "").split(",") if k]) if add else None
print("server.env 갱신:", ", ".join(values), ("(키 %d개)" % count) if count else "", "· 서비스", subprocess.run(["systemctl", "--user", "is-active", "riftflow-api"], capture_output=True, text=True).stdout.strip())
print("health:", urllib.request.urlopen("http://127.0.0.1:8787/v1/health", timeout=5).read().decode())
'''


def check_key(name, key):
    """키처럼 보이지 않으면 이유를 돌려준다. Ctrl+V가 글자(0x16) 하나로 들어간 적이 있어서 넣기 전에 막는다."""
    if not key:
        return '키가 비어 있습니다.'
    if any(c.isspace() for c in key) or not key.isascii() or not key.isprintable():
        return '키에 공백이나 보이지 않는 글자가 들어 있습니다 (붙여넣기가 제대로 되지 않았을 수 있습니다).'
    if name == 'HASA_API_KEY' and (not key.startswith('sk-') or len(key) < 20):
        return 'HASA 키는 sk-로 시작하는 긴 문자열입니다 (입력된 길이 %d자).' % len(key)
    return None


def merged(current, new):
    """쉼표로 이은 키 목록 뒤에 새 키를 덧붙인다 (이미 있으면 그대로)."""
    keys = [k.strip() for k in current.split(',') if k.strip()]
    return ','.join(keys if new in keys else keys + [new])


def update_env(path, values):
    values = dict(values)
    add = values.pop('__add__', None)
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    if add:
        current = next((line.split('=', 1)[1] for line in lines if line.startswith(add + '=')), '')
        values[add] = merged(current, values[add])
    for name, value in values.items():
        for i, line in enumerate(lines):
            if line.startswith(name + '='):
                lines[i] = '%s=%s' % (name, value)
                break
        else:
            lines.append('%s=%s' % (name, value))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='API 키를 보이지 않게 입력해 .env와 서버에 넣습니다.')
    parser.add_argument('key_name', help='예: HASA_API_KEY')
    parser.add_argument('--set', action='append', default=[], metavar='NAME=VALUE', help='함께 바꿀 일반 설정')
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--local-only', action='store_true', help='로컬 .env에만 넣기')
    target.add_argument('--server-only', action='store_true', help='서버 server.env에만 넣기')
    parser.add_argument('--add', action='store_true',
                        help='기존 키를 지우지 않고 쉼표로 덧붙이기 (팀원 키 추가). 같은 키는 한 번만 들어간다')
    args = parser.parse_args()
    if not NAME.match(args.key_name):
        parser.error('키 이름은 대문자·숫자·_ 로 씁니다 (예: HASA_API_KEY)')
    extra = {}
    for item in args.set:
        name, _, value = item.partition('=')
        if not NAME.match(name) or not value or '\n' in value:
            parser.error('--set 형식이 잘못되었습니다: %s' % item)
        extra[name] = value

    print('붙여넣기: 마우스 오른쪽 클릭 (명령 프롬프트에서는 Ctrl+V가 글자로 들어갈 수 있습니다).')
    key = getpass.getpass('%s 붙여넣기 (화면에 보이지 않습니다) 후 Enter: ' % args.key_name).strip()
    problem = check_key(args.key_name, key)
    if problem:
        sys.exit(problem + ' 아무것도 바꾸지 않았습니다. 다시 실행하세요.')
    values = dict(extra, **{args.key_name: key})
    print('입력됨: %s…(%d자)%s' % (key[:6], len(key), ' · 기존 키 뒤에 덧붙임' if args.add else ''))
    if args.add:
        values['__add__'] = args.key_name

    if not args.server_only:
        update_env(ROOT / '.env', values)
        print('로컬 .env 갱신:', ', '.join(k for k in values if k != '__add__'))
    if not args.local_only:
        host = os.environ.get('RIFTFLOW_HOST') or 'minipc'
        # 원격 코드는 base64로 감싸 셸 따옴표·줄바꿈 문제를 피한다. 키는 명령줄이 아니라 표준 입력으로 간다.
        code = base64.b64encode(REMOTE.encode('utf-8')).decode('ascii')
        command = "python3 -c \"import base64; exec(base64.b64decode('%s'))\"" % code
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', host, command],
                                input=json.dumps(values), text=True, encoding='utf-8')
        if result.returncode:
            sys.exit('서버 갱신 실패 (ssh 종료 코드 %d). 로컬 .env는 이미 바뀌었습니다.' % result.returncode)


if __name__ == '__main__':
    main()
