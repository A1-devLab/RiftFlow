# RiftFlow — Riot Production API Key 신청 초안

작성일: 2026-09-27. 상태: **초안, 아직 제출하지 않음.**

기존 Personal 등록(App ID 865638)은 `docs/riot-application.md`에 있습니다. 이 문서는 공개 서비스를 위한 Production 키 신청서 초안입니다.
라이엇 신청 화면에 붙여 넣을 부분은 영어로, 팀용 설명은 한국어로 적었습니다. `[TODO: …]`는 실제 값으로 채워야 하는 자리입니다.

## 제출 전에 해결할 것

지금 상태로 제출하면 안 됩니다. 아래 항목은 라이엇 공개 정책이나 기존 Personal 신청서에 적은 약속과 어긋납니다.
신청서에는 실제 동작만 적어야 하므로, 고친 뒤 해당 문장을 확정합니다.

| # | 항목 | 지금 상태 | 해야 할 일 | 근거 |
|---|---|---|---|---|
| 1 | API 키 보관 | 각 PC의 `.env`에서 Riot·Gemini 키를 읽어 직접 호출 | 키를 보관하는 백엔드 서버를 만들고 앱은 서버만 호출 | 일반 정책: "Do not include your API key in your code, especially if you plan on distributing a binary" |
| 2 | 룬 자동 적용 | 픽창에서 추천이 나오면 클릭 없이 적용 | 설정에서 켜고 끄는 옵션으로 만들고, 기본값을 정한 뒤 신청서에 그대로 적기 | Personal 신청서에 "only after an explicit user click"이라고 적었음 |
| 3 | 인게임 아이템 추천 | "지금 살 아이템" 하나를 추천 | 선택지 3개와 짧은 이유를 보여 주는 방식으로 변경 | 롤 정책: "Apps that dictate player decisions" 비승인, 여러 선택지를 주는 것은 허용 |
| 4 | 429 처리 | 한도에 걸리면 오류만 표시 | `Retry-After`만큼 기다렸다 재시도, 받은 경기 상세는 저장해 다시 받지 않기 | Personal 신청서에 "handle HTTP 429 responses"라고 적었음. 롤 문서: "respect the rate limit" |
| 5 | Gemini로 보내는 데이터 | 최근 전적 요약·랭크·개인 룬 기록을 보냄 (계정 식별자는 보내지 않음) | 개인정보처리방침에 공개하고, 신청서에 정확히 적기 | Personal 신청서에 "does not automatically send ... match histories to Gemini"라고 적었음 |
| 6 | 개인정보처리방침·웹페이지 | 없음 | 공개 URL 준비 (다운로드, 개인정보처리방침, 문의처) | 공개 서비스 운영에 필요 |
| 7 | LCU 사용 경로 신고 | 신고 안 함 | 아래 "Local client APIs" 목록을 신청서에 포함 | 롤 문서: LCU 사용 시 사용 경로를 알려야 함 |

## Product name

RiftFlow

## Product URL

`[TODO: 공개 웹페이지 주소]`

Source repository: https://github.com/A1-devLab/RiftFlow (main branch)

## Target region

Korea (KR platform, ASIA regional routing)

## Product type

Windows desktop application (Python / PySide6) with a backend service that holds API credentials `[TODO: 서버 완성 후 확정]`.

## Short description — copy into the application

RiftFlow is an LLM-based League of Legends coach for Korean players. It grounds every answer in official Riot game data and the player's own match history, and helps players prepare in champion select with rune page recommendations that explain their reasoning.

## Detailed description — copy into the application

RiftFlow started as a five-person university capstone project and currently runs under an approved Personal API Key (App ID 865638) for private team testing. We are requesting a Production API Key to open the product to Korean players.

**What the product does**

