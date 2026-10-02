"""Game-mode aware item stores: Summoner's Rift, ARAM and Arena use different store items."""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from game_phases.in_game.desktop import describe_scoreboard, prompt_player
from game_phases.in_game.items import recommend_items, store_items
from knowledge.collector import connect, save
from knowledge.documents import item_map_for
from knowledge.in_game import current_names

# Data Dragon처럼 능력치에 맞는 아이템 태그 (아이템 후보는 챔피언 분류와 태그로 고른다)
STAT_TAGS = {'FlatMagicDamageMod': 'SpellDamage', 'FlatArmorMod': 'Armor', 'FlatSpellBlockMod': 'SpellBlock',
             'FlatHPPoolMod': 'Health'}


ITEMS = [  # id, name, price, maps, stats
    ('3089', '라바돈의 죽음모자', 3500, {'11': True, '12': True, '30': False}, {'FlatMagicDamageMod': 130}),
    ('773089', '라바돈의 죽음모자', 3300, {'11': False, '12': True, '30': False}, {'FlatMagicDamageMod': 130}),
    ('223089', '라바돈의 죽음모자', 2500, {'11': False, '12': False, '30': True}, {'FlatMagicDamageMod': 130}),
    ('3157', '존야의 모래시계', 3250, {'11': True, '12': True, '30': False}, {'FlatMagicDamageMod': 105, 'FlatArmorMod': 50}),
    ('223157', '존야의 모래시계', 2500, {'11': False, '12': False, '30': True}, {'FlatMagicDamageMod': 105, 'FlatArmorMod': 50}),
    ('3102', '밴시의 장막', 3000, {'11': True, '12': True, '30': False}, {'FlatMagicDamageMod': 105, 'FlatSpellBlockMod': 40}),
    ('663056', '불사대마왕의 왕관', 2500, {'11': True, '12': False, '30': False}, {'FlatArmorMod': 40}),
]


class ModeItemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'game.db'
        with closing(connect(self.db)) as db, db:
            for item_id, name, price, maps, stats in ITEMS:
                save(db, 'item', '16.19.1', item_id, name, json.dumps(
                    {'name': name, 'description': name + ' 효과', 'gold': {'total': price, 'purchasable': True},
                     'maps': maps, 'stats': stats, 'into': [],
                     'tags': [STAT_TAGS[k] for k in stats if k in STAT_TAGS]}, ensure_ascii=False), 'https://x')
            for key, id_, name in ((103, 'Ahri', '아리'), (99, 'Lux', '럭스')):
                save(db, 'champion', '16.19.1', id_, name, json.dumps(
                    {'key': str(key), 'id': id_, 'name': name, 'blurb': name, 'tags': ['Mage'],
                     'info': {'attack': 2, 'magic': 9}}, ensure_ascii=False), 'https://x')

    def test_mode_to_map(self):
        self.assertEqual(item_map_for('ARAM'), '12')
        self.assertEqual(item_map_for('CHERRY'), '30')
        self.assertEqual(item_map_for('URF'), '11')
        self.assertEqual(item_map_for('NEW_MODE'), '11')
        self.assertEqual(item_map_for('CLASSIC', 12), '12')          # 게임 중 클라이언트가 알려 준 맵이 우선

    def test_each_mode_gets_its_own_store_copy(self):
        prices = lambda item_map: {i['name']: (i['id'], i['gold']) for i in store_items(self.db, item_map).values()}
        rift = prices('11')
        self.assertEqual(rift['라바돈의 죽음모자'], (3089, 3500))
        self.assertNotIn('불사대마왕의 왕관', rift)                  # 협곡 표시가 붙은 모드 복사본은 제외
        aram = prices('12')
        self.assertEqual(aram['라바돈의 죽음모자'], (773089, 3300))   # 칼바람 전용 가격판 우선
        self.assertEqual(aram['존야의 모래시계'], (3157, 3250))
        arena = prices('30')
        self.assertEqual(set(arena), {'라바돈의 죽음모자', '존야의 모래시계'})
        self.assertEqual(arena['존야의 모래시계'], (223157, 2500))
        self.assertNotIn('밴시의 장막', current_names(self.db, '30')['items'])

    def test_live_game_mode_drives_item_options(self):
        from contracts.riot import ConnectionState, LiveMatchStatus, LiveState, PlayerLiveStats, TeamGoldTotals
        board = [PlayerLiveStats('Me', '아리', 'ORDER', 'NONE', 9, 1, 1, 1, 50, False, 0.0, [], 0.0),
                 PlayerLiveStats('E', '럭스', 'CHAOS', 'NONE', 9, 1, 1, 1, 50, False, 0.0, [], 0.0)]
        view = describe_scoreboard({'state': LiveState(LiveMatchStatus.IN_GAME, ConnectionState.CONNECTED, 600),
                                    'scoreboard': board, 'team_gold': TeamGoldTotals(1, 1),
                                    'active_player_name': 'Me', 'game': {'game_mode': 'ARAM', 'map_number': 12}}, {})
        self.assertEqual(view['mode_name'], '칼바람 나락')
        reply = {'options': [{'item_id': 773089, 'reason': '주문력'}, {'item_id': 3157, 'reason': '생존'},
                             {'item_id': 3102, 'reason': '마저'}], 'summary': '고르세요'}
        generate = Mock(return_value={'text': json.dumps(reply, ensure_ascii=False)})
        result = recommend_items(self.db, view, '뭐 사야 해?', generate=generate, prompt_player=prompt_player)
        self.assertTrue(result['generated'])
        self.assertIn('라바돈의 죽음모자(3,300)', result['answer'])
        self.assertEqual(result['mode_name'], '칼바람 나락')
        payload = json.loads(generate.call_args.args[0]['user'])
        self.assertEqual(payload['game_mode'], '칼바람 나락')

    def test_live_client_reports_mode_and_map(self):
        from riot import live_client
        with patch.object(live_client, '_get', return_value={'gameMode': 'CHERRY', 'mapNumber': 30, 'gameTime': 12.0}):
            self.assertEqual(live_client.get_game_info(), {'game_mode': 'CHERRY', 'map_number': 30})
        with patch.object(live_client, '_get', return_value=None):
            self.assertIsNone(live_client.get_game_info())


if __name__ == '__main__':
    unittest.main()
