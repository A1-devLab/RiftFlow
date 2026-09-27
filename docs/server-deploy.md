# 미니 PC 서버 배포

설계는 `docs/server-architecture.md`에 있습니다. 이 문서는 지금 쓰는 미니 PC(Ubuntu 24.04, 마인크래프트 서버와 같은 PC)에 **서버 1단계**를 올리는 절차입니다.

미니 PC에 맞춘 결정:

- 실행: Docker 대신 **systemd 사용자 서비스 + SQLite**. 마인크래프트·디스코드 봇과 같은 방식이고, 메모리를 512MB로 제한해 마인크래프트에 영향을 주지 않습니다.
- 외부 공개: **DuckDNS 무료 주소 + Caddy 자동 HTTPS**. 미니 PC는 공유기 없이 통신사(KT)에서 공인 IP를 직접 받으므로 포트포워딩이 필요 없습니다. 대신 **호스트 방화벽(ufw)이 유일한 보호막**입니다.
- RiftFlow 서버 자체(`127.0.0.1:8787`)는 외부에 열지 않습니다. 외부 요청은 Caddy가 HTTPS로 받아 넘깁니다.

서버가 대신하는 것:

- **라이엇 데이터**(1단계): 계정·랭크·전적·경기 상세
- **AI**(2단계): 룬 추천, 픽창 질문, 인게임 질문, AI에게 질문. 서버가 공식 자료를 검색하고 Gemini를 부릅니다.

그래서 배포판 앱에는 API 키가 하나도 들어가지 않습니다. 서버의 공식 게임 자료는 매일 새벽 5시에 자동으로 갱신됩니다(`riftflow-knowledge.timer`).

## 구성

```text
인터넷 ──443/80──► 미니 PC (공인 IP 직접, ufw로 필요한 포트만 허용)
                               ├─ Caddy (HTTPS, 인증서 자동)  ──► 127.0.0.1:8787
                               ├─ riftflow-api (systemd 사용자 서비스, uvicorn)
                               │    └─ ~/riftflow/data/server.db (SQLite)
                               ├─ minecraft-survival (그대로)
                               └─ hy-discordbot (그대로)
```

| 서버 위치 | 내용 |
|---|---|
| `~/riftflow/app/` | 올린 코드 (`src/contracts`, `src/riot`, `src/server`, `deploy/`) |
| `~/riftflow/.venv/` | 서버 전용 Python 환경 (`deploy/requirements-server.txt`만 설치) |
| `~/riftflow/server.env` | 라이엇 키 등 설정. **본인만 읽기(600)** |
| `~/riftflow/data/server.db` | 기기 토큰, 사용량, 라이엇 데이터 캐시, 룬 추천 공유 캐시 |
| `~/riftflow/data/riftflow.db` | 공식 게임 자료 (AI 근거, 룬 트리). 매일 자동 갱신 |
| `~/.config/systemd/user/riftflow-api.service` | 서비스 정의 |
| `~/.config/systemd/user/riftflow-knowledge.{service,timer}` | 공식 자료 매일 갱신 |
| `~/.config/duckdns/` | DuckDNS 주소와 토큰. **본인만 읽기** |

## 처음 설치

키와 비밀번호는 채팅이나 저장소에 적지 않고, 서버에서 직접 입력합니다.

### 1. DuckDNS 주소 만들기 (브라우저)

1. https://www.duckdns.org 에 로그인합니다.
2. 원하는 이름으로 주소를 추가합니다 (예: `riftflow-team` → `riftflow-team.duckdns.org`). 현재 IP가 자동으로 들어갑니다.
3. 화면 위쪽의 **token**은 4번에서 서버에 직접 붙여 넣습니다.

### 2. 네트워크 (포트포워딩 불필요)

미니 PC는 KT에서 공인 IP를 DHCP로 직접 받습니다(`ip route`의 기본 게이트웨이가 통신사 장비). 공유기가 없으므로 포트포워딩 단계는 없습니다.
80번은 HTTPS 인증서 발급 확인에 쓰고, 막혀 있어도 Caddy가 443번으로 발급을 시도합니다. IP가 바뀔 수 있어 DuckDNS 자동 갱신(4번)이 필요합니다.

### 3. 코드 올리기 (개발 PC)

저장소 루트에서 실행합니다. sudo가 필요 없습니다.

```bash
RIFTFLOW_HOST=server@<서버 주소> RIFTFLOW_SSH_KEY=<개인 키 경로> RIFTFLOW_KNOWN_HOSTS=<known_hosts 경로> bash deploy/push.sh
```

처음에는 `server.env`를 만들고, 라이엇 키가 비어 있어 서비스를 시작하지 않은 채 끝납니다.

### 4. 서버에서 한 번만 할 일 (SSH 접속 후, sudo 필요)

```bash
sudo apt update && sudo apt install -y caddy && sudo loginctl enable-linger server
```

방화벽: 쓰는 포트만 열고 나머지는 막습니다. **SSH(22)를 먼저 허용**해야 원격 접속이 끊기지 않습니다.

