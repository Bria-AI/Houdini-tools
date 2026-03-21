"""Bria Houdini Installer — PythonModule for the installer HDA.

This script is FULLY SELF-CONTAINED. It does not import from bria_core or
houdini.* because those paths are not configured yet — that is the job of
this installer.

Daniel: copy-paste this entire file into the installer HDA's PythonModule
section in the Type Properties editor.

HDA parm layout:
    Button   get_api_key   "Get API Key"    callback: hou.phm().open_api_keys(kwargs)
    String   api_key       "API Key"
    Button   install       "Install"        callback: hou.phm().install(kwargs)
    Button   uninstall     "Uninstall"      callback: hou.phm().uninstall(kwargs)
    Label    status        "Status"         (read-only)
"""

from __future__ import annotations

import json
import os
import platform
import sys
import webbrowser
from pathlib import Path

import hou

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIA_API_KEYS_URL = "https://platform.bria.ai/console/account/api-keys"
BRIA_CONFIG_DIR = Path("~/.bria").expanduser()
BRIA_CONFIG_FILE = BRIA_CONFIG_DIR / "bria.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_repo_root(node: hou.Node) -> Path:
    """Detect the bria-houdini repo root from the installer HDA's file path.

    The installer HDA lives at the repo root, so the parent directory of the
    HDA file IS the repo root.
    """
    hda_def = node.type().definition()
    if hda_def is None:
        raise RuntimeError("Cannot determine HDA file path (no definition found).")
    hda_path = hda_def.libraryFilePath()
    if not hda_path:
        raise RuntimeError("Cannot determine HDA file path.")
    repo_root = Path(hda_path).resolve().parent
    # Sanity check: the repo root should contain bria_houdini/ subdirectory
    if not (repo_root / "bria_houdini").is_dir():
        raise RuntimeError(
            f"Expected bria_houdini/ folder inside {repo_root}.\n"
            f"Make sure the installer HDA is at the root of the bria-houdini folder."
        )
    return repo_root


def _packages_dir() -> Path:
    """Return the Houdini packages directory for the current version."""
    home = Path(hou.homeHoudiniDirectory())
    pkg_dir = home / "packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    return pkg_dir


def _build_package_json(repo_root: Path) -> dict:
    """Build the package JSON with absolute paths pointing to *repo_root*.

    The shipped bria_houdini.json uses $HOUDINI_PACKAGE_PATH which only works
    when the JSON lives inside the repo.  When we copy it into Houdini prefs
    we must use the real absolute path instead.
    """
    root = str(repo_root)

    # Detect SSL cert path per platform
    ssl_cert = "/etc/ssl/cert.pem"  # macOS / most Linux
    if platform.system() == "Windows":
        ssl_cert = ""  # Windows handles certs differently

    pkg = {
        "version": "1.0",
        "name": "bria_houdini",
        "description": "Bria Houdini integration (HDAs + API adapter).",
        "env": [
            {
                "BRIA_HOUDINI_ROOT": {
                    "value": os.path.join(root, "bria_houdini", "houdini"),
                    "method": "replace",
                }
            },
            {
                "PYTHONPATH": {
                    "value": os.path.join(root, "bria_houdini"),
                    "method": "prepend",
                }
            },
            {
                "HOUDINI_OTLSCAN_PATH": {
                    "value": root
                            + ";" + os.path.join(root, "bria_houdini", "houdini", "hdas")
                            + ";" + os.path.join(root, "bria_houdini", "houdini", "hdas_legacy"),
                    "method": "prepend",
                }
            },
            {
                "HOUDINI_TOOLBAR_PATH": {
                    "value": os.path.join(root, "bria_houdini", "houdini", "toolbar"),
                    "method": "prepend",
                }
            },
            {
                "HOUDINI_PYTHON_PANEL_PATH": {
                    "value": os.path.join(
                        root, "bria_houdini", "houdini", "python_panels"
                    ),
                    "method": "prepend",
                }
            },
        ],
    }

    if ssl_cert:
        pkg["env"].append(
            {"SSL_CERT_FILE": {"value": ssl_cert, "method": "replace"}}
        )

    return pkg


