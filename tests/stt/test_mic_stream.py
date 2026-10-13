"""Наблюдатель микрофона: пишем с ноутбука, звонковый вход гарнитуры — по просьбе."""
import lib.stt.mic_stream as ms
from lib.stt.mic_stream import DEFAULT_LABEL, MicWatcher

HEADSET = (12, "Головной телефон (…;(soundcore H30i))")
LAPTOP = (1, "Микрофон (Realtek(R) Audio)")
USB = (3, "Микрофон (USB Audio Device)")


class FakeMatcher:
    """Матчер с одной секцией конфига — как в test_record_gate.py."""

    def __init__(self, config):
        self._config = config

    def get_mic_config(self):
        return self._config


def mock_output(mocker, watcher):
    """Вывод наблюдателя на магическом моке: реплики видны в asserts."""
    output = mocker.MagicMock()
    watcher._output = output
    return output


def watch(devices, connected=None, default=None, poll_s=0.0, headset_mic=False):
    """Наблюдатель на подставных проверках: без PortAudio и без COM."""
    return MicWatcher(headphone="soundcore H30i", laptop="realtek",
                      headset_mic=headset_mic, poll_s=poll_s,
                      headset_active=lambda: connected,
                      devices=lambda: list(devices),
                      default_index=lambda: default)


class TestTargetRule:
    """Какой вход нужен прямо сейчас."""

    def test_connected_headphones_keep_the_laptop_mic(self):
        """Наушники подключены — их микрофон всё равно не трогаем: с HFP-входом
        гарнитура уходит в режим разговора и её стерео-звук молчит."""
        assert watch([LAPTOP, HEADSET], True).target() == LAPTOP

    def test_probe_answer_does_not_move_the_target(self):
        """Нет зависимости от «подключены ли наушники» — нет и самопереключения:
        раньше открытие BT-микрофона меняло вывод, вывод — решение о микрофоне."""
        for connected in (True, False, None):
            assert watch([LAPTOP, HEADSET], connected).target() == LAPTOP

    def test_headset_mic_is_used_only_when_allowed(self):
        """Явное `headset_mic` — прежнее поведение, но мёртвый вход не берём."""
        on = watch([LAPTOP, HEADSET], True, headset_mic=True)
        off = watch([LAPTOP, HEADSET], False, headset_mic=True)
        assert on.target() == HEADSET and off.target() == LAPTOP

    def test_headset_alone_is_better_than_no_mic(self):
        """Другого входа нет — берём звонковый: оглохнуть для команд хуже."""
        assert watch([HEADSET], True).target() == HEADSET

    def test_system_default_pointing_at_the_headset_is_skipped(self):
        """Windows делает микрофон гарнитуры системным по умолчанию — не верим."""
        got = watch([HEADSET, LAPTOP], True, default=HEADSET[0])
        assert got.target() == LAPTOP

    def test_no_tokens_at_all_use_system_default(self):
        """Ни гарнитуры, ни ноутбука — пишем системным дефолтом по индексу."""
        got = MicWatcher(devices=lambda: [LAPTOP], default_index=lambda: 1)
        assert got.target() == LAPTOP

    def test_default_index_unknown_means_none_device(self):
        """None в индексе = «отдай системный вход» (PortAudio сам решит)."""
        got = MicWatcher(devices=lambda: [], default_index=lambda: None)
        assert got.target() == (None, DEFAULT_LABEL)


