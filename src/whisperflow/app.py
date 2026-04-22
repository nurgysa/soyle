"""Qt application wiring: lifecycle, DI, event routing."""
from __future__ import annotations

import asyncio
import subprocess
import sys

import structlog
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QApplication

from whisperflow.core.bus import Event, EventBus
from whisperflow.core.config import ConfigStore, default_config_path
from whisperflow.core.dictionary import DictionaryStore
from whisperflow.core.errors import AudioDeviceError
from whisperflow.core.hotkey import HotkeyBox
from whisperflow.core.injector import Injector
from whisperflow.core.postprocess import PostProcess
from whisperflow.core.recorder import Recorder
from whisperflow.core.state import State, StateMachine
from whisperflow.core.transcriber import Transcriber
from whisperflow.platform.autostart import (
    disable_autostart,
    enable_autostart,
)
from whisperflow.platform.single_instance import SingleInstance
from whisperflow.ui.indicator import Indicator
from whisperflow.ui.resources import prompt_path, qss_path
from whisperflow.ui.settings import SettingsWindow
from whisperflow.ui.tray import TrayIcon

log = structlog.get_logger()


class _InferenceJob(QRunnable):
    """Runs transcription + polish on a worker thread."""

    def __init__(self, transcriber: Transcriber, postprocess: PostProcess,
                 audio, sample_rate: int, on_done, on_error) -> None:
        super().__init__()
        self._transcriber = transcriber
        self._postprocess = postprocess
        self._audio = audio
        self._sr = sample_rate
        self._on_done = on_done
        self._on_error = on_error

    def run(self) -> None:
        try:
            transcript = self._transcriber.transcribe(self._audio, sample_rate=self._sr)
            if not transcript.raw_text:
                self._on_done(transcript.raw_text, True, transcript.language)
                return
            polish = asyncio.run(
                self._postprocess.polish(transcript.raw_text, language=transcript.language)
            )
            self._on_done(polish.text, polish.fallback, transcript.language)
        except Exception as exc:
            self._on_error(exc)