```bash
sudo ufw allow 22/tcp && sudo ufw allow 25565/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw default deny incoming && sudo ufw enable
```

Caddy 설정 (`riftflow-team`을 1번에서 만든 이름으로 바꿉니다):

```bash
sed 's/DOMAIN/riftflow-team.duckdns.org/' ~/riftflow/app/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

라이엇 키와 Gemini 키 입력 (`RIOT_API_KEY=`, `GEMINI_API_KEY=` 뒤에 각각 붙여 넣고 저장):

```bash
nano ~/riftflow/server.env
```

DuckDNS 주소 자동 갱신 (집 IP가 바뀌어도 주소가 따라가게):

```bash
mkdir -p ~/.config/duckdns && chmod 700 ~/.config/duckdns && echo riftflow-team > ~/.config/duckdns/domain
nano ~/.config/duckdns/token
chmod 600 ~/.config/duckdns/token
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/bin/python3 $HOME/riftflow/app/deploy/duckdns_update.py") | crontab -
```

### 5. 다시 배포해서 서비스 시작 (개발 PC)

3번 명령을 한 번 더 실행하면 `service: active`와 `health: {"status":"ok"}`가 나옵니다.

### 6. 외부에서 확인

휴대폰 데이터(와이파이 끄고)로 `https://riftflow-team.duckdns.org/v1/health`를 열어 `{"status":"ok"}`가 보이면 됩니다.

### 7. 앱 연결

배포판은 exe 옆의 `server.txt`에 서버 주소가 들어 있어 따로 할 일이 없습니다(아래 "배포판 만들기").
저장소에서 직접 실행하는 개발용 앱은 `.env`에 서버 주소를 넣으면 전적·AI에 키가 필요 없습니다.

```text
RIFTFLOW_SERVER_URL=https://riftflow-team.duckdns.org
```

앱의 **설정 및 데이터** 화면에 `AI: RiftFlow 서버 · 전적: RiftFlow 서버`로 표시됩니다.

## 배포판 만들기 (개발 PC)

```bash
.venv\Scripts\python.exe packaging\build.py --server-url https://riftflow-team.duckdns.org
```

`dist/RiftFlow-<버전>.zip`이 만들어집니다(약 50MB). 받는 사람은 압축을 풀고 `RiftFlow.exe`를 더블클릭하면 됩니다. 안에 `사용법.txt`가 들어 있습니다.

- 키는 들어가지 않습니다. AI와 전적은 `server.txt`의 서버로 처리합니다.
- 서버 주소가 바뀌면 다시 빌드하지 않고 `RiftFlow/server.txt`만 고쳐도 됩니다.
- 배포판은 데이터를 `%LOCALAPPDATA%\RiftFlow`에 저장하고, 처음 켤 때 공식 게임 자료를 자동으로 받습니다.
- 서명하지 않은 exe라 처음 실행할 때 "Windows의 PC 보호" 창이 뜹니다. "추가 정보 → 실행"을 누르면 됩니다.
- PyInstaller가 필요합니다: `uv pip install --python .venv\Scripts\python.exe pyinstaller` (pip 환경이면 `pip install pyinstaller`)

## 운영

| 할 일 | 명령 (미니 PC) |
|---|---|
| 상태 | `systemctl --user status riftflow-api` |
| 로그 | `journalctl --user -u riftflow-api -n 100` |
| 재시작 | `systemctl --user restart riftflow-api` |
| 코드 업데이트 | 개발 PC에서 `deploy/push.sh` |
| DB 백업 | `sqlite3 ~/riftflow/data/server.db ".backup ~/riftflow/data/backup-$(date +%F).db"` (sqlite3가 없으면 `python3 -c` 로 대체) |

한도 설정은 `server.env`에서 바꾸고 재시작합니다.

- `RIFTFLOW_RIOT_LIMITS`: 라이엇 요청 한도. Personal 키 기본값 `18/1,90/120`, Production 키 승인 뒤 `480/10,29000/600`
- `RIFTFLOW_DEVICE_DAILY_REQUESTS`: 기기당 하루 전적 요청 수 (기본 300)
- `RIFTFLOW_DEVICE_DAILY_AI`: 기기당 하루 AI 요청 수 (기본 40). 서버의 Gemini 무료 한도(프로젝트당 하루 20회 수준)는 모든 사용자가 나눠 쓰므로, 여러 명이 쓰면 Gemini 결제 연결이 필요합니다

## 주의

- 지금 서버에 넣는 라이엇 키는 **Personal 키**입니다. 라이엇 문서상 Personal 키는 공개 알파·베타를 포함한 공개 사용이 안 됩니다. 팀원과 지인 몇 명의 비공개 테스트까지만 쓰고, 공개하려면 Production 키로 바꿉니다.
- 22번(SSH)이 외부에 열려 있고 비밀번호 로그인도 허용되어 있습니다. 키 로그인이 되므로 `/etc/ssh/sshd_config`에서 `PasswordAuthentication no`로 바꾸는 것을 권합니다. 바꾸기 전에 키로 접속되는 것을 꼭 확인하세요.
