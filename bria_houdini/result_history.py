"""Result history scanning, diff-based labeling, and load-back for Bria HDAs.

Provides a "History" tab experience: artists can browse previous results
in a dynamic dropdown menu and restore any version with one click.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from datetime import datetime
from typing import Optional

try:
    import hou
except ImportError:
    hou = None

from bria_houdini.node_utils import apply_result_to_ui

# Maximum number of history entries to show in the dropdown.
_MAX_HISTORY = 20

# Image extensions we recognize as Bria results.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _result_dirs() -> list[str]:
    """Return candidate directories where Bria results may live."""
    dirs: list[str] = []

    # 1. Project output path (if configured)
    try:
        from bria_core.config import load_config

        cfg = load_config()
        if cfg.use_bria_project_path:
            output_dir = (cfg.houdini_output_dir or "").strip()
            if not output_dir:
                output_dir = os.environ.get("BRIA_PROJECT_PATH", "").strip()
            if output_dir and os.path.isdir(output_dir):
                dirs.append(output_dir)
    except Exception:
        pass

    # 2. System temp directory
    try:
        import tempfile

        tmp = tempfile.gettempdir()
        if tmp and os.path.isdir(tmp):
            dirs.append(tmp)
    except Exception:
        pass

    return dirs


def scan_results(node_type: str, output_dir: Optional[str] = None) -> list[dict]:
    """Scan for saved result images + metadata, newest first.

    Each entry dict has:
      - path: str          (absolute image path)
      - json_path: str     (companion JSON path, may not exist)
      - timestamp: float   (file mtime)
      - datetime: str      (formatted timestamp for display)
      - request: dict      (request params from metadata, or {})
      - node: str          (node type from metadata)
      - timing: dict       (timing info from metadata, or {})

    Args:
        node_type: e.g. "fibo_edit", "fibo_generate", "enhancer"
        output_dir: Explicit directory to scan. If None, scans default locations.
    """
    prefix = f"bria_{node_type}_result_"

    dirs_to_scan = [output_dir] if output_dir else _result_dirs()

    found: list[dict] = []
    seen_paths: set[str] = set()

    for d in dirs_to_scan:
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except Exception:
            continue

        for fname in entries:
            if not fname.startswith(prefix):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _IMAGE_EXTS:
                continue

            fpath = os.path.join(d, fname)
            if fpath in seen_paths:
                continue
            seen_paths.add(fpath)

            if not os.path.isfile(fpath):
                continue

            try:
                mtime = os.path.getmtime(fpath)
            except Exception:
                mtime = 0.0

            # Read companion JSON metadata
            base, _ = os.path.splitext(fpath)
            json_path = base + ".json"
            request = {}
            node_name = node_type
            timing = {}
            if os.path.isfile(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    request = meta.get("request", {}) or {}
                    node_name = meta.get("node", node_type)
                    timing = meta.get("timing", {}) or {}
                except Exception:
                    pass

            dt_str = datetime.fromtimestamp(mtime).strftime("%m/%d %H:%M")

            found.append({
                "path": fpath,
                "json_path": json_path,
                "timestamp": mtime,
                "datetime": dt_str,
                "request": request,
                "node": node_name,
                "timing": timing,
            })

    # Sort newest first
    found.sort(key=lambda e: e["timestamp"], reverse=True)

    return found[:_MAX_HISTORY]


# ---------------------------------------------------------------------------
# Diff-based labeling
# ---------------------------------------------------------------------------


def _truncate(text: str, max_words: int = 4) -> str:
    """Truncate to ~max_words words with ellipsis."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _extract_struct_label(struct_str: str) -> str:
    """Extract a clean label from a structured prompt JSON string.

    Tries to parse and pull out ``short_description`` or the first
    meaningful string value.  Falls back to a cleaned-up text snippet
    rather than exposing raw JSON syntax.
    """
    try:
        d = json.loads(struct_str) if isinstance(struct_str, str) else struct_str
        if isinstance(d, dict):
            for k in ("short_description", "prompt", "description", "scene", "subject"):
                val = d.get(k)
                if val and isinstance(val, str):
                    return _truncate(val)
            # First string value as last resort
            for val in d.values():
                if isinstance(val, str) and val.strip():
                    return _truncate(val)
    except Exception:
        pass
    # Strip JSON braces/quotes so it doesn't look like raw code
    clean = struct_str.strip().lstrip("{").strip().rstrip("}").strip()
    return _truncate(clean[:80])


