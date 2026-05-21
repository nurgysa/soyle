"""Qt application wiring: lifecycle, DI, event routing."""
from __future__ import annotations

import asyncio
import contextlib
import subprocess
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import keyboard
import numpy as np
import structlog
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from soyle.core.bus import Event, EventBus
from soyle.core.cloud_sync import CloudSync, SyncOutcome, SyncResult
from soyle.core.config import ConfigStore, default_config_path
from soyle.core.dictionary import DictionaryStore
from soyle.core.errors import AudioDeviceError
from soyle.core.hotkey import HotkeyBox
from soyle.core.injector import Injector
from soyle.core.postprocess import PostProcess
from soyle.core.recorder import Recorder, trim_silence_endpoints
from soyle.core.state import State, StateMachine
from soyle.core.transcriber import Transcriber
from soyle.core.usage import UsageTracker
from soyle.platform.autostart import (
    disable_autostart,
    enable_autostart,
)
from soyle.platform.single_instance import SingleInstance
from soyle.ui.async_runnable import AsyncRunnable
from soyle.ui.floating_button import FloatingButton
from soyle.ui.indicator import Indicator
from soyle.ui.resources import prompt_path, qss_path
from soyle.ui.settings import SettingsWindow
from soyle.ui.tray import TrayIcon

log = structlog.get_logger()


# TODO(cloud_sync): replace with the real Desktop OAuth Client ID from the
# Söyle Google Cloud project before shipping. The placeholder lets the app
# import and run, but begin_oauth_flow() will hit Google's "invalid_client"
# response until this is set. The client_id is intentionally not a secret
# (PKCE flow; see docs/superpowers/specs/2026-04-30-cloud-sync-design.md
# §4 for rationale on distributing it in source).
_GOOGLE_CLIENT_ID = "REPLACE_WITH_REAL_CLIENT_ID.apps.googleusercontent.com"


class _InferenceJob(QRunnable):
    """Runs transcription + polish on a worker thread."""

    def __init__(
        self,
        transcriber: Transcriber,
        postprocess: PostProcess,
        audio: np.ndarray,
        sample_rate: int,
        # on_done callback receives (final_text, fallback_used, language,
        # reason_or_polish_outcome, cost_usd). See `run()` for the call sites.
        on_done: Callable[[str, bool, str, str, float], None],
        on_error: Callable[[Exception], None],
    ) -> None:
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
                # No speech — report empty, no polish happened.
                self._on_done(transcript.raw_text, True, transcript.language, "empty_input", 0.0)
                return
            polish = asyncio.run(
                self._postprocess.polish(transcript.raw_text, language=transcript.language)
            )
            self._on_done(
                polish.text,
                polish.fallback,
                transcript.language,
                polish.reason,
                polish.cost_usd,
            )
        except Exception as exc:
            self._on_error(exc)


