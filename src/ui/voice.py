"""게임 중 음성 질문: 단축키, 마이크 녹음, 답 읽어 주기.

- 단축키는 윈도우 표준 RegisterHotKey로 등록한다. 키보드 후킹이 아니라 게임 입력을 가로채거나 읽지 않는다.
- 녹음은 16kHz 단일 채널로 하고, 말을 멈추면(1.2초 조용) 또는 10초가 되면 끝난다. 단축키를 다시 눌러도 끝난다.
- 답은 윈도우에 들어 있는 한국어 음성(Microsoft Heami)으로 읽는다. 따로 받을 것이 없다.
"""
import array
import io
import math
import re
import sys
import threading
import wave

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal

SAMPLE_RATE = 16000
MAX_SECONDS = 10
MAX_LEVEL = 0.06             # 말소리 기준의 최댓값 (시끄러운 방에서도 이보다 크게는 잡지 않는다)
SILENCE_STOP = 1.2           # 말이 끝나고 이만큼 조용하면 녹음을 끝낸다
NO_SPEECH_STOP = 4.0         # 이만큼 기다려도 말이 없으면 끝낸다
SPEECH_LEVEL = 0.03          # 말소리로 보는 최소 음량 (전체 음량 대비 RMS). 방이 시끄러우면 더 올라간다
HOTKEYS = ('Ctrl+Shift+V', 'Ctrl+Alt+V', 'F8', 'F9')
DEFAULT_HOTKEY = HOTKEYS[0]
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
WM_HOTKEY = 0x0312
MAX_SPOKEN = 400             # 너무 긴 답은 앞부분만 읽는다 (게임 중이라 짧게)


