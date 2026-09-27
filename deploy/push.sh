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
# 1) 파일 올리기: 이전 코드는 지우고 새로 푼다 (지운 파일이 서버에 남지 않게)
tar czf - --exclude='__pycache__' pyproject.toml src/contracts src/riot src/server deploy \
  | ssh "${SSH_OPTS[@]}" "$HOST" \
    'mkdir -p ~/riftflow/app && rm -rf ~/riftflow/app/src ~/riftflow/app/deploy && tar xzf - -C ~/riftflow/app'
# 2) 설치와 재시작: 방금 올린 스크립트를 서버에서 실행
ssh "${SSH_OPTS[@]}" "$HOST" 'bash ~/riftflow/app/deploy/remote_install.sh'
