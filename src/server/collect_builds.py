"""상위 랭커 빌드 통계 수집 (서버에서 riftflow-builds.timer가 하루 한 번 실행).

    python -m server.collect_builds

API 서버와 같은 라이엇 키를 쓰므로 한도를 낮게 잡는다 (기본 1초 5회, 2분 40회 = 키 한도 100회의 40%).
사용자가 적은 새벽에 돌고, 라이엇이 한도 초과(429)를 주면 RiotGateway가 기다렸다 다시 보낸다.
"""
import os
import sys
from contextlib import closing

from knowledge.build_stats import collect, connect

from .config import Settings, parse_limits
from .riot_data import RateLimiter, RiotBusy, RiotGateway


def main():
    settings = Settings.from_env()
    limits = parse_limits(os.environ.get('RIFTFLOW_BUILD_LIMITS') or '5/1,40/120')
    gateway = RiotGateway(settings, limiters={'region': RateLimiter(limits), 'platform': RateLimiter(limits)})
    players = int(os.environ.get('RIFTFLOW_BUILD_PLAYERS') or 300)
    matches = int(os.environ.get('RIFTFLOW_BUILD_MATCHES') or 900)
    with closing(connect(settings.knowledge_db_path)) as db:
        try:
            collect(db, gateway, players=players, matches=matches, log=lambda m: print(m, flush=True))
        except RiotBusy as busy:
            print('라이엇 한도로 중단: %s초 뒤 가능. 받은 데까지는 저장됨' % busy.retry_after, flush=True)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