class SoyleApp(QObject):
    """Orchestrator: holds singletons and wires events."""

    # Cross-thread signals: worker QRunnables cannot reliably use QTimer.singleShot
    # because they have no Qt event loop. Signals use QueuedConnection automatically.
    _inference_done = Signal(str, bool, str, str, float)  # text, fallback, lang, reason, cost
    _inference_error = Signal(str)  # error message
    _sync_done = Signal(object)  # cloud_sync.SyncResult

    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self._qapp = qapp

        self._bus = EventBus()
        self._state = StateMachine()
        self._store = ConfigStore()
        self._dict_store = DictionaryStore()
        self._cfg = self._store.load()
        self._usage = UsageTracker(default_config_path().parent / "usage.json")
        # One-shot guard: show the "bad API key" toast at most once per reload,
        # to avoid spamming the user on every hotkey release while their key
        # is invalid. Reset by _reload_config.
        self._auth_warned = False
        # Handle to the global Esc hook (registered in start()).
        # Typed Any | None because keyboard.on_press_key returns an opaque
        # hook handle; we only use it to call keyboard.unhook().
        self._esc_hook: Any | None = None

        self._indicator = Indicator()
        self._tray = TrayIcon()
        # Mouse-triggered PTT alternative; emits HOTKEY_PRESSED/RELEASED via
        # the same EventBus, so state-machine guards in _on_hotkey_pressed
        # de-dup with HotkeyBox. Hidden if user disabled in Settings.
        self._floating_button = FloatingButton(bus=self._bus)
        self._settings_window: SettingsWindow | None = None

        self._recorder = Recorder(bus=self._bus)
        self._injector = Injector(bus=self._bus, method=self._cfg.behavior.inject_method)
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
            ai_prompt_path=prompt_path(self._cfg.postprocess.ai_prompt_file),
            plain_text_path=prompt_path(self._cfg.postprocess.plain_text_file),
            task_prompt_path=prompt_path(self._cfg.postprocess.task_prompt_file),
        )
        self._hotkey = HotkeyBox(
            bus=self._bus,
            combination=self._cfg.hotkey.combination,
            min_hold_ms=self._cfg.hotkey.debounce_ms,
        )

        # Cloud Sync — Google Drive backup of dictionary.toml.
        # Constructed eagerly so `_warm_up_transcriber` can ask
        # `should_run_scheduled()` without re-checking config every time.
        self._cloud_sync = CloudSync(
            dict_store=self._dict_store,
            config_store=self._store,
            client_id=_GOOGLE_CLIENT_ID,
        )
        if not self._cloud_sync.is_configured:
            # Dev build: leave a breadcrumb in the log instead of failing
            # silently. begin_oauth_flow() will raise with a clear message
            # if the user actually tries to connect.
            log.warning(
                "cloud_sync_client_id_not_configured",
                detail="Replace _GOOGLE_CLIENT_ID in src/soyle/app.py with "
                       "a real Desktop OAuth Client ID to enable Drive sync.",
            )

        self._target_hwnd = 0

        self._wire_events()
        self._wire_tray()
        self._apply_theme()

        # Bridge worker-thread inference callbacks → main thread via Qt signals.
        self._inference_done.connect(self._finish_inference)
        self._inference_error.connect(self._handle_inference_error)
        self._sync_done.connect(self._handle_sync_outcome)

    # ---- Lifecycle ----

    def start(self) -> None:
        self._tray.show()
        if self._cfg.ui.show_floating_button:
            self._floating_button.show()
        try:
            self._hotkey.start()
        except Exception as exc:
            log.error("hotkey_registration_failed", error=str(exc))
            self._tray.toast("Söyle", "Не удалось зарегистрировать хоткей. Откройте настройки.")
            self._show_settings()

        # Esc-to-cancel: register a non-suppressing global hook. The callback
        # runs on the `keyboard` library's listener thread, so we marshal the
        # work back to the main thread via the event bus.
        try:
            self._esc_hook = keyboard.on_press_key(
                "esc",
                lambda _e: self._bus.emit(Event.CANCEL_REQUESTED, {}),
                suppress=False,
            )
        except Exception as exc:
            log.warning("esc_hook_failed", error=str(exc))

        # Initial usage label refresh.
        self._refresh_usage_menu()

        # Warm up Whisper in background so first transcription is fast
        QTimer.singleShot(250, self._warm_up_transcriber)

        # First-run wizard: if config.toml didn't exist until now, pull
        # the user into Settings and focus the API-key field. Delayed so
        # the tray icon appears first and the dialog is less jarring.
        if self._store.is_first_run:
            QTimer.singleShot(600, self._show_first_run_wizard)

    def quit(self) -> None:
        self._hotkey.stop()
        if self._esc_hook is not None:
            # Hook may already be gone (race during shutdown); we just want it
            # off, so swallow whatever the keyboard library raises.
            with contextlib.suppress(Exception):
                keyboard.unhook(self._esc_hook)
            self._esc_hook = None
        self._indicator.hide_indicator()
        self._floating_button.close()
        self._tray.hide()
        self._qapp.quit()

    # ---- Event wiring ----

    def _wire_events(self) -> None:
        self._bus.subscribe(Event.HOTKEY_PRESSED, self._on_hotkey_pressed)
        self._bus.subscribe(Event.HOTKEY_RELEASED, self._on_hotkey_released)
        self._bus.subscribe(Event.CANCEL_REQUESTED, self._on_cancel_requested)
        # Floating-button visual state mirrors the state machine.
        self._bus.subscribe(
            Event.RECORDING_STARTED,
            lambda _payload: self._floating_button.set_recording(True),
        )
        self._bus.subscribe(
            Event.RECORDING_STOPPED,
            lambda _payload: self._floating_button.set_recording(False),
        )
        self._bus.subscribe(
            Event.INJECTING,
            lambda _payload: self._floating_button.set_processing(True),
        )
        self._bus.subscribe(
            Event.INJECTED,
            lambda _payload: self._floating_button.set_processing(False),
        )

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
        self._postprocess.set_mode(mode)
        self._tray.set_mode(mode)
        label = "Rewrite" if mode == "rewrite" else "Polish"
        self._tray.toast("Söyle", f"Режим LLM: {label}")

    # ---- Hotkey handlers ----

    def _on_hotkey_pressed(self, _: dict[str, Any]) -> None:
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
            self._tray.toast("Söyle", f"Микрофон: {exc}")
            self._state.reset_to_idle()

    def _on_hotkey_released(self, _: dict[str, Any]) -> None:
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

        # Endpoint silence trimming: drops quiet head/tail frames so a
        # colleague's voice that bled in before/after your dictation
        # doesn't reach Whisper. Middle frames are untouched (full speaker
        # isolation needs voice fingerprinting — separate feature).
        audio = result.audio
        if self._cfg.audio.vad_enabled and audio.size > 0:
            audio = trim_silence_endpoints(
                audio,
                sample_rate=self._cfg.audio.sample_rate,
                threshold_rms=self._cfg.audio.silence_threshold_rms,
            )
        trimmed_duration_ms = int(len(audio) * 1000 / self._cfg.audio.sample_rate)

        if trimmed_duration_ms < self._cfg.audio.vad_min_speech_ms:
            self._indicator.flash_error("Слишком коротко")
            self._state.reset_to_idle()
            return

        self._state.transition(State.TRANSCRIBING)
        self._indicator.show_transcribing()

        job = _InferenceJob(
            transcriber=self._transcriber,
            postprocess=self._postprocess,
            audio=audio,
            sample_rate=self._cfg.audio.sample_rate,
            on_done=self._on_inference_done,
            on_error=self._on_inference_error,
        )
        QThreadPool.globalInstance().start(job)

    def _on_cancel_requested(self, _: dict[str, Any]) -> None:
        # Only react while recording; Esc during idle/transcribing is a no-op
        # so Esc keeps its normal behavior in the foreground app.
        if self._state.current != State.RECORDING:
            return
        try:
            self._recorder.stop()
        except Exception as exc:
            log.warning("cancel_stop_failed", error=str(exc))
        self._state.reset_to_idle()
        self._tray.set_recording(False)
        self._indicator.flash_error("Отменено")
        log.info("recording_cancelled")

    # ---- Inference callbacks (always invoked from worker thread) ----

    def _on_inference_done(
        self, text: str, fallback: bool, language: str, reason: str, cost_usd: float
    ) -> None:
        log.info(
            "on_inference_done",
            chars=len(text),
            fallback=fallback,
            reason=reason,
            cost_usd=round(cost_usd, 6),
        )
        # Signal is thread-safe and uses QueuedConnection → handler runs on main thread.
        self._inference_done.emit(text, fallback, language, reason, cost_usd)

    def _on_inference_error(self, exc: Exception) -> None:
        log.error("inference_failed", error=str(exc))
        self._inference_error.emit(str(exc))

    def _handle_inference_error(self, _message: str) -> None:
        self._indicator.flash_error("Ошибка распознавания")
        self._state.reset_to_idle()

    def _finish_inference(
        self,
        text: str,
        fallback: bool,
        _language: str,
        reason: str,
        cost_usd: float,
    ) -> None:
        log.info(
            "finish_inference",
            chars=len(text),
            fallback=fallback,
            reason=reason,
            state=str(self._state.current),
        )
        if not text.strip():
            self._indicator.flash_error("Ничего не распознано")
            self._state.reset_to_idle()
            return

        self._state.transition(State.POLISHING)
        self._indicator.show_polishing()
        self._state.transition(State.INJECTING)
        inject_result = self._injector.inject(text, target_hwnd=self._target_hwnd)

        if not fallback and cost_usd > 0:
            self._usage.record(cost_usd)
            self._refresh_usage_menu()
            self._check_monthly_limit(cost_usd)

        if inject_result.blocked:
            self._tray.toast(
                "Söyle",
                "Терминал: текст в буфере — вставьте вручную (Ctrl+V)",
            )
        elif fallback:
            self._show_fallback_toast(reason)

        QTimer.singleShot(200, self._after_inject)

    def _show_fallback_toast(self, reason: str) -> None:
        """Route per-reason user-facing messages. Auth failures are shown once
        per config reload to avoid toast spam."""
        if reason in ("http_401", "http_403"):
            if not self._auth_warned:
                self._auth_warned = True
                self._tray.toast(
                    "Söyle",
                    "Проверьте API-ключ OpenRouter в настройках",
                )
            return
        if reason == "http_429":
            self._tray.toast("Söyle", "OpenRouter: превышен лимит, попробуйте позже")
            return
        if reason in ("timeout", "network_error"):
            self._tray.toast("Söyle", "Сеть недоступна — вставлен сырой текст")
            return
        if reason in ("empty_input", "no_api_key"):
            # Silent: either nothing was said or the user intentionally has no key.
            return
        self._tray.toast("Söyle", "LLM недоступна — вставлен сырой текст")

    def _refresh_usage_menu(self) -> None:
        self._tray.set_usage_text(self._usage.summary_line())

    def _check_monthly_limit(self, new_cost: float) -> None:
        """Warn once when this request crossed the configured monthly cap.

        Silent if the limit is 0 (disabled), if we were already over (warning
        was shown earlier), or if we're still under. This keeps the toast as
        a single event per threshold crossing rather than per-request spam.
        """
        limit = self._cfg.behavior.monthly_cost_limit_usd
        if limit <= 0:
            return
        current, _ = self._usage.this_month()
        previous = current - new_cost
        if previous < limit <= current:
            self._tray.toast(
                "Söyle",
                f"Месячный лимит превышен: ${current:.4f} из ${limit:.2f}",
                level="warning",
            )
            log.warning(
                "monthly_limit_exceeded",
                current_usd=round(current, 6),
                limit_usd=limit,
            )

    def _after_inject(self) -> None:
        self._indicator.hide_indicator()
        self._state.reset_to_idle()

    # ---- Settings ----

    def _show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self._store,
                dictionary_store=self._dict_store,
                cloud_sync=self._cloud_sync,
                tray=self._tray,
                on_dictionary_changed=self._refresh_dictionary_consumers,
            )
            self._settings_window.settings_saved.connect(self._reload_config)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _show_first_run_wizard(self) -> None:
        self._show_settings()
        if self._settings_window is not None:
            self._settings_window.focus_api_key_setup()
        self._tray.toast(
            "Добро пожаловать в Söyle",
            "Вставьте OpenRouter API-ключ, чтобы включить полировку. "
            "Без ключа можно работать — получите сырую транскрипцию.",
        )
        log.info("first_run_wizard_shown")
        # Offer Drive sync after the API-key toast has time to land; modal
        # dialogs during warm-up create focus races, so we use a toast and
        # let the user dismiss by ignoring. The actual Connect button lives
        # in Settings → Cloud Sync (Task 15).
        QTimer.singleShot(2000, self._offer_drive_sync_step)

    def _offer_drive_sync_step(self) -> None:
        self._tray.toast(
            "Söyle — Cloud Sync",
            "Подключите Google Drive в Settings → Cloud Sync, чтобы "
            "синхронизировать словарь между устройствами и иметь backup.",
            level="info",
        )

    def _reload_config(self) -> None:
        self._cfg = self._store.load()
        self._hotkey.rebind(self._cfg.hotkey.combination)
        # Refresh in place — an in-flight _InferenceJob may still hold
        # references to these instances, so swapping them would leak state.
        self._transcriber.set_initial_prompt(self._dict_store.as_whisper_prompt())
        self._transcriber.set_language(self._cfg.whisper.language)
        self._postprocess.reload(
            config=self._cfg.postprocess,
            api_key=self._store.get_api_key(),
            prompt_path=prompt_path(self._cfg.postprocess.prompt_file),
            rewrite_prompt_path=prompt_path(self._cfg.postprocess.rewrite_prompt_file),
            ai_prompt_path=prompt_path(self._cfg.postprocess.ai_prompt_file),
            plain_text_path=prompt_path(self._cfg.postprocess.plain_text_file),
            task_prompt_path=prompt_path(self._cfg.postprocess.task_prompt_file),
            dictionary_hint=self._dict_store.as_llm_instruction(),
        )
        self._injector.set_method(self._cfg.behavior.inject_method)
        self._tray.set_mode(self._cfg.postprocess.mode)
        # Floating button visibility tracks the live config without restart.
        if self._cfg.ui.show_floating_button:
            if not self._floating_button.isVisible():
                self._floating_button.show()
        else:
            self._floating_button.hide()
        # User just saved — give the auth warning another chance if the key
        # was edited.
        self._auth_warned = False
        self._refresh_usage_menu()
        self._sync_autostart()
        self._apply_theme()
        self._tray.toast("Söyle", "Настройки сохранены")

    def _sync_autostart(self) -> None:
        if self._cfg.behavior.autostart:
            exe = sys.executable
            enable_autostart(exe_path=exe)
        else:
            disable_autostart()

    def _apply_theme(self) -> None:
        theme = self._cfg.ui.theme
        if theme == "system":
            # Clear any previously-applied stylesheet — otherwise switching
            # dark/light → system would leave the old theme stuck.
            self._qapp.setStyleSheet("")
            return
        qss = qss_path(theme)
        if not qss.exists():
            log.warning("theme_file_missing", theme=theme, path=str(qss))
            self._qapp.setStyleSheet("")
            return
        self._qapp.setStyleSheet(qss.read_text(encoding="utf-8"))

    def _warm_up_transcriber(self) -> None:
        try:
            self._transcriber.warm_up()
        except Exception as exc:
            log.warning("warm_up_failed", error=str(exc))
        # Kick the daily sync only after warm-up so first-recording latency
        # isn't competing with network IO. Predicate handles "not connected"
        # and "<24h since last sync" silently.
        if self._cloud_sync.should_run_scheduled():
            self._kick_scheduled_sync()

    def _kick_scheduled_sync(self) -> None:
        """Run cloud sync on a worker thread; result is marshalled to the
        main thread via _sync_done → _handle_sync_outcome."""
        runnable = AsyncRunnable(
            coro_factory=self._cloud_sync.sync_now,
            on_done=self._sync_done.emit,
            on_error=lambda exc: log.exception(
                "cloud_sync_unhandled", error=str(exc),
            ),
        )
        QThreadPool.globalInstance().start(runnable)

    def _handle_sync_outcome(self, result: SyncResult) -> None:
        """QueuedConnection slot — runs on Qt main thread.

        Per spec §7: silent on transient failures (NETWORK, NOT_CONNECTED,
        OK-with-no-changes), toast only when the user must act
        (auth revoked, quota, app suspended) or when new terms arrived.
        """
        if result.outcome is SyncOutcome.AUTH_REVOKED:
            self._tray.toast(
                "Söyle",
                "Google Drive отключён. Подключите заново в Settings.",
                level="warning",
            )
        elif result.outcome is SyncOutcome.QUOTA:
            self._tray.toast(
                "Söyle",
                "Google Drive переполнен. Освободите место или disconnect.",
                level="warning",
            )
        elif result.outcome is SyncOutcome.APP_SUSPENDED:
            self._tray.toast(
                "Söyle — Google заблокировал приложение",
                "Контакт: andasbek.nurgysa@gmail.com",
                level="critical",
            )
        elif result.outcome is SyncOutcome.OK and result.added_local > 0:
            self._refresh_dictionary_consumers()
            self._tray.toast(
                "Söyle",
                f"Sync: добавлено {result.added_local} терминов.",
                level="info",
            )

    def _refresh_dictionary_consumers(self) -> None:
        """Push the latest local dictionary into Transcriber + PostProcess.

        Called when sync pulled new terms from Drive (added_local > 0).
        Refreshes in place — swapping the instances would orphan an
        in-flight _InferenceJob's references — mirrors _reload_config's
        approach. Also injected as a callback into SettingsWindow so
        manual "Sync now" clicks refresh dictation consumers too
        (codex P1 on PR #19: tab-local _cs_sync_done was bypassing this).
        """
        self._transcriber.set_initial_prompt(self._dict_store.as_whisper_prompt())
        self._postprocess.set_dictionary_hint(self._dict_store.as_llm_instruction())

    # ---- Logs ----

    def _open_logs(self) -> None:
        log_path = default_config_path().parent / "logs" / "soyle.log"
        if log_path.exists():
            subprocess.Popen(["notepad.exe", str(log_path)])
        else:
            self._tray.toast("Söyle", "Логов пока нет")


