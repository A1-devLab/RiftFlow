import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from contracts.riot import ConnectionState, LiveMatchStatus, LiveState, PlayerLiveStats, TeamGoldTotals
from game_phases.in_game.desktop import answer_in_game, describe_scoreboard, is_item_question
from knowledge.collector import connect, save
from knowledge.in_game import champion_profiles, item_catalog, team_composition
from ui.__main__ import HOME, INGAME, PICK, Window, collect_phase


# Data Dragon처럼 능력치에 맞는 아이템 태그 (아이템 후보는 챔피언 분류와 태그로 고른다)
STAT_TAGS = {'FlatMagicDamageMod': 'SpellDamage', 'FlatArmorMod': 'Armor', 'FlatSpellBlockMod': 'SpellBlock',
             'FlatHPPoolMod': 'Health'}


def player(name, champion, team, position, items=(), kills=0, dead=False):
    return PlayerLiveStats(name, champion, team, position, 9, kills, 1, 2, 120, dead, 12.0 if dead else 0.0,
                           [{'itemID': item_id, 'slot': slot} for slot, item_id in enumerate(items)], 1000.0)


def context(active='Me#KR1'):
    board = [player('Enemy', 'Lux', 'ORDER', 'MIDDLE', kills=3),
             player('Buddy', 'Garen', 'CHAOS', 'TOP'),
             player('Me', 'Ahri', 'CHAOS', 'MIDDLE', items=[1056], dead=True)]
    return {'state': LiveState(LiveMatchStatus.IN_GAME, ConnectionState.CONNECTED, 610),
            'scoreboard': board, 'team_gold': TeamGoldTotals(order=5000, chaos=6500),
            'active_player_name': active}


class InGameDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # .env의 실제 Gemini 키로 자동 룬 추천이 호출되지 않게 한다. 키가 필요한 테스트는 직접 넣는다.
        env = patch.dict(os.environ, {'GEMINI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        with closing(connect(self.db)) as db, db:
            for key, id_, name, tags, info in ((103, 'Ahri', '아리', ['Mage'], {'attack': 3, 'magic': 8}),
                                               (99, 'Lux', '럭스', ['Mage'], {'attack': 2, 'magic': 9}),
                                               (86, 'Garen', '가렌', ['Fighter', 'Tank'], {'attack': 7, 'magic': 1})):
                save(db, 'champion', '16.19.1', id_, name, json.dumps(
                    {'key': str(key), 'id': id_, 'name': name, 'blurb': name + ' 챔피언', 'tags': tags, 'info': info},
                    ensure_ascii=False), 'https://example.com/champion')
            for item_id, name, text, gold, stats, extra in (
                    ('1056', '도란의 반지', '주문력 +18 체력', 400, {'FlatMagicDamageMod': 18}, {}),
                    ('3157', '존야의 모래시계', '주문력 방어력 경직', 3250, {'FlatMagicDamageMod': 105, 'FlatArmorMod': 50}, {}),
                    ('3089', '라바돈의 죽음모자', '주문력 대폭 증가', 3500, {'FlatMagicDamageMod': 130}, {}),
                    ('3102', '밴시의 장막', '주문력 마법 저항력 주문 보호막', 3000, {'FlatMagicDamageMod': 105, 'FlatSpellBlockMod': 40}, {}),
                    ('223089', '라바돈의 죽음모자', '아레나 복사본', 2500, {'FlatMagicDamageMod': 130}, {}),
                    ('4636', '밤의 수확자', '상점에 없음', 2765, {'FlatMagicDamageMod': 80}, {'inStore': False})):
                save(db, 'item', '16.19.1', item_id, name, json.dumps(
                    dict({'name': name, 'description': text, 'gold': {'total': gold, 'purchasable': True},
                          'maps': {'11': True}, 'stats': stats, 'into': [], 'tags': [STAT_TAGS[k] for k in stats if k in STAT_TAGS]}, **extra),
                    ensure_ascii=False), 'https://example.com/item')

    def test_scoreboard_uses_my_team_and_official_item_names(self):
        view = describe_scoreboard(context(), item_catalog(self.db))
        self.assertTrue(view['perspective_known'])
        self.assertEqual(view['clock'], '10:10')
        self.assertEqual(view['me']['champion'], 'Ahri')
        self.assertEqual([e['champion'] for e in view['allies']], ['Garen', 'Ahri'])
        self.assertEqual([e['champion'] for e in view['enemies']], ['Lux'])
        self.assertEqual(view['team_gold']['diff'], 1500)
        self.assertEqual(view['me']['items'][0]['name'], '도란의 반지')
        self.assertTrue(view['me']['is_dead'])
        self.assertEqual(view['me']['cs_per_min'], 11.8)

    def test_unknown_perspective_is_explicit(self):
        view = describe_scoreboard(context(active=None), {})
        self.assertFalse(view['perspective_known'])
        self.assertIsNone(view['me'])
        self.assertEqual([e['champion'] for e in view['allies']], ['Lux'])
        self.assertEqual(view['team_gold']['diff'], -1500)
        self.assertEqual(describe_scoreboard({'scoreboard': None}, {}), {'in_game': False})

    def test_composition_uses_only_official_tags(self):
        composition = team_composition(['럭스', 'Garen', '없는챔프'], champion_profiles(self.db))
        self.assertEqual(composition['damage_rating_counts'], {'AP': 1, 'AD': 1})
        self.assertEqual(composition['unverified_champions'], ['없는챔프'])

    def test_store_filter_drops_mode_copies_and_unbuyable_items(self):
        from knowledge.documents import get_documents
        ids = sorted(d['entity_id'] for d in get_documents(kind='item', db_path=self.db))
        self.assertEqual(ids, ['1056', '3089', '3102', '3157'])      # 223089(아레나), 4636(상점 없음) 제외

    def test_item_options_are_chosen_only_from_code_candidates(self):
        view = describe_scoreboard(context(), item_catalog(self.db))
        reply = {'options': [{'item_id': 3089, 'reason': '주문력을 크게 올립니다.'},
                             {'item_id': 3157, 'reason': '상대 돌진을 버팁니다.'},
                             {'item_id': 3102, 'reason': '마법 피해를 버팁니다.'}], 'summary': '상황에 맞게 고르세요.'}
        generator = Mock(side_effect=[{'text': json.dumps({'options': [{'item_id': 4636, 'reason': 'x'}], 'summary': ''})},
                                      {'text': json.dumps(reply, ensure_ascii=False)}])
        result = answer_in_game(self.db, view, '지금 뭐 사야 해?', generate=generator)
        self.assertTrue(result['generated'])
        self.assertEqual([o['name'] for o in result['options']][:2], ['라바돈의 죽음모자', '존야의 모래시계'])
        self.assertEqual(len(result['options']), 3)                      # 추천 칸은 항상 3개
        self.assertTrue(result['answer'].startswith('추천: 라바돈의 죽음모자(3,500)'))
        self.assertNotIn('골드', result['answer'])                       # 보유 골드를 글로 안내하지 않음
        self.assertIsNone(result['options'][0]['affordable'])
        first = json.loads(generator.call_args_list[0].args[0]['user'])
        pool = {c['name'] for c in first['candidates']}
        self.assertNotIn('도란의 반지', pool)                  # 이미 가진 아이템·하위 아이템 제외
        self.assertNotIn('밤의 수확자', pool)                  # 상점에 없는 아이템 제외
        self.assertEqual(generator.call_args.kwargs['config']['responseMimeType'], 'application/json')
        second = json.loads(generator.call_args.args[0]['user'])
        self.assertTrue(any('4636' in e for e in second['previous_errors']))

    def test_current_gold_is_exact_for_me_and_decides_buy_status(self):
        from game_phases.in_game.items import remaining_cost, store_items
        gold_context = dict(context(), current_gold=1200)
        view = describe_scoreboard(gold_context, item_catalog(self.db))
        self.assertEqual(view['me']['current_gold'], 1200)
        self.assertIsNone(view['enemies'][0]['current_gold'])            # 다른 사람 보유 골드는 알 수 없음
        from game_phases.in_game.desktop import prompt_player
        me = prompt_player(view['me'])
        self.assertEqual((me['current_gold'], me['item_value_estimate']), (1200, 1000))
        self.assertNotIn('estimated_gold', me)                           # '가진 돈'으로 오해되던 이름은 보내지 않음
        items = store_items(self.db)
        rabadon = dict(items[3089], **{'from': ['1056']})                 # 도란의 반지(400)를 재료로 가정
        self.assertEqual(remaining_cost(rabadon, items, view['me']), 3100)
        reply = {'options': [{'item_id': 3089, 'reason': '주문력'}, {'item_id': 3102, 'reason': '마저'},
                             {'item_id': 3157, 'reason': '생존'}, {'item_id': 3089, 'reason': '넷째는 버림'}], 'summary': ''}
        generator = Mock(return_value={'text': json.dumps(reply, ensure_ascii=False)})
        result = answer_in_game(self.db, view, '뭐 사야 해?', generate=generator)
        self.assertEqual(len(result['options']), 3)                      # 3개보다 많이 고르면 앞의 3개만
        self.assertFalse(result['options'][0]['affordable'])             # 3,500 > 1,200: 화면이 가격 색으로만 표시
        self.assertNotIn('부족', result['answer'])
        sent = json.loads(generator.call_args.args[0]['user'])
        self.assertEqual(sent['me']['current_gold'], 1200)
        self.assertNotIn('remaining_cost', sent['candidates'][0])

    def test_free_answers_get_current_patch_names(self):
        view = describe_scoreboard(context(), item_catalog(self.db))
        generator = Mock(return_value={'text': '괜찮습니다'})
        answer_in_game(self.db, view, '지금 불리해?', generate=generator)
        names = json.loads(generator.call_args.args[0]['user'])['current_patch_names']
        self.assertIn('라바돈의 죽음모자', names['items'])
        self.assertNotIn('밤의 수확자', names['items'])
        self.assertIn('current_patch_names', generator.call_args.args[0]['system'])

    def test_item_question_without_item_documents_does_not_call_model(self):
        view = describe_scoreboard(context(), {})
        generator = Mock()
        result = answer_in_game(Path(self.temp.name) / 'missing.db', view, '아이템 추천해줘', generate=generator)
        generator.assert_not_called()
        self.assertFalse(result['generated'])
        self.assertTrue(is_item_question('다음 템 뭐 가?'))

    def test_not_in_game_does_not_call_model(self):
        generator = Mock()
        result = answer_in_game(self.db, {'in_game': False}, '불리해?', generate=generator)
        generator.assert_not_called()
        self.assertIn('게임 중이 아닙니다', result['message'])

    @patch('ui.__main__.get_before_game_context', return_value=None)
    @patch('ui.__main__.get_gameflow_phase', return_value='InProgress')
    @patch('ui.__main__.get_live_state',
           return_value=LiveState(LiveMatchStatus.NOT_IN_GAME, ConnectionState.DISCONNECTED))
    def test_loading_screen_is_its_own_phase(self, _state, flow, _session):
        self.assertEqual(collect_phase(self.db), {'phase': 'loading'})
        flow.return_value = 'EndOfGame'
        self.assertEqual(collect_phase(self.db), {'phase': 'idle'})

    def test_window_follows_client_through_pick_loading_game_and_back(self):
        from contracts.riot import ChampSelectMember, ChampSelectSession
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
            window.champ_timer.stop()
            session = ChampSelectSession([ChampSelectMember(1, 103, 'middle', 'mine')], [], [], [], 1)
            champ_select = {'phase': 'champ_select', 'session': session, 'catalog': {}}
            window.navigate(3)
            window.on_phase(champ_select)
            self.assertEqual(window.stack.currentIndex(), PICK)
            window.on_phase({'phase': 'loading'})
            self.assertEqual(window.stack.currentIndex(), INGAME)
            view = describe_scoreboard(context(), item_catalog(self.db))
            window.on_phase({'phase': 'in_game', 'view': view})
            self.assertEqual(window.stack.currentIndex(), INGAME)
            self.assertEqual(window.in_game.clock.text(), '10:10')
            self.assertEqual(window.in_game.ally.rows[1].champion.text(), 'Ahri  (나)')
            self.assertEqual(window.in_game.ally.rows[1].player.text(), '부활까지 12초')
            window.navigate(3)
            window.on_phase({'phase': 'in_game', 'view': view})
            self.assertEqual(window.stack.currentIndex(), 3)   # 같은 단계 동안에는 사용자가 옮긴 화면을 유지
            window.navigate(INGAME)
            window.on_phase({'phase': 'idle'})
            self.assertEqual(window.stack.currentIndex(), HOME)
            self.assertEqual(window.in_game.clock.text(), '--:--')
            window.on_phase(champ_select)
            window.on_phase({'phase': 'idle'})   # 닷지
            self.assertEqual(window.stack.currentIndex(), HOME)
            if window.poll_job is not None:
                window.poll_job.wait(4000)
            window.close()


if __name__ == '__main__':
    unittest.main()
