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

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


class InGameBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    view: dict = Field(default_factory=dict)


class GeneralBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    context: Optional[dict] = None


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
    from rag.gemini import generate
    return lambda prompt, **options: generate(prompt, model=settings.gemini_model, key=settings.gemini_api_key,
                                              retries=0, **options)


def create_app(settings=None, gateway=None, clock=time.time, generate=None):
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    riot = RiotData(db, gateway or RiotGateway(settings), clock=clock)
    ai_enabled = bool(generate or settings.gemini_api_key)
    ai = AiService(db, settings.knowledge_db_path, generate or gemini_generator(settings))
    registrations = defaultdict(deque)
    registrations_lock = threading.Lock()

    app = FastAPI(title="RiftFlow API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    def api_error(_request, error):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status, headers=headers)

    def device(authorization: str = Header(default=""), app_version: str = Header(default="", alias="X-RiftFlow-Version")):
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

    def ai_device(device_id=Depends(device)):
        if not ai_enabled:
            raise ApiError(503, "ai_unavailable", "지금은 AI 기능을 쓸 수 없습니다. 서버 관리자에게 알려 주세요.")
        if db.ai_requests(device_id, kst_day()) >= settings.device_daily_ai:
            raise ApiError(429, "daily_ai_limit", "오늘 AI 사용 한도를 모두 썼습니다. 내일 다시 이용해 주세요.",
                           retry_after=seconds_until_kst_midnight(clock()))
        return device_id

    def ai_call(function, body, device_id):
        result, used = function(body.model_dump())
        db.count_ai(device_id, kst_day(), used)
        return result

    @app.post("/v1/runes/recommend")
    def runes(body: RuneBody, device_id=Depends(ai_device)):
        return ai_call(ai.runes, body, device_id)

    @app.post("/v1/coach/pick")
    def coach_pick(body: PickBody, device_id=Depends(ai_device)):
        return ai_call(ai.pick, body, device_id)

    @app.post("/v1/coach/in-game")
    def coach_in_game(body: InGameBody, device_id=Depends(ai_device)):
        return ai_call(ai.in_game, body, device_id)

    @app.post("/v1/coach/general")
    def coach_general(body: GeneralBody, device_id=Depends(ai_device)):
        return ai_call(ai.general, body, device_id)

    def riot_call(function, *args):
        try:
            return function(*args)
        except NotFound as missing:
            code = str(missing)
            raise ApiError(404, code, NOT_FOUND_MESSAGES.get(code, "찾을 수 없습니다."))
        except RiotBusy as busy:
            raise ApiError(503, "riot_busy", "요청이 몰려 잠시 기다려야 합니다. 조금 뒤 다시 시도해 주세요.",
                           retry_after=busy.retry_after)

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/devices")
    def register(request: Request, app_version: str = Header(default="", alias="X-RiftFlow-Version")):
        ip, now = client_ip(request), clock()
        with registrations_lock:
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
