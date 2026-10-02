"""AI features for the server. Prompts, official-data retrieval and rune validation stay on the server.

앱이 보낸 임의의 프롬프트를 Gemini로 넘기는 경로는 만들지 않는다. 기능별로 정해진 요청만 받는다.
"""
import json
import threading

from game_phases import payloads
from game_phases.before_game.desktop import answer_before_game
from game_phases.before_game.runes import recommend_runes
from game_phases.in_game.desktop import answer_in_game
from knowledge.before_game import canonical_champion
from knowledge.runes import ensure_rune_trees
from ui.services import ask_general

GENERAL_KEYS = ('status', 'message', 'answer', 'generated', 'error')


class AiService:
    """기능별 AI 요청. 메서드는 (결과, 실제 모델 호출 수)를 돌려준다.

    호출 수는 generate를 감싸 직접 센다. 예전에는 '자료 없음'처럼 모델을 부르지 않은 경우도 1회로 셌다.
    """

    def __init__(self, db, knowledge_path, generate):
        self.db, self.knowledge_path = db, knowledge_path
        self._generate = generate
        self._calls = threading.local()

    def generate(self, prompt, **options):
        self._calls.count = getattr(self._calls, 'count', 0) + 1
        return self._generate(prompt, **options)

    def counted(self, function, body):
        self._calls.count = 0
        result, _ = function(body)
        return result, self._calls.count

    def runes(self, body):
        """(결과, Gemini 호출 수). 채팅 요청이 없는 자동 추천은 사용자끼리 공유하는 캐시를 쓴다.

        공유하려면 개인 정보가 섞이면 안 되므로, 자동 추천에서는 개인 룬 기록을 빼고 추천한다.
        """
        view = payloads.pick_view(body.get('view'))
        champion, opponent = payloads.text(body.get('champion')), payloads.text(body.get('opponent'))
        requests = payloads.user_requests(body.get('user_requests'))
        pages = payloads.recent_pages(body.get('recent_pages'))
        cache_key = None
        if not requests:
            trees = ensure_rune_trees(self.knowledge_path)
            version = next(iter(trees.values()))['version'] if trees else 'none'
            from knowledge.build_stats import item_popularity
            stats = item_popularity(self.knowledge_path, canonical_champion(self.knowledge_path, champion))
            # 통계가 쌓이면(표본 50판 단위) 공유 캐시를 새로 만든다. 예전 추천이 통계 없이 만든 것으로 남지 않게.
            version = '%s|stats:%s:%d' % (version, ','.join(stats['patch']), stats['games'] // 50)
            cache_key = json.dumps([version, canonical_champion(self.knowledge_path, champion),
                                    canonical_champion(self.knowledge_path, opponent) if opponent else None,
                                    (view.get('mine') or {}).get('position'), view.get('game_mode')],
                                   ensure_ascii=False)
            cached = self.db.rune_cache(cache_key)
            if cached is not None:
                return dict(cached, cached=True), 0
            pages = []
        result = recommend_runes(self.knowledge_path, None, None, view, generate=self.generate,
                                 champion=champion, opponent=opponent, user_requests=requests,
                                 download=True, recent_pages=pages)
        if cache_key and result.get('page'):
            self.db.save_rune_cache(cache_key, result)
        return dict(result, cached=False), result.get('attempts') or 0

    def pick(self, body):
        champion = payloads.text(body.get('champion'))
        if champion in ('', '선택 전'):
            # 챔피언을 고르기 전에 물은 질문('티모 서폿이랑 어울리는 거?')은 일반 질문으로 답한다.
            result = ask_general(self.knowledge_path, payloads.text(body.get('question'), 1000), generate=self.generate,
                                 history=payloads.history(body.get('history')))
            return {'answer': result.get('answer'), 'message': result.get('message'),
                    'generated': bool(result.get('generated'))}, 1
        view = payloads.pick_view(body.get('view'))
        result = answer_before_game(self.knowledge_path, None, None, view, payloads.text(body.get('question'), 1000),
                                    generate=self.generate, champion=payloads.text(body.get('champion')),
                                    opponent=payloads.text(body.get('opponent')),
                                    user_requests=payloads.user_requests(body.get('user_requests')),
                                    observations=payloads.observations(body.get('observations')),
                                    history=payloads.history(body.get('history')))
        return result, 1

    def in_game(self, body):
        result = answer_in_game(self.knowledge_path, payloads.live_view(body.get('view')),
                                payloads.text(body.get('question'), 1000), generate=self.generate,
                                history=payloads.history(body.get('history')))
        return result, 1

    def general(self, body):
        result = ask_general(self.knowledge_path, payloads.text(body.get('question'), 1000), generate=self.generate,
                             context=payloads.general_context(body.get('context')),
                             history=payloads.history(body.get('history')))
        return {key: result.get(key) for key in GENERAL_KEYS}, 1
