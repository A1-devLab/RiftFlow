"""FastAPI app. Run with: uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8787

Caddy가 HTTPS를 받아 127.0.0.1:8787로 넘긴다. 이 서버는 외부에 직접 열지 않는다.
"""
import hashlib
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from typing import List, Optional

import requests
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from contracts.riot import RiotApiError

from .ai import AiService
from .config import Settings
from .db import Database
from .riot_data import NotFound, RiotBusy, RiotData, RiotGateway

KST = timezone(timedelta(hours=9))
PUUID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
MATCH_ID = re.compile(r"^[A-Z0-9]{2,6}_\d{1,15}$")
NOT_FOUND_MESSAGES = {"player_not_found": "소환사를 찾을 수 없습니다.",
                      "match_not_found": "경기 기록을 찾을 수 없습니다.",
                      "match_data_unavailable": "최근 경기 기록이 없습니다."}


class RuneBody(BaseModel):
    champion: str = Field(min_length=1, max_length=40)
    opponent: Optional[str] = Field(default=None, max_length=40)
    view: dict = Field(default_factory=dict)
    user_requests: List[str] = Field(default_factory=list, max_length=5)
    recent_pages: List[dict] = Field(default_factory=list, max_length=5)


class PickBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    champion: str = Field(min_length=1, max_length=40)
    opponent: Optional[str] = Field(default=None, max_length=40)
    view: dict = Field(default_factory=dict)
    user_requests: List[str] = Field(default_factory=list, max_length=5)
    observations: Optional[dict] = None
    history: List[dict] = Field(default_factory=list, max_length=8)


class InGameBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    view: dict = Field(default_factory=dict)
    history: List[dict] = Field(default_factory=list, max_length=8)


class GeneralBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    context: Optional[dict] = None
    history: List[dict] = Field(default_factory=list, max_length=8)


class ApiError(Exception):
    def __init__(self, status, code, message, retry_after=None):
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after
        super().__init__(message)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def seconds_until_kst_midnight(now):
    moment = datetime.fromtimestamp(now, KST)
    midnight = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - moment).total_seconds()) + 1


def client_ip(request):
    """Caddy(같은 PC)를 거쳐 온 요청이면 X-Forwarded-For의 마지막 주소를 믿는다."""
    host = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for")
    if host in ("127.0.0.1", "::1") and forwarded:
        return forwarded.split(",")[-1].strip()
    return host


def gemini_generator(settings):
    """설정한 제공자(LLM_PROVIDER)의 호출 함수.

    HASA는 동시 1건 한도라 429에 짧게 기다렸다 한 번 더 보낸다. Gemini 키도 있으면 HASA가 실패할 때 Gemini로 넘긴다.
    """
    from rag.gemini import GeminiError, generate
    from rag.llm import with_fallback

    def public(call):
        """키·설정 안내('HASA_API_KEY를 확인하세요')나 공급자 응답 본문을 앱 사용자에게 보내지 않는다."""
        if call is None:
            return None

        def wrapped(prompt, **options):
            try:
                return call(prompt, **options)
            except GeminiError as error:
                if error.status == 429 or error.kind in ('quota', 'daily_quota', 'minute_quota', 'busy'):
                    message = 'AI 사용량이 많아 지금은 답하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
                elif error.kind == 'timeout' or (error.status or 0) >= 500:
                    message = 'AI 응답이 늦어 답하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
                else:
                    message = 'AI 서버 설정 문제로 답하지 못했습니다. 관리자에게 알려 주세요.'
                raise GeminiError(message, status=error.status, retry_after=error.retry_after, kind=error.kind) from error
        return wrapped
    call_gemini = (lambda prompt, **options: generate(prompt, model=settings.gemini_model, key=settings.gemini_api_key,
                                                      retries=0, **options)) if settings.gemini_api_key else None
    if settings.llm_provider == "hasa":
        from rag.llm import FALLBACK_SLOT_WAIT, NO_FALLBACK_SLOT_WAIT
        from rag.openai_compat import generate as call_hasa
        fallback = call_gemini if settings.llm_fallback == "gemini" else None
        # 대체 모델이 없으면 키가 모두 바쁠 때 차례를 길게 기다린다 (앱은 180초까지 기다린다).
        wait = FALLBACK_SLOT_WAIT if fallback else NO_FALLBACK_SLOT_WAIT
        hasa = lambda prompt, **options: call_hasa(prompt, model=settings.hasa_model, key=settings.hasa_api_key,
                                                   retries=1, slot_wait=wait, **options)
        return public(with_fallback(hasa, fallback))
    return public(lambda prompt, **options: generate(prompt, model=settings.gemini_model,
                                                     key=settings.gemini_api_key, retries=0, **options))


