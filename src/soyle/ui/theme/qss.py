"""Render a Qt stylesheet string from a Tokens instance."""
from __future__ import annotations

from soyle.ui.theme.tokens import Tokens


def render_qss(t: Tokens) -> str:
    """Build the application stylesheet from design tokens.

    The accent button is opt-in via ``objectName == "primary"`` so the
    redesign can promote one button per surface without restyling all.
    """
    return f"""
QWidget {{
    background-color: {t.bg_base};
    color: {t.text_primary};
    font-family: "{t.font_family}";
    font-size: {t.font_size_base}px;
}}
QPushButton {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    padding: 6px 14px;
    border-radius: {t.radius_sm}px;
}}
QPushButton:hover {{
    background-color: {t.bg_elevated};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{ background-color: {t.border_default}; }}
QPushButton#primary {{
    background-color: {t.accent};
    color: {t.accent_text};
    border: none;
}}
QPushButton#primary:hover {{ background-color: {t.accent_hover}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    padding: 4px;
    border-radius: {t.radius_sm}px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t.accent};
}}
QTabWidget::pane {{ border: 1px solid {t.border_default}; }}
QTabBar::tab {{
    padding: 6px 14px;
    background-color: {t.bg_surface};
    color: {t.text_secondary};
}}
QTabBar::tab:selected {{
    background-color: {t.bg_base};
    color: {t.text_primary};
    border-bottom: 2px solid {t.accent};
}}
QListWidget {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border_default};
    border-radius: {t.radius_sm}px;
}}
"""
