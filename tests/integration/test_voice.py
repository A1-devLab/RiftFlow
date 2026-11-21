"""게임 중 음성 질문: 녹음 끝내기 판단, WAV, 단축키 해석, 음성 인식 호출, 서버 API, 질문과 답 읽기 흐름."""
import base64
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from rag import speech
from rag.gemini import GeminiError
import array

from ui.voice import MOD_CONTROL, MOD_SHIFT, SilenceGate, VoiceRecorder, louder, mic_report, parse_hotkey, rms_int16, spoken_text, wav_bytes

HAS_SERVER = all(importlib.util.find_spec(name) for name in ("fastapi", "httpx"))
WAV = wav_bytes(b'\x10\x00' * 1600)          # 0.1초짜리 WAV


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body):
    return urllib.error.HTTPError('https://x', code, 'err', {}, io.BytesIO(json.dumps(body).encode()))


class RecordingTests(unittest.TestCase):
    def test_stops_after_speech_then_silence_or_when_nobody_talks(self):
        gate = SilenceGate(silence=1.0, no_speech=3.0, limit=10)
        self.assertIsNone(gate.feed(0.002, 0.3))          # 처음 0.3초는 방 소음 재기
        self.assertIsNone(gate.feed(0.2, 0.5))            # 말하는 중
        self.assertTrue(gate.heard)
        self.assertIsNone(gate.feed(0.0, 0.6))
        self.assertEqual(gate.feed(0.0, 0.5), 'done')     # 1초 넘게 조용
        quiet = SilenceGate(silence=1.0, no_speech=3.0, limit=10)
        self.assertIsNone(quiet.feed(0.001, 2.0))
        self.assertEqual(quiet.feed(0.001, 1.0), 'no_speech')
        long = SilenceGate(silence=1.0, no_speech=3.0, limit=2, warmup=0)
        long.feed(0.3, 1.5)
        self.assertEqual(long.feed(0.3, 0.6), 'done')     # 최대 길이

    def test_a_single_click_or_a_noisy_room_is_not_speech(self):
        clicks = SilenceGate(no_speech=3.0)
        clicks.feed(0.002, 0.3)
        for _ in range(20):                               # 키보드 '딱' 소리가 가끔 튄다
            clicks.feed(0.05, 0.02)
            clicks.feed(0.002, 0.13)
        self.assertFalse(clicks.heard)
        noisy = SilenceGate()
        noisy.feed(0.02, 0.3)                             # 시끄러운 방: 기준이 올라가되 0.06에서 멈춘다
        self.assertAlmostEqual(noisy.threshold(), 0.06)
        noisy.feed(0.05, 0.5)
        self.assertFalse(noisy.heard)

    def test_a_quiet_webcam_mic_still_hears_speech(self):
        quiet = SilenceGate(no_speech=4.0)                # 실제로 잰 웹캠 마이크: 방 소음 0.0004, 말소리 0.01 안팎
        quiet.feed(0.0004, 0.3)
        quiet.feed(0.01, 0.4)
        self.assertTrue(quiet.heard)
        silent = SilenceGate(no_speech=4.0)
        silent.feed(0.0004, 0.3)
        for _ in range(10):                               # 가끔 튀는 소리(0.005, 0.1초)는 말이 아니다
            silent.feed(0.005, 0.1)
            silent.feed(0.0004, 0.2)
        self.assertFalse(silent.heard)

    def test_quiet_recordings_are_made_louder_before_recognition(self):
        quiet = array.array('h', [300, -300, 150, 0] * 100).tobytes()
        loud = array.array('h', louder(quiet))
        self.assertEqual(max(abs(s) for s in loud), int(300 * 20))   # 최대 20배
        normal = array.array('h', [20000, -20000] * 10).tobytes()
        self.assertEqual(louder(normal), normal)
        self.assertEqual(louder(b''), b'')

    def test_no_voice_message_names_the_microphone(self):
        recorder = VoiceRecorder()
        self.assertEqual(recorder.no_voice_message('안 들림.'), '안 들림.')
        recorder.mic_name = '마이크(Full HD webcam)'
        self.assertIn('Full HD webcam', recorder.no_voice_message('안 들림.'))
        self.assertIn('설정 > 음성 질문', recorder.no_voice_message('안 들림.'))

    def test_mic_test_report(self):
        self.assertIn('잘 들립니다', mic_report([0.0004] * 3 + [0.02] * 5 + [0.0004] * 22))
        self.assertIn('작게', mic_report([0.0004] * 3 + [0.003] * 27))
        self.assertIn('아무 소리도', mic_report([0.0003] * 30))
        self.assertIn('들어오지 않았습니다', mic_report([]))

    def test_level_and_wav_header(self):
        self.assertEqual(rms_int16(b''), 0.0)
        self.assertAlmostEqual(rms_int16(b'\x00\x40' * 10), 0.5, places=3)
        with wave.open(io.BytesIO(WAV)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (16000, 1, 2))

    def test_hotkey_names(self):
        self.assertEqual(parse_hotkey('Ctrl+Shift+V'), (MOD_CONTROL | MOD_SHIFT, ord('V')))
        self.assertEqual(parse_hotkey('F9'), (0, 0x78))
        self.assertIsNone(parse_hotkey('Ctrl+Shift'))
        self.assertIsNone(parse_hotkey('Ctrl+Banana'))

    def test_answers_are_cleaned_before_speaking(self):
        self.assertEqual(spoken_text('**바론**은 지금 [위험](https://x)합니다.\n- 시야 먼저'), '바론 은 지금 위험합니다. 시야 먼저')
        self.assertEqual(len(spoken_text('가' * 1000)), 400)


