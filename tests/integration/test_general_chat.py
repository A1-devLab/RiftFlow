import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from contracts.riot import MatchSummary, PlayerIdentity
from ui.services import ask_general


class GeneralChatTests(unittest.TestCase):
    def test_answers_lol_practice_without_documents(self):
        with tempfile.TemporaryDirectory() as folder:
            generate = Mock(return_value={'text': '연습 모드에서 CS 연습을 해보세요.'})
            result = ask_general(Path(folder) / 'missing.db', 'CS 연습 방법 알려줘', generate=generate)
        self.assertTrue(result['generated'])
        generate.assert_called_once()
        self.assertEqual(result['evidence'], [])

    def test_passes_actual_matches_without_identifiers(self):
        match = MatchSummary('private-match', 123, 1800, 'CLASSIC', 'Ahri', True, 7, 2, 9, 180)
        profile = dict(player=PlayerIdentity('private-puuid', 'private-name'), rank=None, matches=[match])
        with tempfile.TemporaryDirectory() as folder:
            generate = Mock(return_value={'text': '최근 1경기를 기준으로 설명합니다.'})
            ask_general(Path(folder) / 'missing.db', '내 장단점을 알려줘', generate=generate, profile=profile)
        prompt = generate.call_args.args[0]
        context = json.loads(prompt['user'])['profile']
        self.assertEqual(context['recent_matches'][0]['kills'], 7)
        self.assertEqual(context['recent_matches'][0]['cs'], 180)
        self.assertNotIn('private-', prompt['user'])

    def test_disconnected_profile_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            generate = Mock(return_value={'text': '전적을 연결해 주세요.'})
            ask_general(Path(folder) / 'missing.db', '내 전적 분석해줘', generate=generate)
        self.assertIsNone(json.loads(generate.call_args.args[0]['user'])['profile'])

    def test_provider_failure_returns_error_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            result = ask_general(Path(folder) / 'missing.db', '안녕', generate=Mock(side_effect=RuntimeError('secret')))
        self.assertFalse(result['generated'])
        self.assertEqual(result['status'], 'model_error')
        self.assertNotIn('secret', result['message'])

    def test_patch_without_evidence_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as folder:
            generate = Mock()
            result = ask_general(Path(folder) / 'missing.db', '26.19 패치 변경 알려줘', generate=generate)
        generate.assert_not_called()
        self.assertEqual(result['status'], 'insufficient_evidence')

    def test_patch_uses_only_requested_official_patch_version(self):
        from unittest.mock import patch
        from ui.services import create_demo
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'demo.db'
            create_demo(path)
            generate = Mock(return_value={'text': '확인된 변경입니다.'})
            with patch('ui.services.DocumentSource') as source:
                source.return_value.chunks.return_value = []
                ask_general(path, '26.19 패치 알려줘', generate=generate)
                self.assertEqual(source.call_args.kwargs['kinds'], ('patch',))
                source.return_value.chunks.assert_called_once_with('26.19')
            generate.assert_not_called()