class TestStreamLifecycle:
    """Поток захвата: открыть, пересобрать на смене, не долбить провал."""

    def _open(self, mocker, watcher):
        """Открывает поток на моке PortAudio; возвращает (фабрика, поток)."""
        stream = mocker.MagicMock()
        made = mocker.patch.object(ms.sd, "RawInputStream", return_value=stream)
        watcher.open(lambda *a: None, 16000, 2048)
        return made, stream

    def test_open_starts_chosen_device(self, mocker):
        """`RawInputStream` сам не играет: без start() захват молчит."""
        made, stream = self._open(mocker, watch([LAPTOP, HEADSET], True))
        assert made.call_args.kwargs["device"] == LAPTOP[0]
        stream.start.assert_called_once_with()

    def test_vanished_input_reopens_on_the_remaining_one(self, mocker):
        """Микрофон исчез из списка (вынули USB) — поток пересобирается."""
        devices = [LAPTOP, USB]
        watcher = watch(devices)
        made, old = self._open(mocker, watcher)
        devices.remove(LAPTOP)
        assert watcher.follow() is True
        old.stop.assert_called_once_with()
        old.close.assert_called_once_with()
        assert made.call_args_list[-1].kwargs["device"] == USB[0]

    def test_disconnect_reopens_on_laptop(self, mocker):
        """В разрешённом режиме смена соединённости по-прежнему пересобирает."""
        connected = {"on": True}
        watcher = watch([LAPTOP, HEADSET], headset_mic=True)
        watcher._headset_active = lambda: connected["on"]
        made, old = self._open(mocker, watcher)
        connected["on"] = False
        assert watcher.follow() is True
        assert made.call_args_list[-1].kwargs["device"] == LAPTOP[0]

    def test_same_target_does_not_reopen(self, mocker):
        """Без смены входа поток не дёргается (щелчки на каждом такте ни к чему)."""
        watcher = watch([LAPTOP, HEADSET], True)
        made, _ = self._open(mocker, watcher)
        assert watcher.follow() is False
        assert made.call_count == 1

    def test_poll_s_limits_rechecks(self, mocker):
        """Опрос не чаще poll_s: смену заметим, но списки дёргаем редко."""
        devices = [LAPTOP, USB]
        watcher = watch(devices, poll_s=60.0)
        self._open(mocker, watcher)
        devices.remove(LAPTOP)
        assert watcher.follow() is False      # ещё не время пересчитывать

    def test_failed_open_is_announced_and_parked(self, mocker):
        """Не открылось — ошибка в консоль и пауза: провал не долбим опросами."""
        watcher = watch([LAPTOP, HEADSET], True, default=1)
        output = mock_output(mocker, watcher)
        mocker.patch.object(ms.sd, "RawInputStream", side_effect=OSError("busy"))
        watcher.open(lambda *a: None, 16000, 2048)
        assert watcher._stream is None
        assert "busy" in output.print_error.call_args[0][0]
        assert watcher.follow() is False      # retry_s держит пробку закрытой

    def test_retry_backoff_expires_and_device_reopens(self, mocker):
        watcher = watch([LAPTOP, HEADSET], True, default=1)
        mocker.patch.object(ms.sd, "RawInputStream", side_effect=OSError("busy"))
        watcher.open(lambda *a: None, 16000, 2048)
        watcher._retry_at = 0.0
        made = mocker.patch.object(ms.sd, "RawInputStream")
        assert watcher.follow() is True
        made.assert_called_once()

    def test_close_tolerates_failure(self, mocker):
        """Сбой закрытия не роняет цикл захвата."""
        watcher = watch([LAPTOP, HEADSET], True)
        _, stream = self._open(mocker, watcher)
        stream.stop.side_effect = OSError("pa")
        watcher.close()
        assert watcher._stream is None

    def test_switch_is_announced(self, mocker):
        devices = [LAPTOP, USB]
        watcher = watch(devices, True)
        output = mock_output(mocker, watcher)
        self._open(mocker, watcher)
        devices.remove(LAPTOP)
        watcher.follow()
        said = [c[0][0] for c in output.print_info.call_args_list]
        assert any(USB[1] in m for m in said)


class TestBuildMicWatcher:
    """Фабрика: секция `mic` (+ `record_gate`) commands.json → наблюдатель."""

    def test_defaults_when_section_empty(self, mocker):
        """Без секции — дефолты модуля, гарнитура берётся у шлюза захвата."""
        probe = mocker.patch.object(ms, "headset_active", return_value=True)
        mocker.patch.object(ms, "input_devices", return_value=[HEADSET, LAPTOP])
        watcher = ms.build_mic_watcher(FakeMatcher({}))
        assert watcher.headphone == ms.RECORD_GATE_ALLOWED_DEVICE.casefold()
        assert watcher.laptop == ms.MIC_LAPTOP_DEVICE
        assert watcher.headset_mic is False
        assert watcher._poll_s == ms.MIC_POLL_S
        assert watcher.target() == LAPTOP
        probe.assert_not_called()

    def test_headset_mic_config_asks_about_connection(self, mocker):
        """Разрешение говорить в гарнитуру возвращает и вопрос о ней."""
        probe = mocker.patch.object(ms, "headset_active", return_value=True)
        mocker.patch.object(ms, "input_devices", return_value=[HEADSET, LAPTOP])
        watcher = ms.build_mic_watcher(FakeMatcher({"headset_mic": True}))
        assert watcher.target() == HEADSET
        probe.assert_called_once_with(ms.RECORD_GATE_ALLOWED_DEVICE)

    def test_headphone_token_from_gate(self, mocker):
        gate = mocker.MagicMock(allowed="Haier TV")
        watcher = ms.build_mic_watcher(FakeMatcher({}), gate)
        assert watcher.headphone == "haier tv"

    def test_config_overrides_win(self, mocker):
        watcher = ms.build_mic_watcher(
            FakeMatcher({"headphone_device": "bh-07",
                         "laptop_device": "conexant", "poll_s": 5.0}))
        assert watcher.headphone == "bh-07"
        assert watcher.laptop == "conexant"
        assert watcher._poll_s == 5.0