class WhisperFlowApp(QObject):
    """Orchestrator: holds singletons and wires events."""

    # Cross-thread signals: worker QRunnables cannot reliably use QTimer.singleShot
    # because they have no Qt event loop. Signals use QueuedConnection automatically.
    _inference_done = Signal(str, bool, str)  # text, fallback, language
    _inference_error = Signal(str)  # error message

    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self._qapp = qapp

        self._bus = EventBus()
        self._state = StateMachine()
        self._store = ConfigStore()
        self._dict_store = DictionaryStore()
        self._cfg = self._store.load()

        self._indicator = Indicator()
        self._tray = TrayIcon()
        self._settings_window: SettingsWindow | None = None

        self._recorder = Recorder(bus=self._bus)
        self._injector = Injector(bus=self._bus)
        self._transcriber = Transcriber(
            model=self._cfg.whisper.model,
            device=self._cfg.whisper.device,
            compute_type=self._cfg.whisper.compute_type,
            language=self._cfg.whisper.language,
            initial_prompt=self._dict_store.as_whisper_prompt(),
        )
        self._postprocess = PostProcess(
            config=self._cfg.postprocess,
            api_key=self._store.get_api_key(),
            prompt_path=prompt_path(self._cfg.postprocess.prompt_file),
            dictionary_hint=self._dict_store.as_llm_instruction(),
            rewrite_prompt_path=prompt_path(self._cfg.postprocess.rewrite_prompt_file),
        )
        self._hotkey = HotkeyBox(
            bus=self._bus,
            combination=self._cfg.hotkey.combination,
            min_hold_ms=self._cfg.hotkey.debounce_ms,
        )

        self._target_hwnd = 0

        self._wire_events()
        self._wire_tray()
        self._apply_theme()

        # Bridge worker-thread inference callbacks → main thread via Qt signals.
        self._inference_done.connect(self._finish_inference)
        self._inference_error.connect(self._handle_inference_error)

    # ---- Lifecycle ----

    def start(self) -> None:
        self._tray.show()
        try:
            self._hotkey.start()
        except Exception as exc:
            log.error("hotkey_registration_failed", error=str(exc))
            self._tray.toast("WhisperFlow", "Не удалось зарегистрировать хоткей. Откройте настройки.")  # noqa: RUF001
            self._show_settings()

        # Warm up Whisper in background so first transcription is fast
        QTimer.singleShot(250, self._warm_up_transcriber)

    def quit(self) -> None:
        self._hotkey.stop()
        self._indicator.hide_indicator()
        self._tray.hide()
        self._qapp.quit()

    # ---- Event wiring ----

    def _wire_events(self) -> None:
        self._bus.subscribe(Event.HOTKEY_PRESSED, self._on_hotkey_pressed)
        self._bus.subscribe(Event.HOTKEY_RELEASED, self._on_hotkey_released)

    def _wire_tray(self) -> None:
        self._tray.settings_requested.connect(self._show_settings)
        self._tray.logs_requested.connect(self._open_logs)
        self._tray.quit_requested.connect(self.quit)
        self._tray.mode_changed.connect(self._on_mode_changed)
        # Reflect persisted mode in the submenu immediately.
        self._tray.set_mode(self._cfg.postprocess.mode)

    def _on_mode_changed(self, mode: str) -> None:
        if mode not in ("polish", "rewrite"):
            return
        self._cfg.postprocess.mode = mode  # type: ignore[assignment]
        self._store.save(self._cfg)
        # Live-update in-memory PostProcess without re-constructing.
        self._postprocess._config.mode = mode  # type: ignore[assignment]
        self._tray.set_mode(mode)
        label = "Rewrite" if mode == "rewrite" else "Polish"
        self._tray.toast("WhisperFlow", f"Режим LLM: {label}")

    # ---- Hotkey handlers ----

    def _on_hotkey_pressed(self, _: dict) -> None:
        if not self._state.can_start_recording():
            return
        try:
            self._target_hwnd = self._injector.capture_target()
            self._recorder.start(
                sample_rate=self._cfg.audio.sample_rate,
                device=self._cfg.audio.device,
            )
            self._state.transition(State.RECORDING)
            self._tray.set_recording(True)
            self._indicator.show_recording()
        except AudioDeviceError as exc:
            self._tray.toast("WhisperFlow", f"Микрофон: {exc}")
            self._state.reset_to_idle()

    def _on_hotkey_released(self, _: dict) -> None:
        if self._state.current != State.RECORDING:
            return
        try:
            result = self._recorder.stop()
        except Exception as exc:
            log.error("recorder_stop_failed", error=str(exc))
            self._state.reset_to_idle()
            self._tray.set_recording(False)
            self._indicator.hide_indicator()
            return

        self._tray.set_recording(False)

        if result.duration_ms < self._cfg.audio.vad_min_speech_ms:
            self._indicator.flash_error("Слишком коротко")
            self._state.reset_to_idle()
            return

        self._state.transition(State.TRANSCRIBING)
        self._indicator.show_transcribing()

        job = _InferenceJob(
            transcriber=self._transcriber,
            postprocess=self._postprocess,
            audio=result.audio,
            sample_rate=self._cfg.audio.sample_rate,
            on_done=self._on_inference_done,
            on_error=self._on_inference_error,
        )
        QThreadPool.globalInstance().start(job)

    # ---- Inference callbacks (always invoked from worker thread) ----

    def _on_inference_done(self, text: str, fallback: bool, language: str) -> None:
        log.info(f"on_inference_done chars={len(text)} fallback={fallback}")
        # Signal is thread-safe and uses QueuedConnection → handler runs on main thread.
        self._inference_done.emit(text, fallback, language)

    def _on_inference_error(self, exc: Exception) -> None:
        log.error(f"inference_failed error={exc}")
        self._inference_error.emit(str(exc))

    def _handle_inference_error(self, _message: str) -> None:
        self._indicator.flash_error("Ошибка распознавания")
        self._state.reset_to_idle()

    def _finish_inference(self, text: str, fallback: bool, _language: str) -> None:
        log.info(
            f"finish_inference chars={len(text)} fallback={fallback} "
            f"state={self._state.current}"
        )
        if not text.strip():
            self._indicator.flash_error("Ничего не распознано")
            self._state.reset_to_idle()
            return

        self._state.transition(State.POLISHING)
        self._indicator.show_polishing()
        self._state.transition(State.INJECTING)
        self._injector.inject(text, target_hwnd=self._target_hwnd)
        if fallback:
            self._tray.toast("WhisperFlow", "LLM недоступна — вставлен сырой текст")
        QTimer.singleShot(200, self._after_inject)

    def _after_inject(self) -> None:
        self._indicator.hide_indicator()
        self._state.reset_to_idle()

    # ---- Settings ----

    def _show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self._store, dictionary_store=self._dict_store
            )
            self._settings_window.settings_saved.connect(self._reload_config)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _reload_config(self) -> None:
        self._cfg = self._store.load()
        self._hotkey.rebind(self._cfg.hotkey.combination)
        # Refresh dictionary-dependent pieces in place (no re-construction needed).
        self._transcriber.set_initial_prompt(self._dict_store.as_whisper_prompt())
        self._postprocess = PostProcess(
            config=self._cfg.postprocess,
            api_key=self._store.get_api_key(),
            prompt_path=prompt_path(self._cfg.postprocess.prompt_file),
            dictionary_hint=self._dict_store.as_llm_instruction(),
            rewrite_prompt_path=prompt_path(self._cfg.postprocess.rewrite_prompt_file),
        )
        self._tray.set_mode(self._cfg.postprocess.mode)
        self._sync_autostart()
        self._apply_theme()
        self._tray.toast("WhisperFlow", "Настройки сохранены")

    def _sync_autostart(self) -> None:
        if self._cfg.behavior.autostart:
            exe = sys.executable
            enable_autostart(exe_path=exe)
        else:
            disable_autostart()

    def _apply_theme(self) -> None:
        theme = self._cfg.ui.theme
        if theme == "system":
            return
        qss = qss_path(theme)
        if qss.exists():
            self._qapp.setStyleSheet(qss.read_text(encoding="utf-8"))

    def _warm_up_transcriber(self) -> None:
        try:
            self._transcriber.warm_up()
        except Exception as exc:
            log.warning("warm_up_failed", error=str(exc))

    # ---- Logs ----

    def _open_logs(self) -> None:
        log_path = default_config_path().parent / "logs" / "whisperflow.log"
        if log_path.exists():
            subprocess.Popen(["notepad.exe", str(log_path)])
        else:
            self._tray.toast("WhisperFlow", "Логов пока нет")


def _configure_logging() -> None:
    log_dir = default_config_path().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "whisperflow.log"

    import logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(message)s")

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def main() -> int:
    _configure_logging()

    guard = SingleInstance()
    if not guard.acquire():
        log.info("already_running")
        return 0

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    app = WhisperFlowApp(qapp)
    app.start()

    try:
        return qapp.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
