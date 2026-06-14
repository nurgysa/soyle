"""UI language resolution and QTranslator installation.

Source strings are Russian, so ``ru`` is the identity locale (no
translation file). Only ``kk`` and ``en`` ship ``.qm`` files.
"""
from __future__ import annotations

import structlog
from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from soyle.ui.resources import i18n_path

log = structlog.get_logger()

SUPPORTED = ("ru", "kk", "en")


def resolve_language(config_value: str, system_locale: QLocale | None = None) -> str:
    """Resolve a config language value to a concrete ``ru``/``kk``/``en``.

    Explicit values pass through. ``"system"`` maps the OS locale: Russian
    → ``ru``, Kazakh → ``kk``, anything else → ``en``.
    """
    if config_value in SUPPORTED:
        return config_value
    loc = system_locale if system_locale is not None else QLocale.system()
    lang = loc.language()
    if lang == QLocale.Language.Russian:
        return "ru"
    if lang == QLocale.Language.Kazakh:
        return "kk"
    return "en"


def install_translator(app: QApplication, language: str) -> QTranslator | None:
    """Install the ``.qm`` translator for ``language`` on ``app``.

    Returns the installed ``QTranslator`` (the caller must hold the
    reference — Qt drops translations if it is garbage-collected), or
    ``None`` for the ``ru`` identity locale / on load failure.
    """
    if language == "ru":
        return None
    qm = i18n_path(f"soyle_{language}.qm")
    translator = QTranslator(app)
    if not translator.load(str(qm)):
        log.warning("translation_file_missing", language=language, path=str(qm))
        return None
    app.installTranslator(translator)
    return translator
