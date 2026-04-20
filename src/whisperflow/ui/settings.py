"""Settings window with tabs: Hotkey, Audio, Whisper, PostProcess, UI, About."""
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
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from whisperflow.core.config import Config, ConfigStore


class SettingsWindow(QMainWindow):
    """Tabbed settings editor; saves Config via ConfigStore."""

    settings_saved = Signal()

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self._store = store
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
        self._pp_model = QLineEdit(self._cfg.postprocess.model)
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
        return w

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
        self._cfg.postprocess.model = self._pp_model.text().strip()
        self._cfg.postprocess.timeout_seconds = self._pp_timeout.value()

        new_key = self._pp_api_key.text().strip()
        if new_key:
            self._store.set_api_key(new_key)
            self._pp_api_key.clear()
            self._pp_api_key.setPlaceholderText("••••••• (ключ сохранён)")

        self._cfg.ui.theme = self._ui_theme.currentText()  # type: ignore[assignment]
        self._cfg.ui.sound_enabled = self._ui_sound.isChecked()
        self._cfg.behavior.autostart = self._beh_autostart.isChecked()

        self._store.save(self._cfg)
        self.settings_saved.emit()
