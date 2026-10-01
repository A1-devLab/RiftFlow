#!/usr/bin/env bash
# 개발 PC(저장소 루트)에서 미니 PC로 서버 코드를 올리고 서비스를 다시 시작한다.
# 서버에 git이 없어서 필요한 파일만 tar로 묶어 SSH로 보낸다. sudo는 쓰지 않는다.
#
#   RIFTFLOW_HOST=server@서버주소 RIFTFLOW_SSH_KEY=경로 RIFTFLOW_KNOWN_HOSTS=경로 bash deploy/push.sh
set -euo pipefail

HOST="${RIFTFLOW_HOST:?RIFTFLOW_HOST에 접속 주소를 넣으세요 (예: server@서버주소)}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10)
[ -n "${RIFTFLOW_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RIFTFLOW_SSH_KEY")
[ -n "${RIFTFLOW_KNOWN_HOSTS:-}" ] && SSH_OPTS+=(-o "UserKnownHostsFile=$RIFTFLOW_KNOWN_HOSTS")

cd "$(dirname "$0")/.."
# 1) 파일 올리기: 새 폴더에 다 받은 뒤에만 바꿔 끼운다 (지운 파일이 서버에 남지 않게).
#    예전에는 기존 코드를 먼저 지우고 받아서, 전송이 끊기면 서버에 코드가 반쯤만 남았다.
tar czf - --exclude='__pycache__' pyproject.toml src/contracts src/riot src/server src/knowledge src/rag src/game_phases src/ui deploy \
  | ssh "${SSH_OPTS[@]}" "$HOST" \
    'set -e; rm -rf ~/riftflow/app.new && mkdir -p ~/riftflow/app.new && tar xzf - -C ~/riftflow/app.new
     test -f ~/riftflow/app.new/src/server/app.py
     rm -rf ~/riftflow/app.old
     if [ -d ~/riftflow/app ]; then mv ~/riftflow/app ~/riftflow/app.old; fi
     mv ~/riftflow/app.new ~/riftflow/app'
# 2) 설치와 재시작: 방금 올린 스크립트를 서버에서 실행
ssh "${SSH_OPTS[@]}" "$HOST" 'bash ~/riftflow/app/deploy/remote_install.sh'
