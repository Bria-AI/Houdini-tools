"""Bria Installer HDA — PythonModule.

Self-contained installer logic embedded in the HDA. Does NOT import from
bria_houdini or bria_core (since those aren't available until after install).

Callbacks:
    hou.phm().open_api_keys(kwargs)
    hou.phm().install(kwargs)
    hou.phm().uninstall(kwargs)
"""

from __future__ import annotations

import json
import os
import shutil
import webbrowser
from pathlib import Path

try:
    import hou  # type: ignore
except ImportError:
    hou = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DASHBOARD_API_KEYS_URL = "https://platform.bria.ai/console/account/api-keys"
CONFIG_PATH = Path("~/.bria/bria.json").expanduser()
PACKAGE_NAME = "bria_houdini"
PACKAGE_JSON_NAME = "bria_houdini.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root_from_hda(kwargs):
    """Derive repo root from the installer HDA file location."""
    node = kwargs.get("node") or hou.pwd()
    hda_def = node.type().definition()
    if hda_def is None:
        return None
    hda_path = hda_def.libraryFilePath()
    if not hda_path:
        return None
    return os.path.dirname(os.path.abspath(hda_path))


def _houdini_packages_dir():
    """Return the Houdini user packages directory, creating it if needed."""
    prefs = hou.homeHoudiniDirectory()
    pkg_dir = os.path.join(prefs, "packages")
    os.makedirs(pkg_dir, exist_ok=True)
    return pkg_dir


def _set_status(kwargs, message):
    """Update the status parm on the installer node."""
    node = kwargs.get("node") or hou.pwd()
    try:
        node.parm("status").set(message)
    except Exception:
        pass


def _read_config():
    """Read ~/.bria/bria.json, returning empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_config(data):
    """Write ~/.bria/bria.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _install_otls(otls_dir):
    """Install all .hda files from the otls directory into the current session."""
    if not os.path.isdir(otls_dir):
        return 0
    count = 0
    for fname in sorted(os.listdir(otls_dir)):
        if fname.endswith(".hda") and not fname.startswith("."):
            hda_path = os.path.join(otls_dir, fname)
            try:
                hou.hda.installFile(hda_path)
                count += 1
            except Exception as exc:
                print(f"  Warning: could not install {fname}: {exc}")
    return count


# ---------------------------------------------------------------------------
# Public callbacks (referenced by HDA button parms)
# ---------------------------------------------------------------------------

def open_api_keys(kwargs):
    """Open the Bria API keys page in the default browser."""
    webbrowser.open(DASHBOARD_API_KEYS_URL)
    _set_status(kwargs, "Opened Bria API keys page in browser")


