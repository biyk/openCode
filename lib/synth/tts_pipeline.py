"""Конвейер озвучки: сборка блоков и параллельный синтез (миксин TTS)."""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional


class TtsPipelineMixin:
    """Миксин TextToSpeech: speak_and_play/speak_blocks и сборка по блокам."""

    def _speak_and_play_single(self, text: str,
                               on_finished: Optional[Callable[[], None]],
                               abort_event: Optional[threading.Event] = None) -> None:
        """Синтез и проигрывание одного блока."""
        if abort_event is not None and abort_event.is_set():
            print("[TTS] Воспроизведение прервано")
            if on_finished:
                on_finished()
            return
        audio_path = self.speak(text, abort_event)
        if not audio_path:
            print("[TTS] Воспроизведение отменено - файл не создан")
            if on_finished:
                on_finished()
            return
        if abort_event is not None and abort_event.is_set():
            print("[TTS] Воспроизведение прервано")
            if on_finished:
                on_finished()
            return
        self._play_file(audio_path, abort_event)
        if on_finished:
            on_finished()

    def _speak_and_play_blocks(self, blocks: list[str],
                               on_finished: Optional[Callable[[], None]],
                               abort_event: Optional[threading.Event] = None) -> None:
        """Параллельный синтез блоков и последовательное проигрывание.

        Все блоки отправляются в пул сразу: пока проигрывается блок i,
        блоки i+1… уже синтезируются (кэшированные возвращаются мгновенно),
        поэтому задержка сети на новом блоке прячется за озвучкой готовых.
        Проигрывание строго по порядку исходных блоков.

        При срабатывании abort_event синтез оставшихся блоков отменяется
        (ожидающие задачи отменяются, активная продолжается в фоне без блокировки).
        """
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            futures = [pool.submit(self.speak, s, abort_event) for s in blocks]
            for future in futures:
                if abort_event is not None and abort_event.is_set():
                    break
                audio_path = future.result()
                if audio_path:
                    self._play_file(audio_path, abort_event)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if on_finished:
            on_finished()

    def speak_blocks(self, blocks: list[str],
                     on_finished: Optional[Callable[[], None]] = None,
                     abort_event: Optional[threading.Event] = None) -> None:
        """Озвучить готовые блоки без перерезки по пунктуации.

        Даёт вызывающему контроль гранулярности: стабильные (ежедневные)
        фреймы отдельным блоком попадут в кэш и заиграют мгновенно, а
        переменные данные — своим блоком, который сгенерится во время
        проговаривания уже готового фрейма.
        """
        blocks = [b.strip() for b in blocks if b and b.strip()]
        if not blocks:
            print("[TTS] Пустой текст")
            if on_finished:
                on_finished()
            return
        if len(blocks) == 1:
            self._speak_and_play_single(blocks[0], on_finished, abort_event)
        else:
            self._speak_and_play_blocks(blocks, on_finished, abort_event)

    def speak_and_play(self, text: str,
                       on_finished: Optional[Callable[[], None]] = None,
                       abort_event: Optional[threading.Event] = None) -> None:
        """Синтез речи и воспроизведение.

        Текст режется на блоки по пунктуации и озвучивается через
        :meth:`speak_blocks`: короткий текст — одним блоком, длинный —
        параллельным синтезом блоков с проигрыванием строго по порядку.
        abort_event позволяет прервать озвучку в любой момент.
        """
        self.speak_blocks(self._split_sentences(text or ""),
                          on_finished, abort_event)