def _diff_text(old: str, new: str) -> str:
    """Find the localized change between two prompt strings.

    Returns:
      - "'old fragment' -> 'new fragment'" if change is localized
      - truncated new prompt if entirely different
    """
    if not old or not new:
        return _truncate(new or old or "")

    old_words = old.split()
    new_words = new.split()

    # Find common prefix length
    prefix_len = 0
    for i in range(min(len(old_words), len(new_words))):
        if old_words[i] == new_words[i]:
            prefix_len = i + 1
        else:
            break

    # Find common suffix length
    suffix_len = 0
    for i in range(1, min(len(old_words), len(new_words)) + 1):
        if old_words[-i] == new_words[-i]:
            suffix_len = i
        else:
            break

    # If less than 30% of words are shared, treat as entirely different
    shared = prefix_len + suffix_len
    total = max(len(old_words), len(new_words))
    if total > 0 and shared / total < 0.3:
        return _truncate(new)

    # Extract changed portions
    old_end = len(old_words) - suffix_len if suffix_len > 0 else len(old_words)
    new_end = len(new_words) - suffix_len if suffix_len > 0 else len(new_words)

    old_changed = " ".join(old_words[prefix_len:old_end])
    new_changed = " ".join(new_words[prefix_len:new_end])

    if not old_changed and not new_changed:
        return _truncate(new)

    old_snippet = _truncate(old_changed, 3)
    new_snippet = _truncate(new_changed, 3)

    return f"'{old_snippet}' \u2192 '{new_snippet}'"


def _leaf_changes(old_val, new_val, prefix: str = "") -> list[tuple]:
    """Recursively find leaf-level text changes between two values.

    Returns list of (dotted_path, old_text, new_text) tuples.
    Recurses into dicts and lists-of-dicts so we never stringify containers.
    """
    if old_val == new_val:
        return []

    # Both dicts — recurse into sub-keys
    if isinstance(old_val, dict) and isinstance(new_val, dict):
        changes: list[tuple] = []
        all_keys = set(list(old_val.keys()) + list(new_val.keys()))
        for key in all_keys:
            sub = f"{prefix}.{key}" if prefix else key
            changes.extend(_leaf_changes(old_val.get(key), new_val.get(key), sub))
        return changes

    # Both lists — compare first differing element (handles VGL "objects")
    if isinstance(old_val, list) and isinstance(new_val, list):
        if (old_val and new_val
                and isinstance(old_val[0], dict) and isinstance(new_val[0], dict)):
            for i in range(min(len(old_val), len(new_val))):
                if old_val[i] != new_val[i]:
                    return _leaf_changes(old_val[i], new_val[i], prefix)
        # Length change or non-dict elements
        return [(prefix, f"{len(old_val)} items", f"{len(new_val)} items")]

    # Leaf value — return raw strings for the formatter to handle
    old_s = str(old_val) if old_val is not None else ""
    new_s = str(new_val) if new_val is not None else ""
    return [(prefix, old_s, new_s)]


# Map JSON leaf-key names to user-friendly labels for the dropdown.
_FRIENDLY_NAMES: dict[str, str] = {
    "background_setting": "background",
    "conditions": "lighting",
    "direction": "light direction",
    "shadows": "shadows",
    "color_scheme": "colors",
    "composition": "composition",
    "mood_atmosphere": "mood",
    "camera_angle": "camera",
    "depth_of_field": "depth of field",
    "focus": "focus",
    "lens_focal_length": "lens",
    "style_medium": "style",
    "artistic_style": "art style",
    "context": "context",
    "description": "subject",
    "location": "position",
    "orientation": "orientation",
    "texture": "texture",
    "appearance_details": "details",
    "relative_size": "size",
    "shape_and_color": "shape/color",
    "relationship": "relationship",
}

# Priority order for choosing which single change to display.
_FIELD_PRIORITY = [
    "background_setting", "description",
    "conditions", "direction", "shadows",
    "color_scheme", "composition", "mood_atmosphere",
    "camera_angle", "depth_of_field", "focus", "lens_focal_length",
    "style_medium", "artistic_style", "context",
    "location", "orientation", "texture", "appearance_details",
    "relative_size", "shape_and_color", "relationship",
]