def create_app(settings=None, gateway=None, clock=time.time, generate=None):
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    riot = RiotData(db, gateway or RiotGateway(settings), clock=clock)
    ai_enabled = bool(generate or (settings.hasa_api_key if settings.llm_provider == "hasa" else settings.gemini_api_key))
    ai = AiService(db, settings.knowledge_db_path, generate or gemini_generator(settings))
    registrations = defaultdict(deque)
    registrations_lock = threading.Lock()
    # 동시에 처리할 AI 요청 수. 넘으면 기다리지 않고 바로 '잠시 뒤 다시'로 돌려준다.
    # 예전에는 느린 AI 요청이 서버 스레드(40개)를 다 붙잡아 상태 확인·전적 조회까지 멈출 수 있었다.
    ai_slots = threading.BoundedSemaphore(max(1, settings.ai_concurrency))
    cleaned = {"day": None}

    app = FastAPI(title="RiftFlow API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    def api_error(_request, error):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status, headers=headers)

    def daily_cleanup():
        """하루 한 번 오래된 캐시·사용량을 지운다 (별도 스레드 없이 그날 첫 요청에서)."""
        day = kst_day()
        if cleaned["day"] == day:
            return
        cleaned["day"] = day
        cutoff = datetime.fromtimestamp(clock() - 14 * 86400, KST).strftime("%Y-%m-%d")
        try:
            db.cleanup(clock(), cutoff)
        except Exception:                       # noqa: BLE001 - 정리 실패로 요청을 막지 않는다
            cleaned["day"] = None

    def device(authorization: str = Header(default=""), app_version: str = Header(default="", alias="X-RiftFlow-Version")):
        daily_cleanup()
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        device_id = db.find_device(token_hash(token)) if token else None
        if device_id is None:
            raise ApiError(401, "invalid_device", "기기 인증이 필요합니다. 앱을 다시 실행해 주세요.")
        db.touch_device(device_id, clock(), app_version[:32])
        return device_id

    def riot_device(device_id=Depends(device)):
        """라이엇 데이터 요청만 전적 조회 한도에 센다 (AI 요청은 따로 센다)."""
        now = clock()
        day = datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d")
        if db.count_request(device_id, day) > settings.device_daily_requests:
            raise ApiError(429, "daily_limit", "오늘 전적 조회 한도를 모두 썼습니다. 내일 다시 이용해 주세요.",
                           retry_after=seconds_until_kst_midnight(now))
        return device_id

    def kst_day():
        return datetime.fromtimestamp(clock(), KST).strftime("%Y-%m-%d")

    def ai_device(request: Request, device_id=Depends(device)):
        """AI 한도를 기기·IP·서버 전체 세 범위로 한 번에 예약한다. 넘으면 아무것도 쓰지 않고 거절한다."""
        if not ai_enabled:
            raise ApiError(503, "ai_unavailable", "지금은 AI 기능을 쓸 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
        scopes = [("device:%d" % device_id, settings.device_daily_ai), ("ip:" + client_ip(request), settings.ip_daily_ai),
                  ("global", settings.global_daily_ai)]
        day = kst_day()
        full = db.reserve_ai(scopes, day)
        if full is not None:
            message = ("오늘 서버 전체 AI 사용량이 한도에 도달했습니다. 내일 다시 이용해 주세요." if full == "global"
                       else "오늘 AI 사용 한도를 모두 썼습니다. 내일 다시 이용해 주세요.")
            raise ApiError(429, "daily_ai_limit", message, retry_after=seconds_until_kst_midnight(clock()))
        return {"device": device_id, "scopes": [scope for scope, _ in scopes], "day": day}

    def ai_call(function, body, reservation):
        if not ai_slots.acquire(blocking=False):
            db.adjust_ai(reservation["scopes"], reservation["day"], -1)
            raise ApiError(503, "ai_busy", "AI 요청이 몰려 있습니다. 잠시 뒤 다시 시도해 주세요.", retry_after=5)
        try:
            result, used = ai.counted(function, body.model_dump())
        except Exception:
            db.adjust_ai(reservation["scopes"], reservation["day"], -1)
            raise
        finally:
            ai_slots.release()
        db.adjust_ai(reservation["scopes"], reservation["day"], used - 1)
        return result

    @app.post("/v1/runes/recommend")
    def runes(body: RuneBody, reservation=Depends(ai_device)):
        return ai_call(ai.runes, body, reservation)

    @app.post("/v1/coach/pick")
    def coach_pick(body: PickBody, reservation=Depends(ai_device)):
        return ai_call(ai.pick, body, reservation)

    @app.post("/v1/coach/in-game")
    def coach_in_game(body: InGameBody, reservation=Depends(ai_device)):
        return ai_call(ai.in_game, body, reservation)

    @app.post("/v1/coach/general")
    def coach_general(body: GeneralBody, reservation=Depends(ai_device)):
        return ai_call(ai.general, body, reservation)

    def riot_call(function, *args):
        try:
            return function(*args)
        except NotFound as missing:
            code = str(missing)
            raise ApiError(404, code, NOT_FOUND_MESSAGES.get(code, "찾을 수 없습니다."))
        except RiotBusy as busy:
            raise ApiError(503, "riot_busy", "요청이 몰려 잠시 기다려야 합니다. 조금 뒤 다시 시도해 주세요.",
                           retry_after=busy.retry_after)
        except (RiotApiError, requests.exceptions.RequestException):
            # 키 만료(401/403)·라이엇 장애(5xx)·연결 실패. 예전에는 그대로 500 Internal Server Error였다.
            raise ApiError(502, "riot_unavailable", "라이엇 서버에서 정보를 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
                           retry_after=30)

    @app.get("/v1/health")
    async def health():
        # async라 스레드 풀이 바빠도 바로 답한다.
        return {"status": "ok"}

    @app.post("/v1/devices")
    def register(request: Request, app_version: str = Header(default="", alias="X-RiftFlow-Version")):
        ip, now = client_ip(request), clock()
        with registrations_lock:
            for old_ip in [key for key, times in registrations.items() if not times or times[-1] < now - 3600]:
                del registrations[old_ip]           # 한 번 등록한 IP가 메모리에 영원히 남지 않게
            recent = registrations[ip]
            while recent and recent[0] < now - 3600:
                recent.popleft()
            if len(recent) >= settings.device_creations_per_hour:
                raise ApiError(429, "too_many_devices", "기기 등록 요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요.",
                               retry_after=int(recent[0] + 3600 - now) + 1)
            recent.append(now)
        token = secrets.token_urlsafe(32)
        db.add_device(token_hash(token), now, app_version[:32])
        return {"token": token}

    @app.get("/v1/riot/account/{game_name}/{tag_line}")
    def account(game_name: str, tag_line: str, _device=Depends(riot_device)):
        if not (1 <= len(game_name) <= 32 and 1 <= len(tag_line) <= 8):
            raise ApiError(400, "invalid_riot_id", "Riot ID 형식이 올바르지 않습니다.")
        return riot_call(riot.account, game_name, tag_line)

    @app.get("/v1/riot/rank/{puuid}")
    def rank(puuid: str, _device=Depends(riot_device)):
        if not PUUID.match(puuid):
            raise ApiError(400, "invalid_puuid", "잘못된 요청입니다.")
        return riot_call(riot.rank, puuid)

    @app.get("/v1/riot/matches/detail/{match_id}")
    def match_detail(match_id: str, _device=Depends(riot_device)):
        if not MATCH_ID.match(match_id):
            raise ApiError(400, "invalid_match_id", "잘못된 요청입니다.")
        return riot_call(riot.match_detail, match_id)

    @app.get("/v1/riot/matches/{puuid}")
    def matches(puuid: str, count: int = Query(default=20, ge=1, le=20), _device=Depends(riot_device)):
        if not PUUID.match(puuid):
            raise ApiError(400, "invalid_puuid", "잘못된 요청입니다.")
        return riot_call(riot.matches, puuid, count)

    return app
