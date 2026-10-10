"""Shared visual tokens and persistent appearance preference for the MT5 UI.

Views should use the names in ``THEMES`` rather than embedding hex colors.
This module has no GUI or MT5 dependency, so it also works in packaged builds.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from mt5_workbench.config import state_directory


THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0B1220",
        "sidebar": "#111D30",
        "surface": "#17263B",
        "surface_alt": "#20334C",
        "border": "#32465F",
        "text": "#F2F6FC",
        "muted": "#A6B6CB",
        "accent": "#5AD5C1",
        "accent_alt": "#88B8FF",
        "positive": "#5AD5C1",
        "negative": "#FF8D9C",
        "warning": "#F6C777",
        "chart_grid": "#344A64",
        "chart_up": "#5AD5C1",
        "chart_down": "#FF8D9C",
        "selected": "#2A5062",
        "hover": "#29405A",
        "disabled": "#74869C",
        "on_accent": "#0B2430",
        "chart_line": "#88B8FF",
        "chart_fill": "#294965",
    },
    "light": {
        "bg": "#F3F6FA",
        "sidebar": "#FFFFFF",
        "surface": "#FFFFFF",
        "surface_alt": "#EAF0F7",
        "border": "#D4DFEB",
        "text": "#192A40",
        "muted": "#50657F",
        "accent": "#087F73",
        "accent_alt": "#295DA5",
        "positive": "#087F73",
        "negative": "#BA394F",
        "warning": "#9A5C0B",
        "chart_grid": "#D9E3EF",
        "chart_up": "#0A9D8D",
        "chart_down": "#D9576B",
        "selected": "#D9F2EC",
        "hover": "#E8EFF7",
        "disabled": "#7B8CA1",
        "on_accent": "#FFFFFF",
        "chart_line": "#295DA5",
        "chart_fill": "#D9EAF8",
    },
}

FONT_FAMILY = "Microsoft YaHei UI"
# Qt widgets use pixel sizes throughout.  Keeping the scale here prevents
# platform DPI settings from mixing point and pixel measurements in one view.
FONT_SIZES = {
    "caption": 13,
    "body": 14,
    "label": 14,
    "subtitle": 15,
    "section": 16,
    "page": 27,
    "metric": 23,
    "brand": 19,
}
SPACING = (4, 8, 12, 16, 24, 32, 40)
WINDOW_GUTTER = 12
SHELL_GAP = 8
MIN_WINDOW_SIZE = (1200, 800)
MAX_CONTENT_WIDTH = 1760


def theme_settings_path() -> Path:
    """Use the application's permanent per-user state directory."""
    return state_directory("ui_settings.json")


def system_theme() -> str:
    """Read the Windows app theme; use dark when the preference is unavailable."""
    if sys.platform != "win32":
        return "dark"
    try:
        import winreg

        key_name = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(light) else "dark"
    except (OSError, ValueError, TypeError):
        return "dark"


def load_theme() -> str:
    """Return a saved theme, falling back to the Windows app theme."""
    try:
        settings = json.loads(theme_settings_path().read_text(encoding="utf-8"))
        if isinstance(settings, dict) and settings.get("theme") in THEMES:
            return settings["theme"]
    except (OSError, ValueError, UnicodeError):
        pass
    return system_theme()


def save_theme(name: str) -> bool:
    """Persist a validated choice atomically; return False if storage fails.

    A failed write must never prevent the user from switching the current UI.
    """
    if name not in THEMES:
        raise ValueError(f"Unknown theme: {name!r}")
    path = theme_settings_path()
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".ui_settings-", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"theme": name}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def style_sheet(p: dict[str, str]) -> str:
    return f"""
    QWidget {{ background: {p['bg']}; color: {p['text']}; }}
    QLabel, QRadioButton {{ background: transparent; }}
    QMainWindow, QScrollArea, QStackedWidget {{ background: {p['bg']}; }}
    QFrame#sidebar, QFrame#header, QFrame#footer {{
        background: {p['sidebar']}; border: 1px solid {p['border']}; border-radius: 10px;
    }}
    QFrame#card {{ background: {p['surface']}; border: 1px solid {p['border']};
                    border-radius: 12px; }}
    QFrame#softCard {{ background: {p['surface_alt']}; border-radius: 10px; }}
    QLabel#muted {{ color: {p['muted']}; }}
    QLabel#positive {{ color: {p['accent']}; }}
    QLabel#warning {{ color: {p['warning']}; }}
    QLabel#danger {{ color: {p['negative']}; }}
    QLabel#pageTitle {{ font-size: {FONT_SIZES['page']}px; font-weight: 700; }}
    QLabel#sectionTitle {{ font-size: {FONT_SIZES['section']}px; font-weight: 700; }}
    QLabel#metricValue {{ font-size: {FONT_SIZES['metric']}px; font-weight: 700; }}
    QPushButton {{ background: {p['surface_alt']}; color: {p['text']};
                  border: 1px solid {p['border']}; border-radius: 9px;
                  padding: 9px 14px; min-height: 20px; font-weight: 700; }}
    QPushButton:hover {{ background: {p['hover']}; }}
    QPushButton:focus {{ border-color: {p['accent']}; }}
    QPushButton:disabled {{ color: {p['disabled']}; background: {p['surface_alt']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: {p['on_accent']};
                           border-color: {p['accent']}; }}
    QPushButton#primary:hover {{ background: {p['accent']}; border-color: {p['text']}; }}
    QPushButton#primary:disabled {{ color: {p['disabled']};
                                   background: {p['surface_alt']}; border-color: {p['border']}; }}
    QPushButton#danger {{ background: {p['negative']}; color: {p['bg']};
                          border-color: {p['negative']}; }}
    QPushButton#nav {{ background: transparent; border: 1px solid transparent;
                       border-radius: 9px; text-align: left; padding: 11px 13px;
                       min-height: 22px; font-size: {FONT_SIZES['body']}px; font-weight: 700; }}
    QPushButton#nav:hover {{ background: {p['hover']}; }}
    QPushButton#nav:checked {{ background: {p['selected']}; color: {p['accent']}; }}
    QLineEdit, QComboBox {{ background: {p['surface_alt']}; color: {p['text']};
                           border: 1px solid {p['border']}; border-radius: 8px;
                           padding: 8px 11px; min-height: 18px;
                           selection-background-color: {p['selected']}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
    QTableWidget {{ background: {p['surface']}; alternate-background-color: {p['surface_alt']};
                    gridline-color: {p['border']}; border: 0; selection-background-color: {p['selected']};
                    selection-color: {p['text']}; }}
    QTableWidget::item {{ padding: 7px 8px; border: 0; }}
    QHeaderView::section {{ background: {p['surface_alt']}; color: {p['muted']};
                            border: 0; border-bottom: 1px solid {p['border']};
                            padding: 9px 10px; font-size: {FONT_SIZES['caption']}px;
                            font-weight: 700; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 3px 1px; }}
    QScrollBar::handle:vertical {{ background: {p['border']}; min-height: 30px;
                                   border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 3px; }}
    QScrollBar::handle:horizontal {{ background: {p['border']}; min-width: 30px;
                                     border-radius: 4px; }}
    QScrollBar::handle:horizontal:hover {{ background: {p['muted']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QDialog {{ background: {p['bg']}; }}
    """