def _diff_structured(old_json: str, new_json: str) -> str:
    """Diff two structured prompt JSON strings.

    Strategy:
      1. Compare ``short_description`` directly — if it changed, show
         a localized word-diff (no field-name prefix).
      2. Otherwise find the single most meaningful leaf change and show
         it with a human-friendly label (e.g. ``lighting: 'golden hour'
         -> 'moonlit night'``).  Never exposes raw JSON paths.
    """
    try:
        old_dict = json.loads(old_json) if isinstance(old_json, str) else old_json
        new_dict = json.loads(new_json) if isinstance(new_json, str) else new_json
    except (json.JSONDecodeError, TypeError):
        return _truncate(str(new_json)[:80] if new_json else "")

    if not isinstance(old_dict, dict) or not isinstance(new_dict, dict):
        return _truncate(str(new_json)[:80] if new_json else "")

    # --- Strategy 1: short_description changed → show text diff ----------
    old_desc = ""
    new_desc = ""
    if isinstance(old_dict.get("short_description"), str):
        old_desc = old_dict["short_description"]
    if isinstance(new_dict.get("short_description"), str):
        new_desc = new_dict["short_description"]

    if old_desc and new_desc and old_desc != new_desc:
        return _diff_text(old_desc, new_desc)

    # --- Strategy 2: find best single leaf change -----------------------
    raw = _leaf_changes(old_dict, new_dict)
    if not raw:
        return "(no change)"

    # Sort by field priority (most interesting first)
    def _priority(item):
        leaf = item[0].rsplit(".", 1)[-1]
        if leaf == "short_description":
            return 999  # already handled above
        try:
            return _FIELD_PRIORITY.index(leaf)
        except ValueError:
            return len(_FIELD_PRIORITY)

    raw.sort(key=_priority)

    # Pick the first meaningful change
    for path, old_s, new_s in raw:
        leaf = path.rsplit(".", 1)[-1]
        if leaf in ("short_description", "preference_score", "aesthetic_score"):
            continue  # skip meta-fields
        friendly = _FRIENDLY_NAMES.get(leaf, leaf.replace("_", " "))

        if not old_s and new_s:
            return f"+{friendly}: {_truncate(new_s, 5)}"
        if old_s and not new_s:
            return f"-{friendly}"
        # For long text values, use localized word-diff
        if len(old_s.split()) > 5 and len(new_s.split()) > 5:
            diff = _diff_text(old_s, new_s)
            return f"{friendly}: {diff}"
        return f"{friendly}: '{_truncate(old_s, 4)}' \u2192 '{_truncate(new_s, 4)}'"

    # Everything was short_description or meta — show new description
    if new_desc:
        return _truncate(new_desc, 5)
    return "(updated)"


def _fallback_label(entry: dict, index: int = 0) -> str:
    """Generate a label when no request params are available (pre-existing results)."""
    timing = entry.get("timing", {})
    total = timing.get("total_time")
    num = index + 1
    if total is not None:
        return f"result #{num} ({total:.1f}s)"
    return f"result #{num}"


def diff_label(current: dict, previous: Optional[dict], index: int = 0) -> str:
    """Build a human-readable diff label for a history entry.

    Args:
        current: Result entry dict from scan_results()
        previous: Previous result entry (chronologically older), or None for first
        index: Position in the results list (0 = newest), used for fallback numbering
    """
    cur_req = current.get("request", {}) or {}
    cur_prompt = cur_req.get("prompt") or ""
    cur_struct = cur_req.get("structured_prompt") or ""

    if previous is None:
        # First result — just show prompt snippet
        if cur_prompt:
            return _truncate(cur_prompt)
        if cur_struct:
            return _extract_struct_label(cur_struct)
        # No request params (pre-existing result) — show numbered label
        return _fallback_label(current, index)

    prev_req = previous.get("request", {}) or {}
    prev_prompt = prev_req.get("prompt") or ""
    prev_struct = prev_req.get("structured_prompt") or ""

    # Compare structured prompts if both present
    if cur_struct and prev_struct:
        label = _diff_structured(prev_struct, cur_struct)
        if label and label != "(no change)":
            return label

    # Compare text prompts
    if cur_prompt and prev_prompt:
        if cur_prompt != prev_prompt:
            return _diff_text(prev_prompt, cur_prompt)

    # Mixed: one has struct, other doesn't
    if cur_prompt and not prev_prompt:
        return _truncate(cur_prompt)
    if cur_struct and not prev_struct:
        return _extract_struct_label(cur_struct)

    # Same prompt — check other params
    for key in ("preset", "seed", "steps_num", "guidance_scale", "resolution",
                "desired_increase", "aspect_ratio"):
        cur_val = cur_req.get(key)
        prev_val = prev_req.get(key)
        if cur_val != prev_val and cur_val is not None:
            return f"{key}: {prev_val} \u2192 {cur_val}"

    # No detectable change — show prompt snippet
    if cur_prompt:
        return _truncate(cur_prompt)
    return _fallback_label(current, index)


