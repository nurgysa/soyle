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
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from whisperflow.core.config import Config, ConfigStore
from whisperflow.core.dictionary import DictionaryStore
from whisperflow.core.postprocess import POPULAR_MODELS


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

        self.setWindowTitle("WhisperFlow — настройки")
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
        self._tabs.addTab(self._build_about_tab(), "О программе")  # noqa: RUF001
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
        self._hk_combination = QLineEdit(self._cfg.hotkey.combination)
        layout.addRow("Клавиша:", self._hk_combination)
        self._hk_mode = QComboBox()
        self._hk_mode.addItems(["push_to_talk", "toggle"])
        self._hk_mode.setCurrentText(self._cfg.hotkey.mode)
        layout.addRow("Режим:", self._hk_mode)
        self._hk_debounce = QSpinBox()
        self._hk_debounce.setRange(0, 1000)
        self._hk_debounce.setValue(self._cfg.hotkey.debounce_ms)
        layout.addRow("Debounce (мс):", self._hk_debounce)
        return w

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._audio_device = QLineEdit(self._cfg.audio.device)
        layout.addRow("Устройство:", self._audio_device)
        self._audio_max = QSpinBox()
        self._audio_max.setRange(1, 600)
        self._audio_max.setValue(self._cfg.audio.max_recording_seconds)
        layout.addRow("Макс. запись (сек):", self._audio_max)
        self._audio_vad = QCheckBox("VAD включён")
        self._audio_vad.setChecked(self._cfg.audio.vad_enabled)
        layout.addRow(self._audio_vad)
        return w

    def _build_whisper_tab(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self._w_model = QLineEdit(self._cfg.whisper.model)
        layout.addRow("Модель:", self._w_model)
        self._w_device = QComboBox()
        self._w_device.addItems(["auto", "cuda", "cpu"])
        self._w_device.setCurrentText(self._cfg.whisper.device)
        layout.addRow("Device:", self._w_device)
        self._w_compute = QComboBox()
        self._w_compute.addItems(["int8", "float16", "float32"])
        self._w_compute.setCurrentText(self._cfg.whisper.compute_type)
        layout.addRow("Compute type:", self._w_compute)
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

        self._pp_api_key = QLineEdit()
        self._pp_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        existing = self._store.get_api_key()
        if existing:
            self._pp_api_key.setPlaceholderText("••••••• (ключ сохранён)")
        layout.addRow("OpenRouter API key:", self._pp_api_key)
        return w

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
        self._dict_input.setPlaceholderText("WhisperFlow, OpenRouter, Nurgisa ...")
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
        from whisperflow import __version__

        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(f"WhisperFlow v{__version__}"))
        layout.addWidget(
            QLabel("Локальная диктовка через Whisper + OpenRouter для постобработки.")
        )
        layout.addStretch()
        return w

    # ---- Helpers ----

    def _resolve_model_id(self) -> str:
        """Return model id: preset `data` if selected unchanged, else typed text.

        Preset items display as "<id>  ·  <label>  ·  $in / $out per M". If
        the user typed a custom id, we return the part before the first "  ·  ".
        """
        idx = self._pp_model.currentIndex()
        if idx >= 0:
            data = self._pp_model.itemData(idx)
            if isinstance(data, str) and self._pp_model.itemText(idx) == self._pp_model.currentText():
                return data
        return self._pp_model.currentText().strip().split("  ·  ", 1)[0].strip()

    # ---- Save ----

    def _save(self) -> None:
        self._cfg.hotkey.combination = self._hk_combination.text().strip()
        self._cfg.hotkey.mode = self._hk_mode.currentText()  # type: ignore[assignment]
        self._cfg.hotkey.debounce_ms = self._hk_debounce.value()

        self._cfg.audio.device = self._audio_device.text().strip() or "default"
        self._cfg.audio.max_recording_seconds = self._audio_max.value()
        self._cfg.audio.vad_enabled = self._audio_vad.isChecked()

        self._cfg.whisper.model = self._w_model.text().strip()
        self._cfg.whisper.device = self._w_device.currentText()  # type: ignore[assignment]
        self._cfg.whisper.compute_type = self._w_compute.currentText()  # type: ignore[assignment]

        self._cfg.postprocess.enabled = self._pp_enabled.isChecked()
        self._cfg.postprocess.mode = self._pp_mode.currentData()  # type: ignore[assignment]
        self._cfg.postprocess.model = self._resolve_model_id()
        self._cfg.postprocess.timeout_seconds = self._pp_timeout.value()

        new_key = self._pp_api_key.text().strip()
        if new_key:
            self._store.set_api_key(new_key)
            self._pp_api_key.clear()
            self._pp_api_key.setPlaceholderText("••••••• (ключ сохранён)")

        self._cfg.ui.theme = self._ui_theme.currentText()  # type: ignore[assignment]
        self._cfg.ui.sound_enabled = self._ui_sound.isChecked()
        self._cfg.behavior.autostart = self._beh_autostart.isChecked()
        self._cfg.behavior.inject_method = self._beh_inject.currentData()  # type: ignore[assignment]

        self._store.save(self._cfg)
        self.settings_saved.emit()