- Match history: after the player signs in to the League client, RiftFlow resolves their own Riot ID with ACCOUNT-V1, shows their solo-queue rank from LEAGUE-V4, and lists their recent matches from MATCH-V5. Clicking a match opens a per-player statistics view of that completed game.
- Champion select coach: RiftFlow reads the local champion-select session to show the player's own team picks, the opposing team's locked picks and bans, and the likely lane opponent only when it is unambiguous. It never displays enemy hovers, which the client does not expose, and never identifies players hidden by the game.
- Rune recommendation: an LLM (Google Gemini) selects one rune page from the full official rune catalog, using the champion's and opponent's official ability descriptions, team composition tags from Data Dragon, the game mode, and preferences the player types in chat. Our code validates every page against the rune page rules before showing it and rejects invalid output. Each rune comes with a one-sentence reason based on its official description. We present this as a reasoned suggestion, not as a statistically optimal page; we do not claim player-base win rates.
- Rune page application: `[TODO: 2번 결정 후 확정 — 예: "When the player enables automatic application in settings, or clicks Apply, RiftFlow creates or replaces a single rune page named 'RiftFlow …' and selects it."]` RiftFlow never deletes or overwrites rune pages the player created. If no page slot is free, it changes nothing and tells the player how to free one.
- In-game: during a match, RiftFlow reads the local Live Client Data API to show the scoreboard the player can already see in the client (levels, KDA, CS, items), plus a team gold estimate derived from visible item prices and clearly labeled as an estimate. `[TODO: 3번 변경 후 확정 — 예: "When asked, it lists two or three item options with trade-offs based on official item descriptions, leaving the decision to the player."]` It does not track cooldowns, timers, vision, or any information unavailable in the client.
- General questions: players can ask about patches, items, practice methods, or their recent performance. Factual answers are restricted to retrieved official documents (Data Dragon and Korean patch notes).

**What the product does not do**

No MMR/ELO estimation, no de-anonymization of hidden players, no enemy cooldown or timer tracking, no gameplay automation, no augment or Arena item win rates, no betting, and no ads inside Riot properties. Arena (CHERRY) is excluded from rune recommendations because the mode does not use rune pages.

**Architecture and credentials**

`[TODO: 1번 완성 후 확정 — 예: "The desktop client never contains the Riot or Gemini keys. It calls our backend, which holds the keys server-side over HTTPS, caches match details and rune recommendations, and applies per-user rate limits."]`

**Data handling**

- Stored on the player's PC: a hashed account identifier with compact observations from their own recent matches (match ID, champion, lane opponent when unambiguous, result, KDA, rune page), used for personal matchup notes and rune history.
- Sent to Gemini: the player's typed messages, champion and item names from the current champion select or scoreboard, their rank tier and a summary of recent matches (champion, result, KDA, CS, duration), and their recent rune pages for the selected champion. Summoner names, Riot IDs, PUUIDs, and match IDs are not sent.
- Chat conversations are not stored.
- Privacy policy: `[TODO: 개인정보처리방침 URL]`

**Rate limits**

A full history load uses about 24 requests (22 on ASIA routing: 1 account lookup, 1 match ID list, 20 match details; 2 on KR routing: summoner and league). `[TODO: 4번 반영 후 확정 — 예: "Match details are cached, so refreshing after a game fetches only new matches (about 3 requests). HTTP 429 responses are retried after the Retry-After interval."]` Expected launch scale: `[TODO: 예상 사용자 수와 하루 요청 수]`.

**Monetization**

The product is free at launch. We will not monetize before our product status is Approved or Acknowledged, and any paid features would keep a free tier as required.

## Requested Riot APIs

| API | Endpoint | Purpose |
|---|---|---|
| ACCOUNT-V1 | `/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}` | Resolve the signed-in player's own Riot ID to a PUUID |
| SUMMONER-V4 | `/lol/summoner/v4/summoners/by-puuid/{puuid}` | Summoner level and profile icon |
| LEAGUE-V4 | `/lol/league/v4/entries/by-puuid/{puuid}` | Solo-queue rank |
| MATCH-V5 | `/lol/match/v5/matches/by-puuid/{puuid}/ids` | Recent match IDs |
| MATCH-V5 | `/lol/match/v5/matches/{matchId}` | Match details for history, statistics, and personal matchup notes |