def _set_status(node: hou.Node, text: str) -> None:
    """Update the status label parm on the installer node."""
    parm = node.parm("status")
    if parm is not None:
        parm.set(text)


# ---------------------------------------------------------------------------
# Public callbacks (wired to HDA buttons)
# ---------------------------------------------------------------------------

def open_api_keys(kwargs: dict) -> None:
    """Open the Bria API keys page in the default browser."""
    try:
        webbrowser.open(BRIA_API_KEYS_URL)
    except Exception as exc:
        hou.ui.displayMessage(
            f"Could not open browser.\n\nPlease visit:\n{BRIA_API_KEYS_URL}",
            severity=hou.severityType.Warning,
            title="Bria Installer",
        )


def install(kwargs: dict) -> None:
    """Install Bria tools: write package config + save API key."""
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")

    try:
        # 1. Detect repo root from HDA location
        repo_root = _get_repo_root(node)

        # 2. Read API key from parm
        api_key = (node.parm("api_key").eval() or "").split("#")[0].strip()
        if not api_key:
            hou.ui.displayMessage(
                "Please paste your API key first.\n\n"
                "Click 'Get API Key' to open the Bria console.",
                severity=hou.severityType.Error,
                title="Bria Installer",
            )
            _set_status(node, "Error: No API key provided")
            return

        # 3. Write package JSON to Houdini prefs
        pkg_data = _build_package_json(repo_root)
        pkg_path = _packages_dir() / "bria_houdini.json"
        pkg_path.write_text(json.dumps(pkg_data, indent=2), encoding="utf-8")

        # 4. Save API key to ~/.bria/bria.json
        BRIA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if BRIA_CONFIG_FILE.exists():
            try:
                config = json.loads(BRIA_CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                config = {}
        else:
            config = {}
        config["houdini_api_key"] = api_key
        BRIA_CONFIG_FILE.write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )

        # 5. Success — prompt to restart
        _set_status(node, "Installed! Restart Houdini to load tools.")
        choice = hou.ui.displayMessage(
            "Restart Houdini to finish installation.",
            buttons=("Restart Now", "Later"),
            severity=hou.severityType.Message,
            title="Bria AI Tools Installed!",
        )
        if choice == 0:  # Restart Now
            hou.exit()

    except Exception as exc:
        _set_status(node, f"Error: {exc}")
        hou.ui.displayMessage(
            f"Installation failed:\n\n{exc}",
            severity=hou.severityType.Error,
            title="Bria Installer",
        )


def uninstall(kwargs: dict) -> None:
    """Remove Bria package config and API key."""
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")

    confirm = hou.ui.displayMessage(
        "This will remove:\n\n"
        f"  Package config from Houdini prefs\n"
        f"  API key from {BRIA_CONFIG_FILE}\n\n"
        "Continue?",
        buttons=("Uninstall", "Cancel"),
        severity=hou.severityType.Warning,
        title="Bria Installer",
    )
    if confirm != 0:
        _set_status(node, "Uninstall cancelled.")
        return

    removed = []

    # Remove package JSON
    pkg_path = _packages_dir() / "bria_houdini.json"
    if pkg_path.exists():
        pkg_path.unlink()
        removed.append(str(pkg_path))

    # Remove config
    if BRIA_CONFIG_FILE.exists():
        BRIA_CONFIG_FILE.unlink()
        removed.append(str(BRIA_CONFIG_FILE))
    if BRIA_CONFIG_DIR.exists() and not any(BRIA_CONFIG_DIR.iterdir()):
        BRIA_CONFIG_DIR.rmdir()

    if removed:
        _set_status(node, "Uninstalled. Restart Houdini.")
        hou.ui.displayMessage(
            "Bria tools uninstalled.\n\n"
            "Removed:\n" + "\n".join(f"  {r}" for r in removed) + "\n\n"
            "Restart Houdini to complete removal.",
            severity=hou.severityType.Message,
            title="Bria Installer",
        )
    else:
        _set_status(node, "Nothing to uninstall.")
        hou.ui.displayMessage(
            "Nothing to uninstall — Bria tools were not installed.",
            severity=hou.severityType.Message,
            title="Bria Installer",
        )
