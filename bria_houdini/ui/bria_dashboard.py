"""Bria Dashboard panel for Houdini (API key setup)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from bria_houdini.bria_core.config import resolve_config_path
from bria_houdini.bria_core.dashboard import (
    DASHBOARD_API_KEYS_URL,
    DASHBOARD_LOGIN_URL,
    clear_dashboard_tokens,
    has_any_dashboard_token,
    primary_token_key_for_dcc,
    read_dashboard_config,
    save_dashboard_tokens,
    token_fields_for_dcc,
    write_dashboard_config,
)
from bria_houdini.bria_core.status import get_status

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
        # Outer layout holds the scroll area — allows the window to resize freely
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer_layout.addWidget(scroll)

        # Inner widget holds all the actual content
        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)

        layout = QtWidgets.QVBoxLayout(inner)
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
        token_group = QtWidgets.QGroupBox("API Key Setup")
        token_layout = QtWidgets.QVBoxLayout(token_group)

        # "Get API Key" button — prominent call-to-action
        get_key_btn = QtWidgets.QPushButton("Get API Key")
        get_key_btn.setStyleSheet(
            "QPushButton { background-color: #1976d2; color: white; padding: 8px 16px; "
            "font-weight: bold; border-radius: 4px; } "
            "QPushButton:hover { background-color: #1565c0; }"
        )
        get_key_btn.setToolTip("Open the Bria Console to create or copy your API key")
        get_key_btn.clicked.connect(self._open_api_keys_page)
        token_layout.addWidget(get_key_btn)

        # Primary token field (always visible)
        primary_label, primary_key = self._TOKEN_FIELDS[0]
        primary_row = QtWidgets.QHBoxLayout()
        primary_row.addWidget(QtWidgets.QLabel(f"{primary_label} API Key:"))

        primary_input = QtWidgets.QLineEdit()
        primary_input.setPlaceholderText("Paste your Bria API key here...")
        primary_input.setEchoMode(QtWidgets.QLineEdit.Password)
        primary_input.textChanged.connect(self._on_token_changed)
        primary_row.addWidget(primary_input)

        primary_show_btn = QtWidgets.QPushButton("Show")
        primary_show_btn.setFixedWidth(60)
        primary_show_btn.clicked.connect(lambda _=None, name=primary_key: self._toggle_token_visibility(name))
        primary_row.addWidget(primary_show_btn)

        self._token_inputs[primary_key] = primary_input
        self._token_show_buttons[primary_key] = primary_show_btn

        token_layout.addLayout(primary_row)

        # Install / Uninstall buttons
        btn_layout = QtWidgets.QHBoxLayout()

        self._save_btn = QtWidgets.QPushButton("Install")
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(
            "QPushButton { padding: 6px 16px; } "
            "QPushButton:enabled { background-color: #4caf50; color: white; font-weight: bold; border-radius: 4px; } "
            "QPushButton:enabled:hover { background-color: #43a047; }"
        )
        self._save_btn.clicked.connect(self._save_tokens)
        btn_layout.addWidget(self._save_btn)

        self._clear_btn = QtWidgets.QPushButton("Uninstall")
        self._clear_btn.clicked.connect(self._clear_credentials)
        btn_layout.addWidget(self._clear_btn)

        btn_layout.addStretch()

        token_layout.addLayout(btn_layout)

        # Additional keys toggle (collapsed by default)
        if len(self._TOKEN_FIELDS) > 1:
            self._extra_keys_toggle = QtWidgets.QPushButton("Show additional keys")
            self._extra_keys_toggle.setFlat(True)
            self._extra_keys_toggle.setStyleSheet("color: #888; text-decoration: underline;")
            self._extra_keys_toggle.clicked.connect(self._toggle_extra_keys)
            token_layout.addWidget(self._extra_keys_toggle)

            self._extra_keys_frame = QtWidgets.QFrame()
            extra_layout = QtWidgets.QVBoxLayout(self._extra_keys_frame)
            extra_layout.setContentsMargins(0, 0, 0, 0)

            for label, key_name in self._TOKEN_FIELDS[1:]:
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel(f"{label}:"))

                token_input = QtWidgets.QLineEdit()
                token_input.setPlaceholderText(f"Paste {label} key...")
                token_input.setEchoMode(QtWidgets.QLineEdit.Password)
                token_input.textChanged.connect(self._on_token_changed)
                row.addWidget(token_input)

                show_btn = QtWidgets.QPushButton("Show")
                show_btn.setFixedWidth(60)
                show_btn.clicked.connect(lambda _=None, name=key_name: self._toggle_token_visibility(name))
                row.addWidget(show_btn)

                self._token_inputs[key_name] = token_input
                self._token_show_buttons[key_name] = show_btn

                extra_layout.addLayout(row)

            self._extra_keys_frame.hide()
            token_layout.addWidget(self._extra_keys_frame)

        layout.addWidget(token_group)

        # Output directory section
        output_group = QtWidgets.QGroupBox("Output Directory")
        output_layout = QtWidgets.QVBoxLayout(output_group)

        self._use_output_dir = QtWidgets.QCheckBox("Use Output Directory")
        self._use_output_dir.setToolTip("Save results to a specific folder instead of the system temp directory")
        self._use_output_dir.toggled.connect(self._on_output_dir_toggled)
        output_layout.addWidget(self._use_output_dir)

        path_row = QtWidgets.QHBoxLayout()
        self._output_dir_input = QtWidgets.QLineEdit()
        self._output_dir_input.setPlaceholderText("Select a folder for Bria output images...")
        self._output_dir_input.setEnabled(False)
        path_row.addWidget(self._output_dir_input)

        self._browse_btn = QtWidgets.QPushButton("Browse")
        self._browse_btn.setFixedWidth(70)
        self._browse_btn.setEnabled(False)
        self._browse_btn.clicked.connect(self._browse_output_dir)
        path_row.addWidget(self._browse_btn)

        self._set_output_btn = QtWidgets.QPushButton("Set")
        self._set_output_btn.setFixedWidth(50)
        self._set_output_btn.setEnabled(False)
        self._set_output_btn.clicked.connect(self._set_output_dir)
        path_row.addWidget(self._set_output_btn)

        output_layout.addLayout(path_row)
        layout.addWidget(output_group)

        # Info section
        info_frame = QtWidgets.QFrame()
        info_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        info_layout = QtWidgets.QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 8, 12, 8)

        info_text = QtWidgets.QLabel(
            "Click 'Get API Key' to open the Bria Console, then paste your key and click Install. "
            "Keys are saved to your local bria.json file and never stored in scene files."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #888;")
        info_layout.addWidget(info_text)

        layout.addWidget(info_frame)

        # Message area (shown temporarily after actions)
        self._message_label = QtWidgets.QLabel()
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        layout.addWidget(self._message_label)

        # Stretch at bottom pushes content up
        layout.addStretch()

    def _create_separator(self) -> QtWidgets.QFrame:
        """Create a horizontal separator line."""
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    def _load_current_state(self):
        """Load current credential and output directory state."""
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

            # Load output directory state
            use_output = bool(data.get("use_bria_project_path"))
            self._use_output_dir.setChecked(use_output)
            output_dir = str(data.get("houdini_output_dir") or "").strip()
            if output_dir:
                self._output_dir_input.setText(output_dir)
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
        """Save tokens to bria.json and validate the configuration."""
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

            self._save_btn.setEnabled(False)

            # Validate config after install
            try:
                status = get_status(dcc="houdini", check_network=False, timeout_s=3)
                if status.get("ok"):
                    self._update_status("connected", "Installed")
                    self._show_message("API key installed successfully", error=False)
                else:
                    self._update_status("disconnected", "Saved (validation warning)")
                    self._show_message(
                        f"Key saved but: {status.get('message', 'check config')}",
                        error=True,
                    )
            except Exception:
                self._load_current_state()
                self._show_message("API key saved to bria.json", error=False)
        except Exception as e:
            self._update_status("error", "Install failed")
            self._show_message(str(e), error=True)

    def _clear_credentials(self):
        """Clear all stored credentials (uninstall)."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Uninstall API Keys",
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
            self._show_message("API keys removed from bria.json", error=False)
        except Exception as e:
            self._show_message(str(e), error=True)

    def _toggle_extra_keys(self):
        """Toggle visibility of additional (non-primary) token fields."""
        if self._extra_keys_frame.isVisible():
            self._extra_keys_frame.hide()
            self._extra_keys_toggle.setText("Show additional keys")
        else:
            self._extra_keys_frame.show()
            self._extra_keys_toggle.setText("Hide additional keys")

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

    def _on_output_dir_toggled(self, checked: bool):
        """Enable/disable output directory controls."""
        self._output_dir_input.setEnabled(checked)
        self._browse_btn.setEnabled(checked)
        self._set_output_btn.setEnabled(checked)

    def _browse_output_dir(self):
        """Open a folder browser for output directory."""
        start = self._output_dir_input.text().strip() or str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Output Directory", start
        )
        if folder:
            self._output_dir_input.setText(folder)

    def _set_output_dir(self):
        """Save the output directory setting to bria.json and apply to env."""
        try:
            data = read_dashboard_config(self._config_path)
            use_output = self._use_output_dir.isChecked()
            output_dir = self._output_dir_input.text().strip()

            data["use_bria_project_path"] = use_output
            if output_dir:
                data["houdini_output_dir"] = output_dir
            else:
                data.pop("houdini_output_dir", None)

            write_dashboard_config(data, self._config_path)

            # Apply to session env
            os.environ["USE_BRIA_PROJECT_PATH"] = "1" if use_output else "0"
            if use_output and output_dir:
                os.environ["BRIA_PROJECT_PATH"] = output_dir
            else:
                os.environ.pop("BRIA_PROJECT_PATH", None)

            self._show_message(
                f"Output directory {'set to: ' + output_dir if use_output and output_dir else 'using temp (default)'}",
                error=False,
            )
        except Exception as e:
            self._show_message(f"Failed to save output directory: {e}", error=True)

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