No Tournament API or RSO access is requested.

## Local client APIs — disclosure

The League Client API (LCU) is unsupported by Riot; we understand it may change without notice.

| Endpoint | Method | Purpose |
|---|---|---|
| `/lol-summoner/v1/current-summoner` | GET | Detect the signed-in player's Riot ID |
| `/lol-gameflow/v1/gameflow-phase` | GET | Detect champion select, loading, and in-game phases |
| `/lol-gameflow/v1/session` | GET | Read the game mode (e.g., ARAM, Arena) during champion select |
| `/lol-champ-select/v1/session` | GET | Own team picks and hovers, enemy locked picks, completed bans |
| `/lol-perks/v1/pages` | GET | Find existing pages and free slots |
| `/lol-perks/v1/pages` | POST | Create the RiftFlow rune page |
| `/lol-perks/v1/pages/{id}` | DELETE | Replace only a previous page named "RiftFlow …" |
| `/lol-perks/v1/inventory` | GET | Check owned page slots |
| `/lol-perks/v1/currentpage` | PUT | Select the RiftFlow page |

Live Client Data API (local port 2999): `/liveclientdata/gamestats`, `/liveclientdata/playerlist`, `/liveclientdata/activeplayername` (with `/liveclientdata/activeplayer` as a fallback), read-only, to show the in-game scoreboard.

The rune page endpoints are the only write operations. The code also contains `/lol-end-of-game/v1/eog-stats-block` and `/liveclientdata/eventdata` for an internal developer tool; the released desktop app does not call them.

## Questions for Riot

1. Is automatic rune page application in champion select acceptable when it is a player-controlled setting and never touches pages the player created, or should it always require a click?
2. Is listing two or three in-game item options with trade-offs, based on official item descriptions and the client-visible scoreboard, within the permitted scope for Korean players?
3. Is showing a team gold estimate derived from visible item prices acceptable if it is clearly labeled as an estimate?

## Demo flow for reviewers

1. Install and run RiftFlow following the README `[TODO: 배포판이 생기면 설치 파일 기준으로 수정]`.
2. Sign in to the League client; the history screen loads the player's rank and recent matches. Click a match to open its statistics.
3. Enter champion select; the pick screen shows own-team picks and hovers, enemy locked picks, and bans. After hovering a champion for a moment, a validated rune page and its reasons appear.
4. Type "공격적으로 하고 싶어, 룬 다시 짜줘" (play aggressively, redo my runes); a new page reflecting the request appears.
5. `[TODO: 2번 결정에 맞춰 적용 흐름 설명]`
6. Start the game; the in-game screen shows the scoreboard and labeled gold estimate.

## Official references

- https://developer.riotgames.com/docs/portal
- https://developer.riotgames.com/docs/lol
- https://developer.riotgames.com/policies/general

## 팀용 요약

- Production 키 한도는 지역별 **10초 500회, 10분 30,000회**입니다(지금 Personal은 2분 100회). 사용료는 없습니다.
- 라이엇 문서상 신청에는 **동작하는 프로토타입**이 필요하고, 심사 기간은 정해져 있지 않습니다.
- 제출 순서: 위 표의 1~7번 해결 → `[TODO]` 채우기 → 개발자 포털 대시보드의 **Register Project**로 신청 → 결과는 포털 신청 메시지로 옴.
- 기존 Personal 등록을 갱신할지 새로 신청할지는 포털 화면에서 확인합니다. 이전처럼 같은 제품이면 중복 신청하지 않습니다.
- 팀원도 키를 써야 하면 포털에서 제품을 그룹 소유로 만들고 팀원 계정을 추가합니다.
