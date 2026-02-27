"""Bria Dashboard panel for Houdini (API key setup)."""

from __future__ import annotations

import logging
from pathlib import Path

from bria_core.config import resolve_config_path
from bria_core.dashboard import (
    DASHBOARD_API_KEYS_URL,
    DASHBOARD_LOGIN_URL,
    clear_dashboard_tokens,
    has_any_dashboard_token,
    primary_token_key_for_dcc,
    read_dashboard_config,
    save_dashboard_tokens,
    token_fields_for_dcc,
)
from bria_core.status import get_status

logger = logging.getLogger(__name__)

# Try to import Qt - Houdini uses PySide2/PySide6
try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Qt
    except ImportError:
        QtWidgets = None
        QtCore = None
        QtGui = None
        Qt = None


class BriaDashboardPanel(QtWidgets.QWidget):
    """Dashboard panel for Bria API key setup in Houdini."""

    _TOKEN_FIELDS = token_fields_for_dcc("houdini")
    _PRIMARY_TOKEN_KEY = primary_token_key_for_dcc("houdini")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token_visible = False
        self._config_path: Path = resolve_config_path()
        self._token_inputs: dict[str, QtWidgets.QLineEdit] = {}
        self._token_show_buttons: dict[str, QtWidgets.QPushButton] = {}
        self._setup_ui()
        self._load_current_state()

    def _setup_ui(self):
        """Build the UI layout."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QtWidgets.QLabel("Bria Dashboard")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Status indicator
        self._status_frame = QtWidgets.QFrame()
        self._status_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        status_layout = QtWidgets.QHBoxLayout(self._status_frame)
        status_layout.setContentsMargins(12, 8, 12, 8)

        self._status_indicator = QtWidgets.QLabel()
        self._status_indicator.setFixedSize(12, 12)
        status_layout.addWidget(self._status_indicator)

        self._status_label = QtWidgets.QLabel("Checking...")
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()

        layout.addWidget(self._status_frame)

        # Config path display
        self._path_label = QtWidgets.QLabel(f"Config path: {self._config_path}")
        self._path_label.setStyleSheet("color: #888;")
        layout.addWidget(self._path_label)

        # Separator
        layout.addWidget(self._create_separator())

        # Access section
        access_group = QtWidgets.QGroupBox("Access")
        access_layout = QtWidgets.QHBoxLayout(access_group)

        login_btn = QtWidgets.QPushButton("Open Login")
        login_btn.clicked.connect(self._open_login_page)
        access_layout.addWidget(login_btn)

        keys_btn = QtWidgets.QPushButton("Open API Keys")
        keys_btn.clicked.connect(self._open_api_keys_page)
        access_layout.addWidget(keys_btn)

        access_layout.addStretch()
        layout.addWidget(access_group)

        # Health checks
        health_group = QtWidgets.QGroupBox("Health Checks")
        health_layout = QtWidgets.QHBoxLayout(health_group)

        check_cfg_btn = QtWidgets.QPushButton("Check Config")
        check_cfg_btn.clicked.connect(lambda: self._run_status_check(False))
        health_layout.addWidget(check_cfg_btn)

        check_net_btn = QtWidgets.QPushButton("Check Network")
        check_net_btn.clicked.connect(lambda: self._run_status_check(True))
        health_layout.addWidget(check_net_btn)

        health_layout.addStretch()
        layout.addWidget(health_group)

        # Token entry section
        token_group = QtWidgets.QGroupBox("API Tokens (Houdini)")
        token_layout = QtWidgets.QVBoxLayout(token_group)

        for label, key_name in self._TOKEN_FIELDS:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(f"API Token Type: {label}"))

            token_input = QtWidgets.QLineEdit()
            token_input.setPlaceholderText("Paste your Bria API key here...")
            token_input.setEchoMode(QtWidgets.QLineEdit.Password)
            token_input.textChanged.connect(self._on_token_changed)
            row.addWidget(token_input)

            show_btn = QtWidgets.QPushButton("Show")
            show_btn.setFixedWidth(60)
            show_btn.clicked.connect(lambda _=None, name=key_name: self._toggle_token_visibility(name))
            row.addWidget(show_btn)

            self._token_inputs[key_name] = token_input
            self._token_show_buttons[key_name] = show_btn

            token_layout.addLayout(row)

        # Action buttons
        btn_layout = QtWidgets.QHBoxLayout()

        self._save_btn = QtWidgets.QPushButton("Save All")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_tokens)
        btn_layout.addWidget(self._save_btn)

        self._clear_btn = QtWidgets.QPushButton("Clear All")
        self._clear_btn.clicked.connect(self._clear_credentials)
        btn_layout.addWidget(self._clear_btn)

        btn_layout.addStretch()

        token_layout.addLayout(btn_layout)

        layout.addWidget(token_group)

        # Info section
        info_frame = QtWidgets.QFrame()
        info_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        info_layout = QtWidgets.QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 8, 12, 8)

        info_text = QtWidgets.QLabel(
            "Paste your API keys from the Bria Console. "
            "Keys are written to your local bria.json file and never stored in scene files. "
            "Production is used by default; other keys are stored for manual use."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #888;")
        info_layout.addWidget(info_text)

        layout.addWidget(info_frame)

        # Stretch at bottom
        layout.addStretch()

        # Message area
        self._message_label = QtWidgets.QLabel()
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        layout.addWidget(self._message_label)

    def _create_separator(self) -> QtWidgets.QFrame:
        """Create a horizontal separator line."""
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    def _load_current_state(self):
        """Load current credential state."""
        try:
            data = read_dashboard_config(self._config_path)
            for _label, key_name in self._TOKEN_FIELDS:
                token = data.get(key_name)
                if token:
                    self._token_inputs[key_name].setText("*" * 32)
            primary = str(data.get(self._PRIMARY_TOKEN_KEY) or "").strip()
            has_any = has_any_dashboard_token(data, self._TOKEN_FIELDS)
            if primary:
                self._update_status("connected", "Configured")
            elif has_any:
                self._update_status("disconnected", "Aux keys only (prod missing)")
            else:
                self._update_status("disconnected", "Not configured")
        except Exception as e:
            logger.exception("Failed to load state")
            self._update_status("error", f"Error: {str(e)}")

    def _update_status(self, status: str, message: str):
        """Update the status indicator."""
        colors = {
            "connected": "#4caf50",  # Green
            "disconnected": "#ff9800",  # Orange
            "error": "#f44336",  # Red
        }

        color = colors.get(status, "#888")
        self._status_indicator.setStyleSheet(
            f"background-color: {color}; border-radius: 6px;"
        )
        self._status_label.setText(message)

    def _on_token_changed(self, text: str):
        """Handle token input changes."""
        # Enable save if any input has new text that's not the masked placeholder
        for token_input in self._token_inputs.values():
            val = token_input.text()
            if val and val != "*" * 32:
                self._save_btn.setEnabled(True)
                return
        self._save_btn.setEnabled(False)

    def _toggle_token_visibility(self, key_name: str):
        """Toggle token visibility."""
        token_input = self._token_inputs.get(key_name)
        show_btn = self._token_show_buttons.get(key_name)
        if token_input is None or show_btn is None:
            return

        showing = token_input.echoMode() == QtWidgets.QLineEdit.Normal
        if showing:
            token_input.setEchoMode(QtWidgets.QLineEdit.Password)
            show_btn.setText("Show")
        else:
            token_input.setEchoMode(QtWidgets.QLineEdit.Normal)
            show_btn.setText("Hide")

    def _save_tokens(self):
        """Save tokens to bria.json."""
        try:
            to_save: dict[str, str] = {}
            for _label, key_name in self._TOKEN_FIELDS:
                token_input = self._token_inputs.get(key_name)
                if token_input is None:
                    continue
                token = token_input.text()
                if not token or token == "*" * 32:
                    continue
                to_save[key_name] = token

            if not to_save:
                self._show_message("No changes to save", error=False)
                return

            save_dashboard_tokens(to_save, self._config_path)
            for key_name in to_save:
                token_input = self._token_inputs.get(key_name)
                if token_input is not None:
                    token_input.setText("*" * 32)

            self._load_current_state()
            self._show_message("Saved API keys to bria.json", error=False)
            self._save_btn.setEnabled(False)
        except Exception as e:
            self._update_status("error", "Save failed")
            self._show_message(str(e), error=True)

    def _clear_credentials(self):
        """Clear all stored credentials."""
        # Confirm
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear Credentials",
            "Are you sure you want to remove all stored Bria API credentials?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply != QtWidgets.QMessageBox.Yes:
            return

        try:
            clear_dashboard_tokens((key_name for _label, key_name in self._TOKEN_FIELDS), self._config_path)
            for token_input in self._token_inputs.values():
                token_input.clear()
            self._update_status("disconnected", "Not configured")
            self._show_message("Cleared API keys from bria.json", error=False)
        except Exception as e:
            self._show_message(str(e), error=True)

    def _open_login_page(self):
        """Open Bria login page."""
        self._open_url(DASHBOARD_LOGIN_URL)

    def _open_api_keys_page(self):
        """Open Bria API keys page."""
        self._open_url(DASHBOARD_API_KEYS_URL)

    def _open_url(self, url: str) -> None:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            self._show_message(f"Please visit {url}", error=False)

    def _show_message(self, message: str, error: bool = False):
        """Show a temporary message."""
        color = "#f44336" if error else "#4caf50"
        self._message_label.setStyleSheet(f"color: {color};")
        self._message_label.setText(message)
        self._message_label.show()

        # Auto-hide after 5 seconds
        QtCore.QTimer.singleShot(5000, self._message_label.hide)

    def _run_status_check(self, check_network: bool) -> None:
        try:
            status = get_status(dcc="houdini", check_network=check_network, timeout_s=3)
            if status.get("ok"):
                self._update_status("connected", "OK")
                self._show_message(f"OK | {status.get('resolved_endpoint')}", error=False)
            else:
                self._update_status("disconnected", "Warning")
                self._show_message(
                    f"{status.get('message')} ({status.get('reason')})",
                    error=True,
                )
        except Exception as exc:
            self._update_status("error", "Error")
            self._show_message(str(exc), error=True)

def createInterface():
    """
    Factory function called by Houdini to create the panel.

    Returns:
        QWidget instance for the Python Panel
    """
    if QtWidgets is None:
        raise ImportError("PySide2/PySide6 is required for the configuration panel")

    return BriaDashboardPanel()


def onActivateInterface():
    """Called when the panel is activated."""
    pass


def onDeactivateInterface():
    """Called when the panel is deactivated."""
    pass