def _configure_logging() -> None:
    log_dir = default_config_path().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "soyle.log"

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


def _write_crash_report(
    log_dir: Path,
    exc_type: type[BaseException],
    exc_value: BaseException,
    tb: TracebackType | None,
) -> Path:
    """Write a timestamped crash report. Returns the path on success.

    Kept as a module-level helper so tests can exercise the file-write
    behaviour without mocking sys.excepthook.
    """
    from pathlib import Path

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    crash_path = log_dir / f"crash-{stamp}.log"
    header = (
        f"Söyle crash report\n"
        f"Timestamp:  {stamp}\n"
        f"Platform:   {sys.platform}\n"
        f"Python:     {sys.version.splitlines()[0]}\n"
        f"Executable: {sys.executable}\n"
        f"Frozen:     {getattr(sys, 'frozen', False)}\n"
        f"Exception:  {exc_type.__name__}: {exc_value}\n\n"
    )
    body = "".join(traceback.format_exception(exc_type, exc_value, tb))
    crash_path.write_text(header + body, encoding="utf-8")
    return crash_path


def _install_crash_handler() -> None:
    """Route unhandled exceptions to a timestamped crash log + a user dialog.

    The handler replaces sys.excepthook, which PySide6 routes Qt slot
    errors through. File-write always runs first (that step never
    fails gracefully even if Qt is wedged), then best-effort show a
    QMessageBox with the path — but only if a QApplication exists,
    otherwise the crash happened before we could build one.
    """
    log_dir = default_config_path().parent / "logs"

    def _handler(
        exc_type: type[BaseException],
        exc_value: BaseException,
        tb: TracebackType | None,
    ) -> None:
        # Let Ctrl+C propagate normally — it's not a bug, it's a quit.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, tb)
            return

        crash_path = None
        try:
            crash_path = _write_crash_report(log_dir, exc_type, exc_value, tb)
            log.error(
                "unhandled_exception",
                exc_type=exc_type.__name__,
                message=str(exc_value),
                crash_log=str(crash_path),
            )
        except Exception:
            # Never re-raise from a crash handler.
            pass

        # Best-effort user-visible message. If we crashed before Qt was
        # up, or from a non-main thread where QMessageBox refuses to
        # build, just skip.
        try:
            qapp = QApplication.instance()
            if qapp is not None:
                box = QMessageBox()
                box.setIcon(QMessageBox.Icon.Critical)
                box.setWindowTitle("Söyle — непредвиденная ошибка")
                box.setText(f"{exc_type.__name__}: {exc_value}")
                info = "Приложите этот файл к багрепорту."
                if crash_path is not None:
                    info = f"Лог сохранён:\n{crash_path}\n\n" + info
                box.setInformativeText(info)
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.exec()
        except Exception:
            pass

        # Delegate to the default hook so Python's normal exit path
        # is triggered if this was a main-thread fatal.
        sys.__excepthook__(exc_type, exc_value, tb)

    sys.excepthook = _handler


def main() -> int:
    _configure_logging()
    _install_crash_handler()

    guard = SingleInstance()
    if not guard.acquire():
        log.info("already_running")
        return 0

    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    app = SoyleApp(qapp)
    app.start()

    try:
        return qapp.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