class SilenceGate:
    """녹음을 언제 끝낼지 정한다. feed(음량, 길이초)가 None(계속), 'done'(말 끝남), 'no_speech'(말 없음)를 돌려준다.

    처음 warmup초는 방 소음 크기를 잰다(마이크 켜는 '딱' 소리도 여기서 걸러진다). 말소리 기준은 소음의 4배와
    level 중 큰 쪽이고, 그 이상인 소리가 min_speech초 넘게 이어져야 말로 본다. 키보드 소리 한 번으로 녹음이 늘어지지 않게.
    """

    def __init__(self, silence=SILENCE_STOP, no_speech=NO_SPEECH_STOP, limit=MAX_SECONDS, level=SPEECH_LEVEL,
                 warmup=0.3, min_speech=0.25):
        self.silence, self.no_speech, self.limit, self.level = silence, no_speech, limit, level
        self.warmup, self.min_speech = warmup, min_speech
        self.elapsed = self.quiet = self.loud = 0.0
        self.noise = []
        self.heard = False

    def threshold(self):
        """방 소음(조용한 쪽 4분의 1 값)의 4배. 마이크가 자리 잡는 동안 튄 값에 끌려 너무 높아지지 않게 MAX_LEVEL로 묶는다."""
        if not self.noise:
            return self.level
        floor = sorted(self.noise)[len(self.noise) // 4]
        return max(self.level, min(MAX_LEVEL, 4 * floor))

    def feed(self, rms, seconds):
        self.elapsed += seconds
        if self.elapsed <= self.warmup:
            self.noise.append(rms)
            return None
        if rms >= self.threshold():
            self.loud += seconds
            self.quiet = 0.0
            self.heard = self.heard or self.loud >= self.min_speech
        else:
            self.quiet += seconds
            if not self.heard and self.quiet > 0.12:
                self.loud = 0.0          # 짧게 튄 소음은 잊는다 (말은 한 단어 안에서 이렇게 오래 끊기지 않는다)
        if self.heard and (self.quiet >= self.silence or self.elapsed >= self.limit):
            return 'done'
        if not self.heard and self.elapsed >= min(self.no_speech, self.limit):
            return 'no_speech'
        return None


def rms_int16(chunk):
    samples = array.array('h', chunk[:len(chunk) - len(chunk) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768


def wav_bytes(pcm, rate=SAMPLE_RATE, channels=1):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def beep(start=True):
    """녹음 시작(높은 음), 끝(낮은 음). 게임 화면에서도 들리게 소리로만 알린다."""
    if sys.platform != 'win32':
        return
    import winsound
    threading.Thread(target=winsound.Beep, args=(880 if start else 560, 110), daemon=True).start()


class VoiceRecorder(QObject):
    """마이크 녹음. finished(WAV 바이트) 또는 failed(안내 문장)를 보낸다."""
    started = Signal()
    finished = Signal(bytes)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = self.device = self.gate = None
        self.opening = False
        self.pcm = bytearray()

    @property
    def recording(self):
        return self.source is not None or self.opening

    def start(self):
        """시작 소리를 먼저 내고 0.2초 뒤에 마이크를 연다. 같이 열면 마이크가 삑 소리를 방 소음으로 잰다."""
        if self.recording:
            return
        self.opening = True
        beep(True)
        QTimer.singleShot(200, self._open)

    def _open(self):
        if not self.opening:            # 여는 사이 취소됐다
            return
        self.opening = False
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        device = QMediaDevices.defaultAudioInput()
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if device.isNull():
            self.failed.emit('마이크를 찾지 못했습니다. 윈도우 소리 설정에서 마이크를 확인해 주세요.')
            return
        if not device.isFormatSupported(fmt):
            self.failed.emit('이 마이크는 음성 질문 녹음 형식(16kHz)을 지원하지 않습니다.')
            return
        self.pcm, self.gate = bytearray(), SilenceGate()
        self.source = QAudioSource(device, fmt, self)
        self.device = self.source.start()
        if self.device is None:
            self.source = None
            self.failed.emit('마이크를 열지 못했습니다. 다른 프로그램이 마이크를 쓰고 있는지 확인해 주세요.')
            return
        self.device.readyRead.connect(self._read)
        self.started.emit()

    def _read(self):
        if self.device is None:
            return
        chunk = bytes(self.device.readAll())
        if not chunk:
            return
        self.pcm += chunk
        state = self.gate.feed(rms_int16(chunk), len(chunk) / 2 / SAMPLE_RATE)
        if state == 'done':
            self.stop()
        elif state == 'no_speech':
            self.cancel('목소리가 들리지 않아 녹음을 멈췄습니다.')

    def _close(self):
        self.opening = False
        source, self.source, self.device = self.source, None, None
        if source is not None:
            source.stop()
            source.deleteLater()

    def stop(self):
        """녹음을 끝내고 WAV를 보낸다. 말소리가 없었으면 보내지 않는다."""
        if not self.recording:
            return
        heard = self.gate.heard if self.gate else False
        self._close()
        beep(False)
        if heard:
            self.finished.emit(wav_bytes(bytes(self.pcm)))
        else:
            self.failed.emit('목소리가 들리지 않았습니다. 단축키를 누르고 바로 말해 주세요.')

    def cancel(self, message):
        if self.recording:
            self._close()
            beep(False)
            self.failed.emit(message)


def parse_hotkey(text):
    """'Ctrl+Shift+V' → (수정키 플래그, 가상 키 코드). 모르는 키면 None."""
    mods, key = 0, None
    for part in [p.strip().lower() for p in str(text).split('+') if p.strip()]:
        if part in ('ctrl', 'control'):
            mods |= MOD_CONTROL
        elif part == 'shift':
            mods |= MOD_SHIFT
        elif part == 'alt':
            mods |= MOD_ALT
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif re.fullmatch(r'f([1-9]|1[0-2])', part):
            key = 0x70 + int(part[1:]) - 1
        elif part == 'space':
            key = 0x20
        else:
            return None
    return (mods, key) if key is not None else None


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    """게임 창이 앞에 있어도 눌리는 단축키. pressed 신호를 보낸다. 윈도우가 아니면 아무것도 하지 않는다."""
    pressed = Signal()

    def __init__(self, parent=None, hotkey_id=0x5246):
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.hotkey_id = hotkey_id          # 단축키마다 다른 번호 (음성 질문 0x5246 'RF', 증강 읽기 0x5247)
        self.registered = None
        self.installed = False

    def register(self, text):
        """단축키를 바꾼다. 다른 프로그램이 이미 쓰는 키면 False."""
        self.unregister()
        parsed = parse_hotkey(text)
        if sys.platform != 'win32' or parsed is None:
            return False
        import ctypes
        from PySide6.QtCore import QCoreApplication
        if not self.installed:
            QCoreApplication.instance().installNativeEventFilter(self)
            self.installed = True
        mods, key = parsed
        if not ctypes.windll.user32.RegisterHotKey(None, self.hotkey_id, mods | MOD_NOREPEAT, key):
            return False
        self.registered = text
        return True

    def unregister(self):
        if self.registered and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, self.hotkey_id)
        self.registered = None

    def nativeEventFilter(self, event_type, message):
        if self.registered and bytes(event_type) == b'windows_generic_MSG':
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                QTimer.singleShot(0, self.pressed.emit)
        return False, 0


def spoken_text(text):
    """읽기 좋게: 마크다운 기호, 목록 기호, 링크를 걷어 내고 앞부분만."""
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', str(text or ''))
    text = re.sub(r'[*_#`>|]+', ' ', text)
    text = re.sub(r'^\s*[-•]\s*', '', text, flags=re.M)
    text = ' '.join(text.split())
    return text[:MAX_SPOKEN]


class Speaker(QObject):
    """답 읽어 주기. 한국어 음성이 없으면 조용히 아무것도 하지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = None

    def _engine(self):
        if self.engine is None:
            from PySide6.QtCore import QLocale
            from PySide6.QtTextToSpeech import QTextToSpeech
            for name in ('winrt', 'sapi'):
                if name not in QTextToSpeech.availableEngines():
                    continue
                engine = QTextToSpeech(name, self)
                korean = [v for v in engine.availableVoices() if v.locale().language() == QLocale.Korean]
                if korean:
                    engine.setVoice(korean[0])
                    self.engine = engine
                    break
            else:
                self.engine = False
        return self.engine or None

    def say(self, text):
        text = spoken_text(text)
        engine = self._engine() if text else None
        if engine is not None:
            engine.stop()
            engine.say(text)

    def stop(self):
        if self.engine:
            self.engine.stop()