def install(kwargs):
    """Install Bria Houdini tools: save API key, write package, load OTLs."""
    node = kwargs.get("node") or hou.pwd()

    # 1. Validate API key
    api_key = node.parm("api_key").eval().strip()
    if not api_key:
        _set_status(kwargs, "Error: Please enter an API key first")
        hou.ui.displayMessage(
            "Please paste your Bria API key before clicking Install.",
            title="Bria Installer",
            severity=hou.severityType.Warning,
        )
        return

    # 2. Determine repo root from HDA location
    repo_root = _repo_root_from_hda(kwargs)
    if not repo_root:
        _set_status(kwargs, "Error: Could not determine install path from HDA")
        return

    bria_pkg_dir = os.path.join(repo_root, PACKAGE_NAME)
    otls_dir = os.path.join(bria_pkg_dir, "otls")

    if not os.path.isdir(bria_pkg_dir):
        _set_status(kwargs, f"Error: {PACKAGE_NAME}/ not found next to installer HDA")
        hou.ui.displayMessage(
            f"Expected '{PACKAGE_NAME}/' directory at:\n{repo_root}\n\n"
            "Make sure the installer HDA is at the repository root.",
            title="Bria Installer",
            severity=hou.severityType.Error,
        )
        return

    errors = []

    # 3. Save API key to ~/.bria/bria.json
    try:
        config = _read_config()
        config["houdini_api_key"] = api_key
        _write_config(config)
        print(f"[Bria Installer] Saved API key to {CONFIG_PATH}")
    except Exception as exc:
        errors.append(f"Config save failed: {exc}")

    # 4. Write Houdini package JSON
    try:
        pkg_dir = _houdini_packages_dir()
        pkg_json_path = os.path.join(pkg_dir, PACKAGE_JSON_NAME)

        package_data = {
            "version": "1.0",
            "name": PACKAGE_NAME,
            "description": "Bria Houdini integration (HDAs + API adapter).",
            "path": bria_pkg_dir,
            "env": [
                {
                    "PYTHONPATH": {
                        "value": repo_root,
                        "method": "prepend",
                    }
                },
                {
                    "HOUDINI_OTLSCAN_PATH": {
                        "value": otls_dir,
                        "method": "prepend",
                    }
                },
            ],
        }

        with open(pkg_json_path, "w", encoding="utf-8") as f:
            json.dump(package_data, f, indent=2)
        print(f"[Bria Installer] Wrote package to {pkg_json_path}")
    except Exception as exc:
        errors.append(f"Package write failed: {exc}")

    # 5. Install OTLs into current session
    try:
        count = _install_otls(otls_dir)
        print(f"[Bria Installer] Loaded {count} HDAs from {otls_dir}")
    except Exception as exc:
        errors.append(f"OTL install failed: {exc}")

    # 6. Report result
    if errors:
        msg = "Installed with warnings:\n" + "\n".join(errors)
        _set_status(kwargs, msg)
        hou.ui.displayMessage(msg, title="Bria Installer", severity=hou.severityType.Warning)
    else:
        msg = f"Installed successfully ({count} HDAs). Restart Houdini to complete setup."
        _set_status(kwargs, msg)
        hou.ui.displayMessage(
            "Bria tools installed successfully!\n\n"
            f"  - API key saved to {CONFIG_PATH}\n"
            f"  - Package written to {pkg_dir}/\n"
            f"  - {count} HDAs loaded into current session\n\n"
            "Restart Houdini for full integration (shelf tools, Python path).",
            title="Bria Installer",
            severity=hou.severityType.Message,
        )


def uninstall(kwargs):
    """Remove Bria package and API key."""
    confirm = hou.ui.displayMessage(
        "This will remove:\n"
        "  - Bria Houdini package from Houdini preferences\n"
        "  - API key from ~/.bria/bria.json\n\n"
        "Continue?",
        buttons=("Uninstall", "Cancel"),
        title="Bria Installer",
        severity=hou.severityType.Warning,
    )
    if confirm != 0:
        return

    removed = []

    # Remove package JSON
    try:
        pkg_dir = _houdini_packages_dir()
        pkg_json_path = os.path.join(pkg_dir, PACKAGE_JSON_NAME)
        if os.path.exists(pkg_json_path):
            os.remove(pkg_json_path)
            removed.append("package file")
            print(f"[Bria Installer] Removed {pkg_json_path}")
    except Exception as exc:
        print(f"[Bria Installer] Warning: could not remove package: {exc}")

    # Remove API key from config (keep other keys intact)
    try:
        config = _read_config()
        changed = False
        for key in ("houdini_api_key", "houdini_api_key_staging",
                     "houdini_api_key_comfyui", "houdini_api_key_mcp"):
            if key in config:
                del config[key]
                changed = True
        if changed:
            _write_config(config)
            removed.append("API key(s)")
            print(f"[Bria Installer] Removed Houdini keys from {CONFIG_PATH}")
    except Exception as exc:
        print(f"[Bria Installer] Warning: could not update config: {exc}")

    if removed:
        msg = f"Removed: {', '.join(removed)}. Restart Houdini to complete."
        _set_status(kwargs, msg)
        hou.ui.displayMessage(
            "Bria tools uninstalled.\n\n"
            "Restart Houdini to fully remove loaded HDAs.",
            title="Bria Installer",
            severity=hou.severityType.Message,
        )
    else:
        _set_status(kwargs, "Nothing to remove (not installed)")
