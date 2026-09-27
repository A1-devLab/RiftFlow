# 미니 PC 서버 배포

설계는 `docs/server-architecture.md`에 있습니다. 이 문서는 지금 쓰는 미니 PC(Ubuntu 24.04, 마인크래프트 서버와 같은 PC)에 **서버 1단계**를 올리는 절차입니다.

미니 PC에 맞춘 결정:

- 실행: Docker 대신 **systemd 사용자 서비스 + SQLite**. 마인크래프트·디스코드 봇과 같은 방식이고, 메모리를 512MB로 제한해 마인크래프트에 영향을 주지 않습니다.
- 외부 공개: **공유기 포트포워딩(443, 80) + DuckDNS 무료 주소 + Caddy 자동 HTTPS**.
- RiftFlow 서버 자체(`127.0.0.1:8787`)는 외부에 열지 않습니다. 외부 요청은 Caddy가 HTTPS로 받아 넘깁니다.

1단계에서 서버가 대신하는 것은 **라이엇 데이터(계정·랭크·전적·경기 상세)** 입니다. AI(Gemini)는 아직 각 앱의 키로 호출합니다(2단계에서 서버로 이전).

## 구성

```text
인터넷 ──443/80──► 공유기 ──► 미니 PC
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
| `~/riftflow/data/server.db` | 기기 토큰, 사용량, 라이엇 데이터 캐시 |
| `~/.config/systemd/user/riftflow-api.service` | 서비스 정의 |
| `~/.config/duckdns/` | DuckDNS 주소와 토큰. **본인만 읽기** |

## 처음 설치

키와 비밀번호는 채팅이나 저장소에 적지 않고, 서버에서 직접 입력합니다.

### 1. DuckDNS 주소 만들기 (브라우저)

1. https://www.duckdns.org 에 로그인합니다.
2. 원하는 이름으로 주소를 추가합니다 (예: `riftflow-team` → `riftflow-team.duckdns.org`). 현재 IP가 자동으로 들어갑니다.
3. 화면 위쪽의 **token**은 4번에서 서버에 직접 붙여 넣습니다.

### 2. 공유기 포트포워딩

마인크래프트(25565)와 같은 방식으로 아래 두 개를 미니 PC로 넘깁니다.

| 외부 포트 | 내부 포트 | 용도 |
|---|---|---|
| 443 (TCP) | 443 | HTTPS |
| 80 (TCP) | 80 | HTTPS 인증서 발급 확인용. 통신사가 80을 막으면 443만으로도 발급됩니다 |

### 3. 코드 올리기 (개발 PC)

저장소 루트에서 실행합니다. sudo가 필요 없습니다.

```bash
RIFTFLOW_HOST=server@<서버 주소> RIFTFLOW_SSH_KEY=<개인 키 경로> RIFTFLOW_KNOWN_HOSTS=<known_hosts 경로> bash deploy/push.sh
```

처음에는 `server.env`를 만들고, 라이엇 키가 비어 있어 서비스를 시작하지 않은 채 끝납니다.

### 4. 서버에서 한 번만 할 일 (SSH 접속 후, sudo 필요)

```bash
sudo apt update && sudo apt install -y caddy
sudo loginctl enable-linger server
sudo ufw status
```

`ufw status`가 `active`면 포트를 엽니다.

```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
```

Caddy 설정 (`riftflow-team`을 1번에서 만든 이름으로 바꿉니다):

```bash
sed 's/DOMAIN/riftflow-team.duckdns.org/' ~/riftflow/app/deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

라이엇 키 입력 (`RIOT_API_KEY=` 뒤에 붙여 넣고 저장):

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

각 사용자의 `.env`에 서버 주소를 넣습니다. 그러면 전적 기능에 라이엇 키가 필요 없습니다.

```text
RIFTFLOW_SERVER_URL=https://riftflow-team.duckdns.org
```

앱의 **설정 및 데이터** 화면에 `전적: RiftFlow 서버`로 표시됩니다.

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

## 주의

- 지금 서버에 넣는 라이엇 키는 **Personal 키**입니다. 라이엇 문서상 Personal 키는 공개 알파·베타를 포함한 공개 사용이 안 됩니다. 팀원과 지인 몇 명의 비공개 테스트까지만 쓰고, 공개하려면 Production 키로 바꿉니다.
- 22번(SSH)이 외부에 열려 있고 비밀번호 로그인도 허용되어 있습니다. 키 로그인이 되므로 `/etc/ssh/sshd_config`에서 `PasswordAuthentication no`로 바꾸는 것을 권합니다. 바꾸기 전에 키로 접속되는 것을 꼭 확인하세요.
