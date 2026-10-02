"""High-elo build statistics as grounding for item candidates, class rules, and upgrades of owned components."""
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from knowledge.build_stats import (MIN_GAMES, collect, connect, item_popularity, patch_of, prune, samples_from_match,
                                   save_match)


def match(match_id, version='16.19.734.1', queue=420, duration=1800, players=None):
    players = players or [{'championName': 'Leblanc', 'teamPosition': 'MIDDLE', 'win': True,
                           'item0': 6655, 'item1': 3089, 'item2': 3020, 'item3': 0, 'item4': 0, 'item5': 0, 'item6': 3340,
                           'perks': {'styles': [{'style': 8100, 'selections': [{'perk': 8112}]}, {'style': 8200}]},
                           'puuid': 'secret', 'riotIdGameName': 'Faker'}]
    return {'metadata': {'matchId': match_id},
            'info': {'queueId': queue, 'gameDuration': duration, 'gameVersion': version, 'participants': players}}


def item(item_id, name, gold, tags, into=(), frm=()):
    return {'id': item_id, 'name': name, 'gold': gold, 'stats': {}, 'tags': list(tags), 'from': [str(f) for f in frm],
            'into': [str(i) for i in into], 'version': '16.19.1', 'effect': name + ' 효과'}


ITEMS = {i['id']: i for i in [
    item(3802, '사라진 양피지', 1200, ['SpellDamage', 'Mana'], into=[6655, 323003]),
    item(6655, '루덴의 메아리', 2750, ['SpellDamage', 'Mana'], frm=[3802]),
    item(3089, '라바돈의 죽음모자', 3500, ['SpellDamage']),
    item(3157, '존야의 모래시계', 3250, ['SpellDamage', 'Armor', 'Active']),
    item(3124, '구인수의 격노검', 3000, ['Damage', 'SpellDamage', 'AttackSpeed', 'OnHit']),
    item(3742, '망자의 갑옷', 2900, ['Health', 'Armor']),
    item(3031, '무한의 대검', 3450, ['Damage', 'CriticalStrike']),
    item(1001, '장화', 300, ['Boots'], into=[3020, 3047]),
    item(3020, '마법사의 신발', 1100, ['Boots'], frm=[1001]),
    item(3047, '판금 장화', 1200, ['Boots', 'Armor'], frm=[1001]),
    item(3006, '광전사의 군화', 1100, ['Boots', 'AttackSpeed'], frm=[1001]),
]}
LEBLANC = {'id': 'Leblanc', 'name': '르블랑', 'tags': ['Assassin', 'Mage'], 'damage_rating': 'AP'}
COMPOSITION = {'damage_rating_counts': {'AD': 3, 'AP': 1}}


class BuildStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'k.db'

    def test_samples_keep_only_build_facts_and_skip_other_queues(self):
        samples, patch = samples_from_match(match('KR_1'))
        self.assertEqual(patch, '16.19')
        self.assertEqual(samples[0]['items'], [6655, 3089, 3020])          # 빈 칸·장신구 제외
        self.assertEqual((samples[0]['keystone'], samples[0]['sub_style']), (8112, 8200))
        self.assertNotIn('puuid', json.dumps(samples))                        # 소환사 정보는 저장하지 않음
        self.assertEqual(samples_from_match(match('KR_2', queue=450))[0], [])  # 칼바람 제외
        self.assertEqual(samples_from_match(match('KR_3', duration=300))[0], [])  # 다시하기 제외
        self.assertEqual(patch_of('16.9.1.2'), '16.9')

    def test_popularity_counts_recent_patches_and_prunes_old_ones(self):
        with closing(connect(self.path)) as db, db:
            for n in range(MIN_GAMES):
                save_match(db, 'KR_%d' % n, match('KR_%d' % n))
            save_match(db, 'OLD_1', match('OLD_1', version='16.10.1.1'))
            save_match(db, 'OLD_2', match('OLD_2', version='16.9.1.1'))
            prune(db, keep=2)
            patches = {r[0] for r in db.execute('SELECT DISTINCT patch FROM build_samples')}
        self.assertEqual(patches, {'16.19', '16.10'})
        stats = item_popularity(self.path, 'Leblanc', 'MIDDLE')
        self.assertEqual(stats['games'], MIN_GAMES + 1)
        self.assertEqual(stats['items'][6655], 1.0)
        self.assertEqual(stats['keystones'][8112], 1.0)
        self.assertEqual(item_popularity(self.path, 'Zed')['games'], 0)

    def test_collect_uses_high_elo_players_and_skips_known_matches(self):
        calls = []

        class Gateway:
            def get(self, routing, path, params=None):
                calls.append(path)
                if 'challengerleagues' in path:
                    return {'entries': [{'puuid': 'p1', 'leaguePoints': 1000}, {'puuid': 'p2', 'leaguePoints': 900}]}
                if path.endswith('/ids'):
                    return ['KR_1', 'KR_2'] if 'p1' in path else ['KR_2', 'KR_3']
                return match(path.rsplit('/', 1)[-1])
        with closing(connect(self.path)) as db:
            fetched, saved = collect(db, Gateway(), players=2, matches=10, log=lambda m: None)
            again, _ = collect(db, Gateway(), players=2, matches=10, log=lambda m: None)
        self.assertEqual((fetched, saved, again), (3, 3, 0))                   # 같은 경기는 다시 받지 않음
        self.assertEqual(sum(1 for c in calls if c.startswith('/lol/match/v5/matches/KR')), 3)


    def test_collector_waits_out_the_shared_rate_limit(self):
        class Busy(Exception):
            retry_after = 30
        waits, state = [], {'busy': 2}

        class Gateway:
            def get(self, routing, path, params=None):
                if 'challengerleagues' in path and state['busy']:
                    state['busy'] -= 1
                    raise Busy()
                if 'leagues' in path:
                    return {'entries': [{'puuid': 'p1', 'leaguePoints': 1}]}
                return ['KR_9'] if path.endswith('/ids') else match('KR_9')
        with closing(connect(self.path)) as db:
            fetched, _ = collect(db, Gateway(), players=1, matches=5, log=lambda m: None, sleep=waits.append)
        self.assertEqual((fetched, waits), (1, [35, 35]))       # 그만두지 않고 기다렸다 이어서 받는다


class CandidateTests(unittest.TestCase):
    def pool(self, owned=(), popularity=None, profile=LEBLANC):
        from game_phases.in_game.items import candidates
        me = {'champion': '르블랑', 'items': [{'id': i, 'name': ITEMS[i]['name']} for i in owned]}
        return candidates(ITEMS, me, COMPOSITION, profile.get('damage_rating'), profile, popularity)

    def test_owned_component_suggests_its_completed_upgrade(self):
        pool = self.pool(owned=[3802])
        luden = next(c for c in pool if c['name'] == '루덴의 메아리')
        self.assertEqual((luden['role'], luden['from_owned'], luden['remaining_cost']), ('완성 가능', '사라진 양피지', 1550))
        self.assertNotIn('사라진 양피지', [c['name'] for c in pool])            # 가진 재료는 다시 추천하지 않음

    def test_class_rules_drop_items_that_do_not_fit(self):
        names = [c['name'] for c in self.pool()]
        self.assertIn('라바돈의 죽음모자', names)
        self.assertIn('존야의 모래시계', names)                                 # 마법사의 방어 아이템
        for absurd in ('구인수의 격노검', '망자의 갑옷', '무한의 대검', '광전사의 군화'):
            self.assertNotIn(absurd, names)
        self.assertIn('마법사의 신발', names)

    def test_statistics_take_priority_and_are_passed_as_grounds(self):
        popularity = {'games': MIN_GAMES, 'items': {3157: 0.62, 3089: 0.4, 3124: 0.01}}
        pool = self.pool(popularity=popularity)
        popular = [c for c in pool if c['role'] == '많이 삼']
        self.assertEqual([c['name'] for c in popular], ['존야의 모래시계', '라바돈의 죽음모자'])
        self.assertEqual(popular[0]['pick_rate'], 0.62)
        self.assertNotIn('구인수의 격노검', [c['name'] for c in pool])          # 1%는 근거가 약해 뺀다


if __name__ == '__main__':
    unittest.main()
