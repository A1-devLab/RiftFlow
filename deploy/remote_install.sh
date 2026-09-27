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
  echo "server.env를 만들었습니다. RIOT_API_KEY를 채운 뒤 다시 배포하세요: nano ~/riftflow/server.env"
fi

cp ~/riftflow/app/deploy/riftflow-api.service ~/.config/systemd/user/
systemctl --user daemon-reload

if grep -q '^RIOT_API_KEY=.\+' ~/riftflow/server.env; then
  systemctl --user enable riftflow-api >/dev/null 2>&1
  systemctl --user restart riftflow-api
  sleep 3
  echo "service: $(systemctl --user is-active riftflow-api)"
  python3 -c "import urllib.request; print('health:', urllib.request.urlopen('http://127.0.0.1:8787/v1/health', timeout=5).read().decode())"
else
  echo "RIOT_API_KEY가 비어 있어 서비스를 시작하지 않았습니다."
fi
