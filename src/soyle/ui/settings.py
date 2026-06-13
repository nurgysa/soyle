"""Settings window with tabs: Hotkey, Audio, Whisper, PostProcess, Dictionary, Cloud Sync, UI, About."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from soyle.core.cloud_sync import CloudSync, RestoreOption, SyncOutcome, SyncResult
from soyle.core.config import Config, ConfigStore
from soyle.core.dictionary import DictionaryStore
from soyle.core.postprocess import POPULAR_MODELS
from soyle.core.transcriber import WHISPER_MODELS
from soyle.ui.async_runnable import AsyncRunnable
from soyle.ui.shortcut_capture import ShortcutCaptureDialog
from soyle.ui.tray import TrayIcon

# Curated list of known-good push-to-talk keys. Editable combobox
# falls back to arbitrary string input for anything not listed.
HOTKEY_PRESETS = (
    "right alt",
    "right ctrl",
    "right shift",
    "caps lock",
    "scroll lock",
    "pause",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
)


class SettingsWindow(QMainWindow):
    """Tabbed settings editor; saves Config via ConfigStore."""

    settings_saved = Signal()
    # Cross-thread signals for the Cloud Sync tab's worker callbacks.
    # AsyncRunnable.on_done/on_error fire on the QThreadPool worker; signals
    # auto-marshal back to the main thread via QueuedConnection.
    _cs_connect_done = Signal(object)  # RestoreOption | None
    _cs_sync_done = Signal(object)  # SyncResult
    _cs_disconnect_done = Signal()
    _cs_action_failed = Signal(str)  # error message for toast

    def __init__(
        self,
        store: ConfigStore,
        dictionary_store: DictionaryStore | None = None,
        cloud_sync: CloudSync | None = None,
        tray: TrayIcon | None = None,
        on_dictionary_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._dict_store = dictionary_store or DictionaryStore()
        self._cloud_sync = cloud_sync
        self._tray = tray
        # Invoked when manual Sync now pulled new terms from Drive — lets
        # SoyleApp refresh Transcriber + PostProcess in place so dictation
        # picks up new terms immediately, not after the next config save.
        self._on_dictionary_changed = on_dictionary_changed
        self._cfg: Config = store.load()

        self.setWindowTitle(self.tr("Söyle — настройки"))
        self.resize(560, 440)

        central = QWidget()
        root = QVBoxLayout(central)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_hotkey_tab(), self.tr("Хоткей"))
        self._tabs.addTab(self._build_audio_tab(), self.tr("Аудио"))
        self._tabs.addTab(self._build_whisper_tab(), "Whisper")
        self._tabs.addTab(self._build_postprocess_tab(), "LLM")
        self._tabs.addTab(self._build_dictionary_tab(), self.tr("Словарь"))
        # Cloud Sync sits right after Словарь — it backs up dictionary.toml,
        # so users browsing dictionary settings stay in context.
        if self._cloud_sync is not None:
            self._tabs.addTab(self._build_cloud_sync_tab(), "Cloud Sync")
        self._tabs.addTab(self._build_ui_tab(), self.tr("Внешний вид"))
        self._tabs.addTab(self._build_about_tab(), self.tr("О программе"))
        root.addWidget(self._tabs)

        # Wire the worker-thread signals to main-thread slots.
        self._cs_connect_done.connect(self._on_connect_done)
        self._cs_sync_done.connect(self._on_sync_done)
        self._cs_disconnect_done.connect(self._on_disconnect_done)
        self._cs_action_failed.connect(self._on_action_failed)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton(self.tr("Сохранить"))
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        btn_close = QPushButton(self.tr("Закрыть"))
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        self.setCentralWidget(central)

    # ---- Tabs ----

    def _build_hotkey_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        # Editable combobox: curated presets + arbitrary user input.
        # `keyboard.hook_key` requires a single key (not a combo), so
        # presets are the single keys we've verified behave well for PTT.
        self._hk_combination = QComboBox()
        self._hk_combination.setEditable(True)
        for preset in HOTKEY_PRESETS:
            self._hk_combination.addItem(preset)
        current = self._cfg.hotkey.combination
        idx = self._hk_combination.findText(current)
        if idx >= 0:
            self._hk_combination.setCurrentIndex(idx)
        else:
            self._hk_combination.setEditText(current)

        # "Записать…" opens a capture dialog that detects the pressed
        # key — saves the user from guessing the exact string format.
        self._hk_capture_btn = QPushButton(self.tr("Записать…"))
        self._hk_capture_btn.setFixedWidth(100)
        self._hk_capture_btn.setToolTip(
            self.tr("Нажать клавишу и распознать её автоматически")
        )
        self._hk_capture_btn.clicked.connect(self._capture_hotkey_clicked)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self._hk_combination, 1)
        hotkey_row.addWidget(self._hk_capture_btn)
        layout.addRow(self.tr("Клавиша:"), hotkey_row)

        self._hk_mode = QComboBox()
        self._hk_mode.addItems(["push_to_talk", "toggle"])
        self._hk_mode.setCurrentText(self._cfg.hotkey.mode)
        layout.addRow(self.tr("Режим:"), self._hk_mode)
        self._hk_debounce = QSpinBox()
        self._hk_debounce.setRange(0, 1000)
        self._hk_debounce.setValue(self._cfg.hotkey.debounce_ms)
        layout.addRow(self.tr("Debounce (мс):"), self._hk_debounce)
        return w

    def _capture_hotkey_clicked(self) -> None:
        dlg = ShortcutCaptureDialog(self)
        if dlg.exec() and dlg.captured:
            captured = dlg.captured
            # If the captured key matches a preset, select it in the
            # combobox; otherwise fall back to free-text.
            idx = self._hk_combination.findText(captured)
            if idx >= 0:
                self._hk_combination.setCurrentIndex(idx)
            else:
                self._hk_combination.setEditText(captured)

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._audio_device = QLineEdit(self._cfg.audio.device)
        layout.addRow(self.tr("Устройство:"), self._audio_device)
        self._audio_max = QSpinBox()
        self._audio_max.setRange(1, 600)
        self._audio_max.setValue(self._cfg.audio.max_recording_seconds)
        layout.addRow(self.tr("Макс. запись (сек):"), self._audio_max)

        self._audio_vad = QCheckBox(
            self.tr("Обрезать тишину в начале и конце записи")
        )
        self._audio_vad.setChecked(self._cfg.audio.vad_enabled)
        self._audio_vad.setToolTip(
            self.tr(
                "Удаляет тихие фреймы по краям записи. Помогает когда коллеги "
                "говорят рядом — их голос будет ниже порога и обрежется."
            )
        )
        layout.addRow(self._audio_vad)

        # 0.005-step QDoubleSpinBox covers the realistic operating range:
        # 0.01 = sensitive (open mic, picks up far voices),
        # 0.02 = default (good for normal home setup),
        # 0.04-0.06 = office (only close-talking speech survives),
        # 0.08+ = very strict (whispers near mic get dropped).
        self._audio_threshold = QDoubleSpinBox()
        self._audio_threshold.setDecimals(3)
        self._audio_threshold.setRange(0.001, 0.200)
        self._audio_threshold.setSingleStep(0.005)
        self._audio_threshold.setValue(self._cfg.audio.silence_threshold_rms)
        self._audio_threshold.setToolTip(
            self.tr(
                "Порог RMS-энергии для определения тишины. "
                "Ниже = пропускает тихую/удалённую речь. "
                "Выше = только громкая близкая речь."
            )
        )
        layout.addRow(self.tr("Порог тишины (RMS):"), self._audio_threshold)
        return w

    def _build_whisper_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)

        # Editable combobox: curated presets + free-text fallback for any
        # checkpoint name faster-whisper accepts (Hugging Face IDs,
        # Systran/faster-* mirrors, etc.). Same pattern as the LLM model
        # picker.
        self._w_model = QComboBox()
        self._w_model.setEditable(True)
        for preset in WHISPER_MODELS:
            self._w_model.addItem(preset.display_label, preset.model_id)
        current = self._cfg.whisper.model
        preset_idx = self._w_model.findData(current)
        if preset_idx >= 0:
            self._w_model.setCurrentIndex(preset_idx)
        else:
            self._w_model.setEditText(current)
        layout.addRow(self.tr("Модель:"), self._w_model)
        self._w_device = QComboBox()
        self._w_device.addItems(["auto", "cuda", "cpu"])
        self._w_device.setCurrentText(self._cfg.whisper.device)
        layout.addRow(self.tr("Device:"), self._w_device)
        self._w_compute = QComboBox()
        self._w_compute.addItems(["int8", "float16", "float32"])
        self._w_compute.setCurrentText(self._cfg.whisper.compute_type)
        layout.addRow(self.tr("Compute type:"), self._w_compute)

        # None = auto-detect (Whisper picks per utterance). Forcing a language
        # avoids cross-language mis-detections at the cost of failing on the
        # rare other-language utterance. Kazakh ("kk") is intentionally not
        # exposed here: faster-whisper checkpoints + CTranslate2 hang on
        # GTX 16-series GPUs (Turing without tensor cores) for KZ inference,
        # and CPU+small produces too many hallucinations to be useful.
        # Prompts and tests retain KZ rules so re-adding "kk" is one line.
        self._w_language = QComboBox()
        self._w_language.addItem(
            self.tr("Авто (определять автоматически)"), None
        )
        self._w_language.addItem("Русский", "ru")
        self._w_language.addItem("English", "en")
        idx = self._w_language.findData(self._cfg.whisper.language)
        self._w_language.setCurrentIndex(max(0, idx))
        layout.addRow(self.tr("Язык:"), self._w_language)

        # Hint label — same muted styling as the Cloud Sync last-synced
        # subtitle. Honest framing: KZ recognition is currently unreliable
        # on this hardware. Auto-detect frequently misclassifies Kazakh
        # speech as Russian/Arabic/Azerbaijani; forcing language="kk"
        # would deadlock CT2 on GTX 16xx. See research notes:
        # docs/research/2026-05-23-kz-detection-root-cause.md
        self._w_language_hint = QLabel(
            self.tr(
                "Auto-detect рекомендуется для смешанной RU+EN речи. "
                "Принудительный выбор ru/en даёт лучше recognition "
                "строго-моноязычной диктовки, но ломает code-switching. "
                "Казахский пока ненадёжен — fix в работе (dual-model)."
            )
        )
        self._w_language_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._w_language_hint.setWordWrap(True)
        layout.addRow("", self._w_language_hint)
        return w

    def _build_postprocess_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._pp_enabled = QCheckBox(self.tr("Включить постобработку LLM"))
        self._pp_enabled.setChecked(self._cfg.postprocess.enabled)
        layout.addRow(self._pp_enabled)

        self._pp_mode = QComboBox()
        self._pp_mode.addItem(
            self.tr("Polish — чистка, пунктуация, без переформулирования"),
            "polish",
        )
        self._pp_mode.addItem(
            self.tr("Rewrite — активная переформулировка в связный текст"),
            "rewrite",
        )
        self._pp_mode.addItem(
            self.tr(
                "AI Prompt — превратить речь в инструкцию для Claude/ChatGPT/Gemini"
            ),
            "ai_prompt",
        )
        self._pp_mode.addItem(
            self.tr(
                "Plain Text — текст для документа (Word, email, мессенджер)"
            ),
            "plain_text",
        )
        self._pp_mode.addItem(
            self.tr(
                "Task — структурированная задача"
                " (Задача / Департамент / Приоритет / Описание)"
            ),
            "task",
        )
        idx = self._pp_mode.findData(self._cfg.postprocess.mode)
        self._pp_mode.setCurrentIndex(max(0, idx))
        layout.addRow(self.tr("Режим:"), self._pp_mode)

        self._pp_model = QComboBox()
        self._pp_model.setEditable(True)
        for preset in POPULAR_MODELS:
            self._pp_model.addItem(preset.display_label, preset.model_id)
        # Pre-select current value (may be from the preset list or a custom entry).
        current = self._cfg.postprocess.model
        preset_idx = self._pp_model.findData(current)
        if preset_idx >= 0:
            self._pp_model.setCurrentIndex(preset_idx)
        else:
            self._pp_model.setEditText(current)
        layout.addRow(self.tr("Модель:"), self._pp_model)
        self._pp_timeout = QDoubleSpinBox()
        self._pp_timeout.setRange(1.0, 30.0)
        self._pp_timeout.setValue(self._cfg.postprocess.timeout_seconds)
        layout.addRow(self.tr("Таймаут (сек):"), self._pp_timeout)

        # Pre-populate from keyring so "Показать" reveals the stored key.
        # The stored value is kept as `_pp_api_key_original` so we can skip
        # redundant keyring writes on save (and know when the user actually
        # edited the field).
        existing_key = self._store.get_api_key() or ""
        self._pp_api_key_original = existing_key
        self._pp_api_key = QLineEdit(existing_key)
        self._pp_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._pp_api_key.setPlaceholderText(self.tr("sk-or-v1-…"))

        self._pp_show_key_btn = QPushButton(self.tr("Показать"))
        self._pp_show_key_btn.setCheckable(True)
        self._pp_show_key_btn.setFixedWidth(90)
        self._pp_show_key_btn.setToolTip(
            self.tr("Временно сделать ключ видимым")
        )
        self._pp_show_key_btn.toggled.connect(self._toggle_key_visibility)

        self._pp_clear_key_btn = QPushButton(self.tr("Удалить"))
        self._pp_clear_key_btn.setFixedWidth(90)
        self._pp_clear_key_btn.setToolTip(
            self.tr("Стереть сохранённый ключ из Windows Credential Manager")
        )
        self._pp_clear_key_btn.clicked.connect(self._clear_api_key_clicked)

        key_row = QHBoxLayout()
        key_row.addWidget(self._pp_api_key, 1)
        key_row.addWidget(self._pp_show_key_btn)
        key_row.addWidget(self._pp_clear_key_btn)
        layout.addRow(self.tr("OpenRouter API key:"), key_row)

        # Status line — shows whether a key is currently stored and a
        # masked preview so the user can tell "which" key is active.
        self._pp_key_status = QLabel()
        self._refresh_key_status()
        layout.addRow("", self._pp_key_status)
        return w

    # ---- Cloud Sync tab ----

    def _build_cloud_sync_tab(self) -> QWidget:
        """Status + Connect/Sync/Disconnect controls for Google Drive backup.

        Tab is only registered when CloudSync was injected (production path
        — SoyleApp passes it). Tests that instantiate SettingsWindow alone
        without CloudSync skip this tab gracefully.
        """
        w = QWidget()
        layout = QVBoxLayout(w)

        _cs_desc = QLabel(
            self.tr(
                "Синхронизация словаря, настроек и истории usage через Google Drive.\n"
                "Запускается ежедневно при старте Söyle; изменения настроек уходят\n"
                "сразу же (с задержкой ~8 секунд). Поля привязанные к железу\n"
                "(микрофон, модель Whisper, тема) остаются локальными."
            )
        )
        _cs_desc.setWordWrap(True)
        _cs_desc.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(_cs_desc)

        layout.addSpacing(8)

        self._cs_status_label = QLabel(self._cloud_sync_status_text())
        layout.addWidget(self._cs_status_label)

        self._cs_last_synced_label = QLabel(self._cloud_sync_last_synced_text())
        self._cs_last_synced_label.setStyleSheet("color: #888;")
        layout.addWidget(self._cs_last_synced_label)

        layout.addSpacing(16)

        btn_row = QHBoxLayout()
        self._cs_connect_btn = QPushButton(
            self.tr("Подключить Google Drive")
        )
        self._cs_connect_btn.clicked.connect(self._on_cloud_sync_connect)
        self._cs_sync_now_btn = QPushButton(
            self.tr("Синхронизировать сейчас")
        )
        self._cs_sync_now_btn.clicked.connect(self._on_cloud_sync_sync_now)
        self._cs_disconnect_btn = QPushButton(self.tr("Отключить"))
        self._cs_disconnect_btn.clicked.connect(self._on_cloud_sync_disconnect)
        btn_row.addWidget(self._cs_connect_btn)
        btn_row.addWidget(self._cs_sync_now_btn)
        btn_row.addWidget(self._cs_disconnect_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        self._refresh_cloud_sync_buttons()
        return w

    def _cloud_sync_status_text(self) -> str:
        if self._cloud_sync is not None and self._cloud_sync.is_connected:
            return self.tr("✓ Подключено к Google Drive")
        return self.tr("Не подключено")

    def _cloud_sync_last_synced_text(self) -> str:
        if self._cloud_sync is None:
            return ""
        last = self._cloud_sync.last_synced_at
        if last is None:
            return self.tr("Последняя синхронизация: никогда")
        local = last.astimezone()
        return self.tr("Последняя синхронизация: ") + local.strftime(
            "%Y-%m-%d %H:%M"
        )

    def _refresh_cloud_sync_buttons(self) -> None:
        connected = self._cloud_sync is not None and self._cloud_sync.is_connected
        self._cs_connect_btn.setVisible(not connected)
        self._cs_sync_now_btn.setVisible(connected)
        self._cs_disconnect_btn.setVisible(connected)

    def _on_cloud_sync_connect(self) -> None:
        """Kick the OAuth flow on a worker; on completion offer restore."""
        if self._cloud_sync is None:
            return
        self._toast(
            self.tr("Söyle — Cloud Sync"),
            self.tr(
                "Открыл браузер для авторизации в Google. Подтвердите и вернитесь."
            ),
            level="info",
        )
        runnable = AsyncRunnable(
            coro_factory=self._connect_and_maybe_restore,
            on_done=self._cs_connect_done.emit,
            on_error=lambda exc: self._cs_action_failed.emit(
                f"Не удалось подключить Drive: {type(exc).__name__}",
            ),
        )
        QThreadPool.globalInstance().start(runnable)

    async def _connect_and_maybe_restore(
        self,
    ) -> tuple[RestoreOption | None, Config | None]:
        assert self._cloud_sync is not None  # button hidden when None
        await self._cloud_sync.begin_oauth_flow()
        await self._cloud_sync.complete_oauth_flow()
        dict_option = await self._cloud_sync.detect_existing_backup()
        remote_cfg = await self._cloud_sync.detect_existing_config_backup()
        return dict_option, remote_cfg

    def _on_connect_done(
        self, result: tuple[RestoreOption | None, Config | None] | RestoreOption | None,
    ) -> None:
        """Main-thread slot — refresh UI, optionally show restore prompts."""
        self._refresh_cloud_sync_buttons()
        self._cs_status_label.setText(self._cloud_sync_status_text())

        # Unpack: result is now a (dict_option, remote_cfg) tuple.
        # Guard against legacy callers passing RestoreOption | None directly.
        if isinstance(result, tuple):
            dict_option, remote_cfg = result
        else:
            dict_option, remote_cfg = result, None

        if dict_option is None and remote_cfg is None:
            self._toast(
                self.tr("Söyle — Cloud Sync"),
                self.tr("Подключено. Backup начнётся автоматически."),
            )
            return

        # --- Dict restore prompt (Phase 1) ---
        if dict_option is not None:
            box = QMessageBox(self)
            box.setWindowTitle(self.tr("Söyle — найден backup"))
            box.setText(
                self.tr(
                    "В Google Drive найден backup словаря: {count} терминов "
                    "(обновлён {date}).\n\n"
                    "Объединить с локальным словарём сейчас?"
                ).format(
                    count=dict_option.term_count,
                    date=dict_option.last_modified.strftime("%Y-%m-%d"),
                )
            )
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if box.exec() == QMessageBox.StandardButton.Yes:
                self._on_cloud_sync_sync_now()

        # --- Settings restore prompt (Phase 2) ---
        if remote_cfg is not None:
            from datetime import UTC, datetime
            from datetime import timedelta as _td

            from soyle.core.cloud_sync import _merge_config

            response = QMessageBox.question(
                self,
                self.tr("Söyle — настройки с другого устройства"),
                self.tr(
                    "Найдены настройки с другого устройства. Применить?\n"
                    "(Локальные значения для микрофона, модели Whisper и темы\n"
                    "оформления останутся как есть.)"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if response == QMessageBox.StandardButton.Yes:
                local_cfg = self._store.load()
                local_mtime = self._store.mtime()
                # Force remote to win regardless of mtime — user clicked Yes.
                far_future = datetime.now(UTC) + _td(days=365)
                merged = _merge_config(
                    local_cfg, remote_cfg, local_mtime, far_future,
                )
                self._store.apply_synced_overrides(merged)
                # Codex P1 fix on PR #30: reload self._cfg so any pending
                # _save() does NOT overwrite the just-restored values with
                # stale widget state, and close the window so the next
                # open() repopulates widgets from disk.
                self._cfg = self._store.load()
                self._toast(
                    self.tr("Söyle — Cloud Sync"),
                    self.tr(
                        "Настройки с другого устройства применены. "
                        "Открой Settings заново, чтобы увидеть значения."
                    ),
                )
                self.close()

    def _on_cloud_sync_sync_now(self) -> None:
        if self._cloud_sync is None:
            return
        runnable = AsyncRunnable(
            coro_factory=self._cloud_sync.sync_now,
            on_done=self._cs_sync_done.emit,
            on_error=lambda exc: self._cs_action_failed.emit(
                f"Sync error: {type(exc).__name__}",
            ),
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_sync_done(self, result: SyncResult) -> None:
        """Main-thread slot — refresh timestamp + toast on OK.

        SoyleApp's _handle_sync_outcome already covers AUTH_REVOKED / QUOTA /
        APP_SUSPENDED toasts at the app level. Here we own the
        Settings-tab-local update (timestamp + confirmation toast on OK)
        plus the dictionary-consumers refresh that the app-level handler
        would do for scheduled syncs.
        """
        self._cs_last_synced_label.setText(self._cloud_sync_last_synced_text())
        if result.outcome is SyncOutcome.OK:
            if result.added_local > 0 and self._on_dictionary_changed is not None:
                # Codex P1 on PR #19: without this, manual "Sync now" pulls
                # new terms but Transcriber/PostProcess keep the stale prompt
                # until next config reload/restart.
                self._on_dictionary_changed()
            self._toast(
                self.tr("Söyle"),
                self.tr("Sync OK. Локально +{local}, в Drive +{remote}.").format(
                    local=result.added_local,
                    remote=result.added_remote,
                ),
            )

    def _on_cloud_sync_disconnect(self) -> None:
        if self._cloud_sync is None:
            return
        runnable = AsyncRunnable(
            coro_factory=self._cloud_sync.disconnect,
            on_done=lambda _result: self._cs_disconnect_done.emit(),
            on_error=lambda exc: self._cs_action_failed.emit(
                f"Disconnect failed: {type(exc).__name__}",
            ),
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_disconnect_done(self) -> None:
        self._refresh_cloud_sync_buttons()
        self._cs_status_label.setText(self._cloud_sync_status_text())
        self._cs_last_synced_label.setText(self._cloud_sync_last_synced_text())
        self._toast(
            self.tr("Söyle — Cloud Sync"),
            self.tr("Отключено от Google Drive."),
        )

    def _on_action_failed(self, message: str) -> None:
        self._toast(self.tr("Söyle — Cloud Sync"), message, level="warning")

    def _toast(self, title: str, message: str, *, level: str = "info") -> None:
        """No-op when tray wasn't injected (e.g. standalone test instance)."""
        if self._tray is not None:
            self._tray.toast(title, message, level=level)

    # ---- First-run wizard helpers ----

    def focus_api_key_setup(self) -> None:
        """Jump to the LLM tab and put the cursor on the API-key field.

        Used by the first-run wizard in app.py to pull the user directly
        to the one setup step that actually matters on a clean install.
        """
        # Find the LLM tab by label rather than hardcoding the index so
        # reordering tabs doesn't silently send us to the wrong one.
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == "LLM":
                self._tabs.setCurrentIndex(i)
                break
        self._pp_api_key.setFocus()

    # ---- API key helpers ----

    def _toggle_key_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._pp_api_key.setEchoMode(mode)
        self._pp_show_key_btn.setText(
            self.tr("Скрыть") if checked else self.tr("Показать")
        )

    def _clear_api_key_clicked(self) -> None:
        if self._store.get_api_key() is None and not self._pp_api_key.text():
            # Nothing to clear — silently no-op rather than asking a
            # confirmation the user won't understand.
            return
        resp = QMessageBox.question(
            self,
            self.tr("Söyle"),
            self.tr(
                "Удалить сохранённый API-ключ из Windows Credential Manager?\n"
                "Постобработка вернётся к выводу сырых транскриптов, пока "
                "не задан новый ключ."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._store.clear_api_key()
        self._pp_api_key.clear()
        self._pp_api_key_original = ""
        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
        key = self._store.get_api_key()
        if key:
            tail = key[-4:] if len(key) >= 4 else "••••"
            head = key[:10] if len(key) >= 10 else key
            self._pp_key_status.setText(
                self.tr(
                    "✓ Ключ сохранён: {head}…{tail}"
                    "  ·  хранится в Windows Credential Manager"
                ).format(head=head, tail=tail)
            )
            self._pp_clear_key_btn.setEnabled(True)
        else:
            self._pp_key_status.setText(
                self.tr(
                    "✗ Ключ не задан — постобработка работает в fallback-режиме"
                )
            )
            self._pp_clear_key_btn.setEnabled(False)

    def _build_ui_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._ui_theme = QComboBox()
        self._ui_theme.addItems(["dark", "light", "system"])
        self._ui_theme.setCurrentText(self._cfg.ui.theme)
        layout.addRow(self.tr("Тема:"), self._ui_theme)

        self._ui_language = QComboBox()
        self._ui_language.addItem(self.tr("Системный"), "system")
        self._ui_language.addItem("Русский", "ru")
        self._ui_language.addItem("Қазақша", "kk")
        self._ui_language.addItem("English", "en")
        lang_idx = self._ui_language.findData(self._cfg.ui.language)
        self._ui_language.setCurrentIndex(max(0, lang_idx))
        layout.addRow(self.tr("Язык интерфейса:"), self._ui_language)
        # Remember the value at open time so _save can detect a change and
        # prompt for restart (language applies on next launch).
        self._ui_language_original = self._cfg.ui.language

        self._ui_sound = QCheckBox(self.tr("Звуковые сигналы"))
        self._ui_sound.setChecked(self._cfg.ui.sound_enabled)
        layout.addRow(self._ui_sound)
        self._ui_floating = QCheckBox(
            self.tr("Показать floating-кнопку для диктовки мышью")
        )
        self._ui_floating.setChecked(self._cfg.ui.show_floating_button)
        self._ui_floating.setToolTip(
            self.tr(
                "Круглая иконка микрофона в правом нижнем углу. "
                "Зажми и говори — альтернатива Right Alt."
            )
        )
        layout.addRow(self._ui_floating)
        self._beh_autostart = QCheckBox(self.tr("Запуск при старте Windows"))
        self._beh_autostart.setChecked(self._cfg.behavior.autostart)
        layout.addRow(self._beh_autostart)
        self._beh_inject = QComboBox()
        self._beh_inject.addItem(
            self.tr("Буфер обмена (быстрее, совместимо)"), "clipboard"
        )
        self._beh_inject.addItem(
            self.tr("Эмуляция клавиш (не трогает буфер)"), "keystroke"
        )
        idx = self._beh_inject.findData(self._cfg.behavior.inject_method)
        self._beh_inject.setCurrentIndex(max(0, idx))
        layout.addRow(self.tr("Метод вставки:"), self._beh_inject)

        self._beh_cost_limit = QDoubleSpinBox()
        self._beh_cost_limit.setDecimals(2)
        self._beh_cost_limit.setRange(0.0, 1000.0)
        self._beh_cost_limit.setSingleStep(0.5)
        self._beh_cost_limit.setSuffix(" $")
        self._beh_cost_limit.setValue(self._cfg.behavior.monthly_cost_limit_usd)
        self._beh_cost_limit.setToolTip(
            self.tr("Предупреждение в трее при превышении. 0 = выключено.")
        )
        layout.addRow(self.tr("Лимит в месяц:"), self._beh_cost_limit)
        return w

    def _build_dictionary_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(
            QLabel(
                self.tr(
                    "Термины из словаря подсказываются Whisper при распознавании "
                    "и LLM при полировке (имена, бренды, техническая лексика)."
                )
            )
        )

        self._dict_list = QListWidget()
        self._dict_list.addItems(self._dict_store.load())
        layout.addWidget(self._dict_list, 1)

        entry_row = QHBoxLayout()
        self._dict_input = QLineEdit()
        self._dict_input.setPlaceholderText("Söyle, OpenRouter, Nurgisa ...")
        entry_row.addWidget(self._dict_input, 1)
        btn_add = QPushButton(self.tr("Добавить"))
        btn_add.clicked.connect(self._dict_add_clicked)
        entry_row.addWidget(btn_add)
        self._dict_input.returnPressed.connect(self._dict_add_clicked)
        layout.addLayout(entry_row)

        button_row = QHBoxLayout()
        btn_remove = QPushButton(self.tr("Удалить выбранные"))
        btn_remove.clicked.connect(self._dict_remove_selected)
        button_row.addWidget(btn_remove)
        btn_clear = QPushButton(self.tr("Очистить всё"))
        btn_clear.clicked.connect(self._dict_clear_clicked)
        button_row.addWidget(btn_clear)
        button_row.addStretch()
        layout.addLayout(button_row)
        return w

    def _dict_add_clicked(self) -> None:
        term = self._dict_input.text().strip()
        if not term:
            return
        self._dict_store.add(term)
        self._refresh_dict_list()
        self._dict_input.clear()

    def _dict_remove_selected(self) -> None:
        items = self._dict_list.selectedItems()
        for item in items:
            self._dict_store.remove(item.text())
        self._refresh_dict_list()

    def _dict_clear_clicked(self) -> None:
        self._dict_store.clear()
        self._refresh_dict_list()

    def _refresh_dict_list(self) -> None:
        self._dict_list.clear()
        self._dict_list.addItems(self._dict_store.load())

    def _build_about_tab(self) -> QWidget:
        from soyle import __version__

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(f"Söyle v{__version__}"))
        layout.addWidget(
            QLabel(
                self.tr(
                    "Локальная диктовка через Whisper + OpenRouter для постобработки."
                )
            )
        )
        layout.addStretch()
        return w

    # ---- Helpers ----

    @staticmethod
    def _resolve_combo_model_id(combo: QComboBox) -> str:
        """Return model id: preset `data` if selected unchanged, else typed text.

        Preset items display as "<id>  ·  <metadata>". If the user typed a
        custom id, return the part before the first "  ·  ". Used by both
        the LLM model picker and the Whisper model picker — same shape.
        """
        idx = combo.currentIndex()
        if idx >= 0:
            data = combo.itemData(idx)
            if isinstance(data, str) and combo.itemText(idx) == combo.currentText():
                return data
        return combo.currentText().strip().split("  ·  ", 1)[0].strip()

    # ---- Save ----

    def _save(self) -> None:
        self._cfg.hotkey.combination = self._hk_combination.currentText().strip()
        self._cfg.hotkey.mode = self._hk_mode.currentText()  # type: ignore[assignment]
        self._cfg.hotkey.debounce_ms = self._hk_debounce.value()

        self._cfg.audio.device = self._audio_device.text().strip() or "default"
        self._cfg.audio.max_recording_seconds = self._audio_max.value()
        self._cfg.audio.vad_enabled = self._audio_vad.isChecked()
        self._cfg.audio.silence_threshold_rms = float(self._audio_threshold.value())

        self._cfg.whisper.model = self._resolve_combo_model_id(self._w_model)
        self._cfg.whisper.device = self._w_device.currentText()  # type: ignore[assignment]
        self._cfg.whisper.compute_type = self._w_compute.currentText()  # type: ignore[assignment]
        self._cfg.whisper.language = self._w_language.currentData()

        self._cfg.postprocess.enabled = self._pp_enabled.isChecked()
        self._cfg.postprocess.mode = self._pp_mode.currentData()
        self._cfg.postprocess.model = self._resolve_combo_model_id(self._pp_model)
        self._cfg.postprocess.timeout_seconds = self._pp_timeout.value()

        new_key = self._pp_api_key.text().strip()
        if new_key and new_key != self._pp_api_key_original:
            self._store.set_api_key(new_key)
            self._pp_api_key_original = new_key
            # Force show-toggle back off so the dialog doesn't leak the key
            # next time it's opened.
            if self._pp_show_key_btn.isChecked():
                self._pp_show_key_btn.setChecked(False)
            self._refresh_key_status()

        self._cfg.ui.theme = self._ui_theme.currentText()  # type: ignore[assignment]
        self._cfg.ui.language = self._ui_language.currentData()
        self._cfg.ui.sound_enabled = self._ui_sound.isChecked()
        self._cfg.ui.show_floating_button = self._ui_floating.isChecked()
        self._cfg.behavior.autostart = self._beh_autostart.isChecked()
        self._cfg.behavior.inject_method = self._beh_inject.currentData()
        self._cfg.behavior.monthly_cost_limit_usd = float(self._beh_cost_limit.value())

        self._store.save(self._cfg)
        self.settings_saved.emit()

        if self._cfg.ui.language != self._ui_language_original:
            self._ui_language_original = self._cfg.ui.language
            self._toast(
                self.tr("Söyle"),
                self.tr("Язык интерфейса изменится после перезапуска."),
            )