# ---------------------------------------------------------------------------
# Houdini menu / button callbacks
# ---------------------------------------------------------------------------


def _node_type_from_cop(cop_node) -> str:
    """Infer the node_type string from the HDA's type name."""
    if cop_node is None:
        return "unknown"
    try:
        type_name = cop_node.type().name()
    except Exception:
        return "unknown"

    # Map HDA type names to result file prefixes.
    # Sorted longest-first to avoid substring collisions
    # (e.g. "bria_fibo_edit" matching inside "bria_fibo_edit_presets").
    mapping = [
        ("bria_fibo_edit_presets", "fibo_edit_presets"),
        ("bria_generate_structured_prompt", "generate_structured_prompt"),
        ("bria_fibo_generate", "generate_image"),
        ("bria_generate_image", "generate_image"),
        ("bria_fibo_edit", "fibo_edit"),
        ("bria_enhancer", "enhancer"),
        ("bria_upscale", "upscale"),
        ("bria_restyle", "restyle"),
        ("bria_genfill", "genfill"),
        ("bria_expand", "expand"),
        ("bria_rmbg", "rmbg"),
        ("bria_erase", "erase"),
    ]

    type_lower = type_name.lower()
    for key, val in mapping:
        if key in type_lower:
            return val

    return type_name.split("::")[-1] if "::" in type_name else type_name


def build_history_menu(kwargs: dict) -> list[str]:
    """Return flat [token, label, ...] list for Houdini dynamic menu script.

    Called from HDA parm menu script callback.
    """
    node = kwargs.get("node")
    if node is None:
        return ["", "(no node)"]

    node_type = _node_type_from_cop(node)
    results = scan_results(node_type)

    if not results:
        return ["", "(no results yet)"]

    items: list[str] = []
    for i, entry in enumerate(results):
        # Compare against next entry (chronologically older = next in sorted list)
        prev = results[i + 1] if i + 1 < len(results) else None
        label = diff_label(entry, prev, index=i)
        dt = entry["datetime"]

        if i == 0:
            display = f"Latest ({dt}) \u2014 {label}"
        else:
            display = f"{dt} \u2014 {label}"

        # Token is the file path
        items.append(entry["path"])
        items.append(display)

    # Update result count label if present
    try:
        count_parm = node.parm("result_count")
        if count_parm is not None:
            total = len(results)
            suffix = "+" if total >= _MAX_HISTORY else ""
            count_parm.set(f"{total}{suffix} results")
    except Exception:
        pass

    return items


def on_load_result(kwargs: dict) -> None:
    """Load the selected historical result into the node's viewer.

    Called from HDA button callback.
    """
    node = kwargs.get("node")
    if node is None:
        return

    parm = node.parm("result_history")
    if parm is None:
        return

    result_path = parm.eval()
    if not result_path or not os.path.isfile(result_path):
        if hou is not None:
            hou.ui.displayMessage(
                "Select a result from the History dropdown first.",
                severity=hou.severityType.Warning,
                title="Bria History",
            )
        return

    apply_result_to_ui(
        node,
        result_path,
        f"Loaded historical result: {os.path.basename(result_path)}",
    )


def on_open_result_folder(kwargs: dict) -> None:
    """Open the result directory in Finder (macOS) or Explorer (Windows).

    Called from HDA button callback.
    """
    node = kwargs.get("node")
    if node is None:
        return

    # Try to get path from selected result, fall back to result_path parm
    folder = None
    parm = node.parm("result_history")
    if parm is not None:
        val = parm.eval()
        if val and os.path.isfile(val):
            folder = os.path.dirname(val)

    if not folder:
        rp = node.parm("result_path")
        if rp is not None:
            val = rp.eval()
            if val and os.path.exists(val):
                folder = os.path.dirname(val) if os.path.isfile(val) else val

    if not folder or not os.path.isdir(folder):
        if hou is not None:
            hou.ui.displayMessage(
                "No result folder found. Generate a result first.",
                severity=hou.severityType.Warning,
                title="Bria History",
            )
        return

    try:
        from bria_core.utils import open_in_os
        open_in_os(folder)
    except Exception as exc:
        if hou is not None:
            hou.ui.displayMessage(
                f"Could not open folder: {repr(exc)}",
                severity=hou.severityType.Error,
                title="Bria History",
            )
