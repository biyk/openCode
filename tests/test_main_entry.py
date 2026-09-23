"""Тесты main: точка входа приложения."""


import sys
import builtins
import types
from pathlib import Path
from unittest.mock import MagicMock
import main


class TestMainEntryPoint:
    """Гард __main__ и запуск."""

    def test_guard_executes_main(self, monkeypatch):
        """Модуль при запуске как __main__ вызывает main()."""
        calls = []

        def _stub(**attrs):
            mod = types.ModuleType("stub")
            mod.__path__ = []
            for key, value in attrs.items():
                setattr(mod, key, value)
            return mod

        class StubOutput:
            def print_text(self, text, **kwargs):
                calls.append(("text", text))

            def print_info(self, text, **kwargs):
                calls.append(("info", text))

            def print_error(self, text, **kwargs):
                calls.append(("error", text))

            def print_progress(self, *args, **kwargs):
                pass

            def print_partial(self, *args, **kwargs):
                pass

            def print_stopped(self):
                calls.append(("stopped",))

        class StubMatcher:
            def __init__(self, *args, **kwargs):
                pass

            def get_llm_config(self):
                return {}

            def get_intent_config(self):
                return {}

            def get_opencode_cli_config(self):
                return {}

            def match_config(self):
                return {}

            @property
            def triggers(self):
                return []

            def has_trigger(self, *args, **kwargs):
                return False

            def find(self, *args, **kwargs):
                return None

            def execute(self, *args, **kwargs):
                pass

            def reload(self):
                pass

        class StubLogger:
            def __init__(self, *args, **kwargs):
                pass

            def log_command(self, *args, **kwargs):
                pass

            def log_llm(self, *args, **kwargs):
                pass

            def get_llm_history(self, *args, **kwargs):
                return []

        class StubTTS:
            def __init__(self, *args, **kwargs):
                pass

            def speak_and_play(self, *args, **kwargs):
                pass

        class StubLLM:
            def ask(self, text):
                return None

        class StubProviderManager:
            def __init__(self, *args, **kwargs):
                pass

            def get_client(self, **kwargs):
                return StubLLM()

        class StubStream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def raise_on_get(*args, **kwargs):
            raise RuntimeError("stub network")

        monkeypatch.setitem(sys.modules, "lib.output", _stub(TranscriptionOutput=StubOutput))
        monkeypatch.setitem(
            sys.modules, "lib.commands", _stub(CommandMatcher=StubMatcher)
        )
        monkeypatch.setitem(sys.modules, "lib.logger", _stub(Logger=StubLogger))
        monkeypatch.setitem(sys.modules, "lib.tts", _stub(TextToSpeech=StubTTS))
        monkeypatch.setitem(sys.modules, "lib.providers", _stub())
        monkeypatch.setitem(
            sys.modules,
            "lib.config_loader",
            _stub(get_device_commands_path=lambda *a, **k: "commands.json"),
        )
        monkeypatch.setitem(
            sys.modules, "lib.providers.manager",
            _stub(ProviderManager=StubProviderManager),
        )
        monkeypatch.setitem(
            sys.modules, "sounddevice", _stub(RawInputStream=lambda **kw: StubStream())
        )
        monkeypatch.setitem(
            sys.modules,
            "vosk",
            _stub(
                Model=lambda *a: object(),
                KaldiRecognizer=lambda *a: MagicMock(),
                SetLogLevel=lambda *a: None,
            ),
        )
        monkeypatch.setitem(sys.modules, "requests", _stub(get=raise_on_get))

        builtins_dict = dict(vars(builtins))
        builtins_dict["input"] = lambda prompt=None: ""
        source = Path(main.__file__).read_text(encoding="utf-8")

        exec(compile(source, main.__file__, "exec"), {
            "__name__": "__main__",
            "__file__": main.__file__,
            "__builtins__": builtins_dict,
        })

        assert ("stopped",) in calls
        infos = [c[0] for c in calls if c[0] == "info"]
        assert len(infos) >= 2