class TranscribeTests(unittest.TestCase):
    def test_sends_audio_with_lol_vocabulary_and_returns_text(self):
        sent = []

        def opener(request, timeout):
            sent.append(request)
            return Response(json.dumps({'text': ' 지금  바론 먹어도 돼? '}).encode())
        text = speech.transcribe(WAV, key='k1', opener=opener)
        self.assertEqual(text, '지금 바론 먹어도 돼?')
        body = sent[0].data
        self.assertIn(b'whisper-large-v3-turbo', body)
        self.assertNotIn(b'name="prompt"', body)            # 한국어 prompt를 주면 HASA whisper가 깨진다
        self.assertIn(WAV, body)
        self.assertTrue(sent[0].full_url.endswith('/audio/transcriptions'))

    def test_invalid_key_moves_to_the_next_key_once(self):
        calls = []

        def opener(request, timeout):
            calls.append(request.headers['Authorization'])
            if len(calls) == 1:
                raise http_error(403, {'detail': {'error': 'api_key_revoked'}})
            return Response(json.dumps({'text': '드래곤 언제 나와?'}).encode())
        self.assertEqual(speech.transcribe(WAV, key='bad,good', opener=opener), '드래곤 언제 나와?')
        self.assertEqual(calls, ['Bearer bad', 'Bearer good'])

    def test_silence_hallucination_and_oversize_are_refused(self):
        echo = lambda request, timeout: Response(json.dumps({'text': '시청해 주셔서 감사합니다.'}).encode())
        with self.assertRaises(GeminiError):
            speech.transcribe(WAV, key='k', opener=echo)
        with self.assertRaises(GeminiError):
            speech.transcribe(b'x' * (speech.MAX_AUDIO + 1), key='k', opener=echo)


@unittest.skipUnless(HAS_SERVER, "fastapi/httpx not installed")
class ServerVoiceTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        from server.config import Settings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = Settings(riot_api_key='test', db_path=str(Path(self.temp.name) / 'server.db'),
                            knowledge_db_path=str(Path(self.temp.name) / 'knowledge.db'), device_daily_ai=5)
        self.transcribe = Mock(return_value='한타 열어도 돼?')
        self.http = TestClient(create_app(settings, gateway=Mock(), generate=Mock(), transcribe=self.transcribe))
        self.auth = {'Authorization': 'Bearer ' + self.http.post('/v1/devices').json()['token']}

    def test_wav_is_transcribed_and_bad_audio_is_explained(self):
        audio = base64.b64encode(WAV).decode()
        ok = self.http.post('/v1/voice/transcribe', json={'audio_base64': audio}, headers=self.auth)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['text'], '한타 열어도 돼?')
        self.transcribe.assert_called_once_with(WAV)
        not_wav = base64.b64encode(b'not a wav file' * 20).decode()
        self.assertIsNone(self.http.post('/v1/voice/transcribe', json={'audio_base64': not_wav}, headers=self.auth).json()['text'])
        self.assertEqual(self.http.post('/v1/voice/transcribe', json={'audio_base64': 'x'}, headers=self.auth).status_code, 422)
        self.assertEqual(self.http.post('/v1/voice/transcribe', json={'audio_base64': audio}).status_code, 401)


class WindowVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def window(self):
        from ui.__main__ import Window
        with patch('ui.__main__.get_before_game_context', return_value=None), \
             patch('ui.__main__.champion_catalog', return_value={}):
            window = Window(Path(self.temp.name) / 'ui')
        window.champ_timer.stop()
        window.speaker = Mock()
        window.voice = Mock(value=lambda name, default: default)      # 사용자 설정 파일을 건드리지 않는다
        self.addCleanup(window.close)
        return window

    def test_transcribed_question_waits_for_the_job_then_goes_to_in_game_and_answer_is_spoken(self):
        window = self.window()
        window.on_voice_text({'text': '지금 바론 먹어도 돼?', 'message': None})
        self.assertEqual(window.pending_voice, '지금 바론 먹어도 돼?')
        asked = []
        window.in_game.askRequested.connect(asked.append)
        window.phase = 'in_game'
        window.ask_voice(window.pending_voice)
        self.assertEqual(asked[0]['question'], '지금 바론 먹어도 돼?')
        self.assertTrue(window.speak_next)
        window.show_in_game_answer({'answer': '**상대 정글**이 안 보이면 위험합니다.', 'generated': True}, '지금 바론 먹어도 돼?')
        window.speaker.say.assert_called_once_with('**상대 정글**이 안 보이면 위험합니다.')
        window.show_in_game_answer({'answer': '두 번째 답', 'generated': True}, '타이핑한 질문')
        self.assertEqual(window.speaker.say.call_count, 1)      # 직접 친 질문은 읽지 않는다

    def test_failed_transcription_is_spoken_and_nothing_is_asked(self):
        window = self.window()
        window.on_voice_text({'text': None, 'message': '목소리를 알아듣지 못했습니다.'})
        self.assertIsNone(window.pending_voice)
        window.speaker.say.assert_called_once_with('목소리를 알아듣지 못했습니다.')

    def test_outside_a_game_the_question_goes_to_the_general_chat(self):
        window = self.window()
        asked = []
        window.out_game.askRequested.connect(asked.append)
        window.ask_voice('요즘 칼바람 꿀챔 뭐야?')
        self.assertEqual(asked, ['요즘 칼바람 꿀챔 뭐야?'])


if __name__ == '__main__':
    unittest.main()
