import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from contracts.riot import AppliedRunePage, ClientNotRunning, RiotApiError, RunePageSlotsFull
from game_phases.before_game.runes import apply_recommended_page
from riot import lcu_client
from ui.pages.before_game import BeforeGamePage

PERKS = [8112, 8126, 8136, 8135, 9111, 8014, 5008, 5008, 5011]
PAGE = {'primary_style': {'id': 8100, 'name': '지배'}, 'keystone': {'id': 8112, 'name': '감전'},
        'primary': [], 'secondary_style': {'id': 8000, 'name': '정밀'}, 'secondary': [], 'shards': [],
        'selected_perk_ids': PERKS}
USER_PAGE = {'id': 3, 'name': '내 페이지', 'isDeletable': True, 'isEditable': True}
PRESET = {'id': 1, 'name': '기본 페이지', 'isDeletable': False, 'isEditable': False}


class FakeLcu:
    """LCU 요청을 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, pages, owned=5, post_status=200, post_page=None):
        self.pages, self.owned, self.post_status, self.post_page = pages, owned, post_status, post_page
        self.calls = []

    def __call__(self, port, password, method, endpoint, body=None):
        self.calls.append((method, endpoint, body))
        if (method, endpoint) == ('GET', '/lol-perks/v1/pages'):
            return 200, self.pages
        if (method, endpoint) == ('GET', '/lol-perks/v1/inventory'):
            return 200, {'ownedPageCount': self.owned}
        if method == 'POST':
            return self.post_status, (self.post_page if self.post_page is not None
                                      else dict(body, id=99, isValid=True))
        return 204, None

    def methods(self, method):
        return [call for call in self.calls if call[0] == method]


class ApplyRunePageTests(unittest.TestCase):
    def apply(self, fake, name='RiftFlow 아리'):
        with patch.object(lcu_client, '_find_lcu_credentials', return_value=(1234, 'secret')), \
             patch.object(lcu_client, '_lcu_request', side_effect=fake):
            return lcu_client.apply_rune_page(name, 8100, 8000, PERKS)

    def test_creates_new_page_in_free_slot(self):
        fake = FakeLcu([PRESET, USER_PAGE], owned=2)
        result = self.apply(fake)
        self.assertEqual(result, AppliedRunePage(99, 'RiftFlow 아리', False, True))
        self.assertEqual(fake.methods('DELETE'), [])
        self.assertEqual(fake.methods('POST')[0][2], {'name': 'RiftFlow 아리', 'primaryStyleId': 8100,
                                                      'subStyleId': 8000, 'selectedPerkIds': PERKS,
                                                      'current': True})

    def test_replaces_only_riftflow_page(self):
        own = {'id': 7, 'name': 'RiftFlow 럭스', 'isDeletable': True}
        locked = {'id': 8, 'name': 'RiftFlow 프리셋', 'isDeletable': False}
        fake = FakeLcu([USER_PAGE, locked, own], owned=3)
        result = self.apply(fake)
        self.assertTrue(result.replaced)
        self.assertEqual(fake.methods('DELETE'), [('DELETE', '/lol-perks/v1/pages/7', None)])
        self.assertNotIn(('GET', '/lol-perks/v1/inventory', None), fake.calls)

    def test_full_slots_never_delete_user_pages(self):
        fake = FakeLcu([PRESET, USER_PAGE], owned=1)
        with self.assertRaises(RunePageSlotsFull):
            self.apply(fake)
        self.assertEqual(fake.methods('DELETE'), [])
        self.assertEqual(fake.methods('POST'), [])

    def test_client_rejection_is_explained(self):
        fake = FakeLcu([], post_status=400, post_page={'message': 'Invalid perks'})
        with self.assertRaises(RiotApiError) as caught:
            self.apply(fake)
        self.assertIn('400', str(caught.exception))
        self.assertIn('Invalid perks', str(caught.exception))

    def test_selects_page_when_create_ignores_current(self):
        fake = FakeLcu([], post_page={'id': 42, 'name': 'RiftFlow 아리', 'current': False})
        self.apply(fake)
        self.assertEqual(fake.methods('PUT'), [('PUT', '/lol-perks/v1/currentpage', 42)])

    def test_long_name_is_trimmed_and_missing_client_raises(self):
        fake = FakeLcu([])
        self.apply(fake, name='RiftFlow ' + '가' * 40)
        self.assertEqual(len(fake.methods('POST')[0][2]['name']), 25)
        with patch.object(lcu_client, '_find_lcu_credentials', return_value=None):
            with self.assertRaises(ClientNotRunning):
                lcu_client.apply_rune_page('RiftFlow', 8100, 8000, PERKS)


class ApplyRecommendedPageTests(unittest.TestCase):
    def test_success_and_failure_messages(self):
        with patch('riot.apply_rune_page', return_value=AppliedRunePage(5, 'RiftFlow 아리', True, False)) as apply:
            result = apply_recommended_page(PAGE, '아리')
        apply.assert_called_once_with('RiftFlow 아리', 8100, 8000, PERKS)
        self.assertTrue(result['applied'])
        self.assertIn('교체하고', result['message'])
        self.assertIn('유효하지 않다고', result['message'])
        with patch('riot.apply_rune_page', side_effect=ClientNotRunning('x')):
            self.assertIn('실행 중이 아닙니다', apply_recommended_page(PAGE, '아리')['message'])
        with patch('riot.apply_rune_page', side_effect=RunePageSlotsFull(2)):
            self.assertIn('가득 찼습니다', apply_recommended_page(PAGE, '아리')['message'])

    def test_incomplete_page_is_not_sent(self):
        with patch('riot.apply_rune_page') as apply:
            result = apply_recommended_page(dict(PAGE, selected_perk_ids=[8112]), '아리')
        apply.assert_not_called()
        self.assertFalse(result['applied'])


class ApplyButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_follows_recommendation_state(self):
        page = BeforeGamePage()
        requests = []
        page.runeApplyRequested.connect(requests.append)
        self.assertFalse(page.apply_button.isEnabled())
        page.champion.setText('아리')
        page.rune_view.show_page = lambda _page: None   # 아이콘 렌더링은 다른 테스트에서 확인
        page.show_rune_result({'page': PAGE}, '아리')
        self.assertTrue(page.apply_button.isEnabled())
        page.set_busy(True)
        self.assertFalse(page.apply_button.isEnabled())
        page.set_busy(False)
        page.request_apply()
        self.assertEqual(requests, [{'page': PAGE, 'champion': '아리'}])
        page.show_apply_status('적용했습니다.')
        self.assertFalse(page.rune_status.isHidden())
        page.champion.setText('럭스')
        self.assertFalse(page.apply_button.isEnabled())
        self.assertTrue(page.rune_status.isHidden())
        page.close()


if __name__ == '__main__':
    unittest.main()
