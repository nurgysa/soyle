"""Settings window with tabs: Hotkey, Audio, Whisper, PostProcess, UI, Dictionary, About."""
from __future__ import annotations

from PySide6.QtCore import Signal
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

from soyle.core.config import Config, ConfigStore
from soyle.core.dictionary import DictionaryStore
from soyle.core.postprocess import POPULAR_MODELS
from soyle.core.transcriber import WHISPER_MODELS
from soyle.ui.shortcut_capture import ShortcutCaptureDialog

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

    def __init__(
        self,
        store: ConfigStore,
        dictionary_store: DictionaryStore | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._dict_store = dictionary_store or DictionaryStore()
        self._cfg: Config = store.load()

        self.setWindowTitle("Söyle — настройки")
        self.resize(560, 440)

        central = QWidget()
        root = QVBoxLayout(central)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_hotkey_tab(), "Хоткей")
        self._tabs.addTab(self._build_audio_tab(), "Аудио")
        self._tabs.addTab(self._build_whisper_tab(), "Whisper")
        self._tabs.addTab(self._build_postprocess_tab(), "LLM")
        self._tabs.addTab(self._build_dictionary_tab(), "Словарь")
        self._tabs.addTab(self._build_ui_tab(), "Внешний вид")
        self._tabs.addTab(self._build_about_tab(), "О программе")
        root.addWidget(self._tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        btn_close = QPushButton("Закрыть")
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
        self._hk_capture_btn = QPushButton("Записать…")
        self._hk_capture_btn.setFixedWidth(100)
        self._hk_capture_btn.setToolTip("Нажать клавишу и распознать её автоматически")
        self._hk_capture_btn.clicked.connect(self._capture_hotkey_clicked)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self._hk_combination, 1)
        hotkey_row.addWidget(self._hk_capture_btn)
        layout.addRow("Клавиша:", hotkey_row)

        self._hk_mode = QComboBox()
        self._hk_mode.addItems(["push_to_talk", "toggle"])
        self._hk_mode.setCurrentText(self._cfg.hotkey.mode)
        layout.addRow("Режим:", self._hk_mode)
        self._hk_debounce = QSpinBox()
        self._hk_debounce.setRange(0, 1000)
        self._hk_debounce.setValue(self._cfg.hotkey.debounce_ms)
        layout.addRow("Debounce (мс):", self._hk_debounce)
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
        layout.addRow("Устройство:", self._audio_device)
        self._audio_max = QSpinBox()
        self._audio_max.setRange(1, 600)
        self._audio_max.setValue(self._cfg.audio.max_recording_seconds)
        layout.addRow("Макс. запись (сек):", self._audio_max)

        self._audio_vad = QCheckBox("Обрезать тишину в начале и конце записи")
        self._audio_vad.setChecked(self._cfg.audio.vad_enabled)
        self._audio_vad.setToolTip(
            "Удаляет тихие фреймы по краям записи. Помогает когда коллеги "
            "говорят рядом — их голос будет ниже порога и обрежется."
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
            "Порог RMS-энергии для определения тишины. "
            "Ниже = пропускает тихую/удалённую речь. "
            "Выше = только громкая близкая речь."
        )
        layout.addRow("Порог тишины (RMS):", self._audio_threshold)
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
        layout.addRow("Модель:", self._w_model)
        self._w_device = QComboBox()
        self._w_device.addItems(["auto", "cuda", "cpu"])
        self._w_device.setCurrentText(self._cfg.whisper.device)
        layout.addRow("Device:", self._w_device)
        self._w_compute = QComboBox()
        self._w_compute.addItems(["int8", "float16", "float32"])
        self._w_compute.setCurrentText(self._cfg.whisper.compute_type)
        layout.addRow("Compute type:", self._w_compute)

        # None = auto-detect (Whisper picks per utterance). Forcing a language
        # avoids cross-language mis-detections at the cost of failing on the
        # rare other-language utterance. Kazakh ("kk") is intentionally not
        # exposed here: faster-whisper checkpoints + CTranslate2 hang on
        # GTX 16-series GPUs (Turing without tensor cores) for KZ inference,
        # and CPU+small produces too many hallucinations to be useful.
        # Prompts and tests retain KZ rules so re-adding "kk" is one line.
        self._w_language = QComboBox()
        self._w_language.addItem("Авто (определять автоматически)", None)
        self._w_language.addItem("Русский", "ru")
        self._w_language.addItem("English", "en")
        idx = self._w_language.findData(self._cfg.whisper.language)
        self._w_language.setCurrentIndex(max(0, idx))
        layout.addRow("Язык:", self._w_language)
        return w

    def _build_postprocess_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._pp_enabled = QCheckBox("Включить постобработку LLM")
        self._pp_enabled.setChecked(self._cfg.postprocess.enabled)
        layout.addRow(self._pp_enabled)

        self._pp_mode = QComboBox()
        self._pp_mode.addItem("Polish — чистка, пунктуация, без переформулирования", "polish")
        self._pp_mode.addItem("Rewrite — активная переформулировка в связный текст", "rewrite")
        self._pp_mode.addItem("AI Prompt — превратить речь в инструкцию для Claude/ChatGPT/Gemini", "ai_prompt")
        self._pp_mode.addItem("Plain Text — текст для документа (Word, email, мессенджер)", "plain_text")
        idx = self._pp_mode.findData(self._cfg.postprocess.mode)
        self._pp_mode.setCurrentIndex(max(0, idx))
        layout.addRow("Режим:", self._pp_mode)

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
        layout.addRow("Модель:", self._pp_model)
        self._pp_timeout = QDoubleSpinBox()
        self._pp_timeout.setRange(1.0, 30.0)
        self._pp_timeout.setValue(self._cfg.postprocess.timeout_seconds)
        layout.addRow("Таймаут (сек):", self._pp_timeout)

        # Pre-populate from keyring so "Показать" reveals the stored key.
        # The stored value is kept as `_pp_api_key_original` so we can skip
        # redundant keyring writes on save (and know when the user actually
        # edited the field).
        existing_key = self._store.get_api_key() or ""
        self._pp_api_key_original = existing_key
        self._pp_api_key = QLineEdit(existing_key)
        self._pp_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._pp_api_key.setPlaceholderText("sk-or-v1-…")

        self._pp_show_key_btn = QPushButton("Показать")
        self._pp_show_key_btn.setCheckable(True)
        self._pp_show_key_btn.setFixedWidth(90)
        self._pp_show_key_btn.setToolTip("Временно сделать ключ видимым")
        self._pp_show_key_btn.toggled.connect(self._toggle_key_visibility)

        self._pp_clear_key_btn = QPushButton("Удалить")
        self._pp_clear_key_btn.setFixedWidth(90)
        self._pp_clear_key_btn.setToolTip(
            "Стереть сохранённый ключ из Windows Credential Manager"
        )
        self._pp_clear_key_btn.clicked.connect(self._clear_api_key_clicked)

        key_row = QHBoxLayout()
        key_row.addWidget(self._pp_api_key, 1)
        key_row.addWidget(self._pp_show_key_btn)
        key_row.addWidget(self._pp_clear_key_btn)
        layout.addRow("OpenRouter API key:", key_row)

        # Status line — shows whether a key is currently stored and a
        # masked preview so the user can tell "which" key is active.
        self._pp_key_status = QLabel()
        self._refresh_key_status()
        layout.addRow("", self._pp_key_status)
        return w

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
        self._pp_show_key_btn.setText("Скрыть" if checked else "Показать")

    def _clear_api_key_clicked(self) -> None:
        if self._store.get_api_key() is None and not self._pp_api_key.text():
            # Nothing to clear — silently no-op rather than asking a
            # confirmation the user won't understand.
            return
        resp = QMessageBox.question(
            self,
            "Söyle",
            "Удалить сохранённый API-ключ из Windows Credential Manager?\n"
            "Постобработка вернётся к выводу сырых транскриптов, пока "
            "не задан новый ключ.",
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
                f"✓ Ключ сохранён: {head}…{tail}  ·  хранится в Windows Credential Manager"
            )
            self._pp_clear_key_btn.setEnabled(True)
        else:
            self._pp_key_status.setText(
                "✗ Ключ не задан — постобработка работает в fallback-режиме"
            )
            self._pp_clear_key_btn.setEnabled(False)

    def _build_ui_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._ui_theme = QComboBox()
        self._ui_theme.addItems(["dark", "light", "system"])
        self._ui_theme.setCurrentText(self._cfg.ui.theme)
        layout.addRow("Тема:", self._ui_theme)
        self._ui_sound = QCheckBox("Звуковые сигналы")
        self._ui_sound.setChecked(self._cfg.ui.sound_enabled)
        layout.addRow(self._ui_sound)
        self._beh_autostart = QCheckBox("Запуск при старте Windows")
        self._beh_autostart.setChecked(self._cfg.behavior.autostart)
        layout.addRow(self._beh_autostart)
        self._beh_inject = QComboBox()
        self._beh_inject.addItem("Буфер обмена (быстрее, совместимо)", "clipboard")
        self._beh_inject.addItem("Эмуляция клавиш (не трогает буфер)", "keystroke")
        idx = self._beh_inject.findData(self._cfg.behavior.inject_method)
        self._beh_inject.setCurrentIndex(max(0, idx))
        layout.addRow("Метод вставки:", self._beh_inject)

        self._beh_cost_limit = QDoubleSpinBox()
        self._beh_cost_limit.setDecimals(2)
        self._beh_cost_limit.setRange(0.0, 1000.0)
        self._beh_cost_limit.setSingleStep(0.5)
        self._beh_cost_limit.setSuffix(" $")
        self._beh_cost_limit.setValue(self._cfg.behavior.monthly_cost_limit_usd)
        self._beh_cost_limit.setToolTip(
            "Предупреждение в трее при превышении. 0 = выключено."
        )
        layout.addRow("Лимит в месяц:", self._beh_cost_limit)
        return w

    def _build_dictionary_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(
            QLabel(
                "Термины из словаря подсказываются Whisper при распознавании "
                "и LLM при полировке (имена, бренды, техническая лексика)."
            )
        )

        self._dict_list = QListWidget()
        self._dict_list.addItems(self._dict_store.load())
        layout.addWidget(self._dict_list, 1)

        entry_row = QHBoxLayout()
        self._dict_input = QLineEdit()
        self._dict_input.setPlaceholderText("Söyle, OpenRouter, Nurgisa ...")
        entry_row.addWidget(self._dict_input, 1)
        btn_add = QPushButton("Добавить")
        btn_add.clicked.connect(self._dict_add_clicked)
        entry_row.addWidget(btn_add)
        self._dict_input.returnPressed.connect(self._dict_add_clicked)
        layout.addLayout(entry_row)

        button_row = QHBoxLayout()
        btn_remove = QPushButton("Удалить выбранные")
        btn_remove.clicked.connect(self._dict_remove_selected)
        button_row.addWidget(btn_remove)
        btn_clear = QPushButton("Очистить всё")
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
            QLabel("Локальная диктовка через Whisper + OpenRouter для постобработки.")
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
        self._cfg.postprocess.mode = self._pp_mode.currentData()  # type: ignore[assignment]
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
        self._cfg.ui.sound_enabled = self._ui_sound.isChecked()
        self._cfg.behavior.autostart = self._beh_autostart.isChecked()
        self._cfg.behavior.inject_method = self._beh_inject.currentData()  # type: ignore[assignment]
        self._cfg.behavior.monthly_cost_limit_usd = float(self._beh_cost_limit.value())

        self._store.save(self._cfg)
        self.settings_saved.emit()
