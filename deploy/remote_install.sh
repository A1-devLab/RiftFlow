#!/usr/bin/env bash
# 미니 PC에서 실행된다 (deploy/push.sh가 부름). sudo 없이 사용자 권한으로만 설치한다.
set -euo pipefail

mkdir -p ~/riftflow/data ~/.config/systemd/user
[ -d ~/riftflow/.venv ] || python3 -m venv ~/riftflow/.venv
~/riftflow/.venv/bin/pip install -q --upgrade pip
~/riftflow/.venv/bin/pip install -q -r ~/riftflow/app/deploy/requirements-server.txt

if [ ! -f ~/riftflow/server.env ]; then
  cp ~/riftflow/app/deploy/server.env.example ~/riftflow/server.env
  chmod 600 ~/riftflow/server.env
  echo "server.env를 만들었습니다. RIOT_API_KEY와 GEMINI_API_KEY를 채운 뒤 다시 배포하세요: nano ~/riftflow/server.env"
else
  # 새 버전에 추가된 설정만 덧붙인다. 이미 있는 값(키 포함)은 건드리지 않는다.
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    grep -q "^${line%%=*}=" ~/riftflow/server.env || { echo "$line" >> ~/riftflow/server.env; echo "server.env에 추가: ${line%%=*}"; }
  done < ~/riftflow/app/deploy/server.env.example
fi

cp ~/riftflow/app/deploy/riftflow-api.service ~/riftflow/app/deploy/riftflow-knowledge.service \
   ~/riftflow/app/deploy/riftflow-knowledge.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now riftflow-knowledge.timer >/dev/null 2>&1

# 공식 자료가 아직 없으면 한 번 바로 받는다 (1분 안팎).
if [ ! -s ~/riftflow/data/riftflow.db ]; then
  echo "공식 게임 자료를 처음 받는 중…"
  systemctl --user start riftflow-knowledge.service || echo "공식 자료 수집 실패: journalctl --user -u riftflow-knowledge 확인"
fi

if grep -q '^RIOT_API_KEY=.\+' ~/riftflow/server.env; then
  systemctl --user enable riftflow-api >/dev/null 2>&1
  systemctl --user restart riftflow-api
  sleep 3
  echo "service: $(systemctl --user is-active riftflow-api)"
  python3 -c "import urllib.request; print('health:', urllib.request.urlopen('http://127.0.0.1:8787/v1/health', timeout=5).read().decode())"
  grep -q '^GEMINI_API_KEY=.\+' ~/riftflow/server.env || echo "GEMINI_API_KEY가 비어 있어 AI 기능은 꺼져 있습니다."
else
  echo "RIOT_API_KEY가 비어 있어 서비스를 시작하지 않았습니다."
fi
