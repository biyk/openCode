"""Проверки записывающих устройств: имена, токены, «живы ли наушники»."""
from lib.runtime import mic_devices as md

# Реальные имена с этого ПК: вход гарнитуры висит в списке и когда она
# выключена, а имя содержит CR/LF.
HEADSET = ('Головной телефон (@System32\\drivers\\bthhfenum.sys,#2;'
           '%1 Hands-Free%0\r\n;(soundcore H30i))')
LAPTOP = "Микрофон (Realtek(R) Audio)"
OTHER_BT = "Головной телефон (...;(BH-07))"


class TestCleanName:
    """Имена BT-эндпоинтов с CR/LF внутри приводим к одной строке."""

    def test_crlf_collapsed(self):
        assert "H30i" in md.clean_name(HEADSET)
        assert "\r" not in md.clean_name(HEADSET)
        assert "\n" not in md.clean_name(HEADSET)

    def test_empty_is_empty_string(self):
        assert md.clean_name(None) == ""


class TestInputDevices:
    """Список входов: только те, с чего можно писать."""

    def test_only_capture_devices(self):
        rows = [{"name": LAPTOP, "max_input_channels": 2},
                {"name": "Динамики", "max_input_channels": 0}]
        assert md.input_devices(rows) == [(0, LAPTOP)]

    def test_indices_are_positions_in_full_list(self):
        """Индекс — позиция во всём списке PortAudio, а не среди входов."""
        rows = [{"name": "Динамики", "max_input_channels": 0},
                {"name": LAPTOP, "max_input_channels": 2}]
        assert md.input_devices(rows) == [(1, LAPTOP)]

    def test_unavailable_device_skipped(self):
        rows = [{"name": LAPTOP, "max_input_channels": 2, "available": False}]
        assert md.input_devices(rows) == []

    def test_probe_failure_is_empty_list(self, mocker):
        """Сбой перечисления не роняет цикл: просто нет кандидатов."""
        mocker.patch.object(md.sd, "query_devices", side_effect=OSError("pa"))
        assert md.input_devices() == []


class TestMatchDevice:
    """Токен в имени (регистр не важен); skip не пускает гарнитуру."""

    NAMED = [(0, md.clean_name(HEADSET)), (1, LAPTOP), (2, OTHER_BT)]

    def test_headset_token_matches_its_input(self):
        assert md.match_device(self.NAMED, "soundcore H30i") == (
            0, md.clean_name(HEADSET))

    def test_match_is_case_insensitive(self):
        assert md.match_device(self.NAMED, "SOUNDCORE h30i")[0] == 0

    def test_first_candidate_wins(self):
        named = [(5, LAPTOP), (1, LAPTOP)]
        assert md.match_device(named, "realtek") == (5, LAPTOP)

    def test_skip_keeps_laptop_off_the_headset(self):
        """Имя адаптера попадает во вход гарнитуры — его и надо отсечь."""
        named = [(0, "Микрофон (soundcore H30i Hands-Free)"), (1, LAPTOP)]
        got = md.match_device(named, "soundcore", skip="soundcore H30i")
        assert got is None

    def test_empty_token_matches_nothing(self):
        assert md.match_device(self.NAMED, "") is None

    def test_unknown_token(self):
        assert md.match_device(self.NAMED, "haier tv") is None


class TestSafeInputs:
    """Звонковые входы не открываем: с ними гарнитура замолкает (A2DP ↔ HFP)."""

    TRUNCATED = "Головной телефон (soundcore H30"      # обрезано Windows
    BTHF = "Головной телефон (...bthhfenum.sys...Hands-Free...(soundcore H30i))"
    USB_MIC = "Микрофон (USB Headset)"

    def test_all_forms_of_the_headset_input_are_call_inputs(self):
        for name in (md.clean_name(HEADSET), self.TRUNCATED, self.BTHF):
            assert md.is_call_input(name), name

    def test_laptop_and_usb_mics_are_not_call_inputs(self):
        """USB-гарнитуру не режем: конфликта профилей у неё нет."""
        assert not md.is_call_input(LAPTOP)
        assert not md.is_call_input(self.USB_MIC)

    def test_token_catches_a_headset_named_by_model(self):
        """Драйвер может назвать вход моделью без слова «головной»."""
        assert md.is_call_input("soundcore H30i Stereo Mic", "soundcore H30i")

    def test_empty_token_matches_nothing_extra(self):
        assert not md.is_call_input(LAPTOP, "")

    def test_safe_inputs_keeps_the_laptop_mic(self):
        named = [(1, self.TRUNCATED), (2, LAPTOP), (3, self.USB_MIC)]
        want = [(2, LAPTOP), (3, self.USB_MIC)]
        assert md.safe_inputs(named, "soundcore h30i") == want

    def test_allow_call_returns_everything(self):
        """`mic.headset_mic` — пользователь сам выбрал говорить в гарнитуру."""
        named = [(1, self.TRUNCATED), (2, LAPTOP)]
        assert md.safe_inputs(named, "soundcore h30i", True) == named

    def test_headset_as_the_only_input_is_fail_open(self):
        """Другого микрофона нет: оглохнуть для команд хуже, чем рисковать звуком."""
        named = [(1, self.TRUNCATED), (2, self.BTHF)]
        assert md.safe_inputs(named, "soundcore h30i") == named

    def test_empty_list_stays_empty(self):
        assert md.safe_inputs([], "soundcore h30i") == []


class TestHeadsetActive:
    """Соединённость гарнитуры решает дефолтное устройство воспроизведения."""

    def _probe(self, mocker, name):
        mocker.patch.object(md, "co_initialize")
        mocker.patch.object(md, "default_device_name", return_value=name)
        return md.headset_active("soundcore H30i")

    def test_render_in_headphones_is_true(self, mocker):
        assert self._probe(mocker, "Наушники (soundcore H30i)") is True

    def test_render_on_speakers_is_false(self, mocker):
        """Колонки — наушников нет, даже если их вход ещё в списке."""
        assert self._probe(mocker, LAPTOP.replace("Микрофон", "Динамики")) is False

    def test_no_render_device_is_unknown(self, mocker):
        assert self._probe(mocker, None) is None

    def test_com_failure_is_unknown_not_false(self, mocker):
        """Сбой COM — «не известно»: по догадке вход не переключаем."""
        mocker.patch.object(md, "co_initialize", side_effect=OSError("com"))
        assert md.headset_active("soundcore H30i") is None

    def test_empty_marker_is_unknown(self, mocker):
        mocker.patch.object(md, "co_initialize")
        mocker.patch.object(md, "default_device_name", return_value=LAPTOP)
        assert md.headset_active("") is None


class TestDefaultInputIndex:
    """Индекс системного входа — чтобы смену дефолта тоже замечать."""

    def test_index_taken_from_portaudio(self, mocker):
        mocker.patch.object(md.sd, "query_devices",
                            return_value={"index": 1, "name": LAPTOP})
        assert md.default_input_index() == 1

    def test_failure_is_none(self, mocker):
        mocker.patch.object(md.sd, "query_devices", side_effect=OSError("pa"))
        assert md.default_input_index() is None
