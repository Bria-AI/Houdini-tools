"""VGL (Visual GenAI Language) structured prompt utilities.

Parse VGL JSON into category sections for editing, and reassemble
edited categories back into a full VGL JSON for the API.

Both FIBO Generate and FIBO Edit Presets import these functions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Category-level schema (used by build script and old per-category path)
# ---------------------------------------------------------------------------

# Map VGL top-level keys -> (parm_suffix, display_label).
# Order defines the display order in the HDA parameter UI.
VGL_CATEGORIES: List[Tuple[str, str, str]] = [
    # (json_key,                     parm_suffix,  label)
    ("background_setting",           "scene",      "Scene & Background"),
    ("objects",                      "objects",     "Subjects"),
    ("lighting",                     "lighting",    "Lighting"),
    ("aesthetics",                   "aesthetics",  "Aesthetics"),
    ("photographic_characteristics", "photo",       "Photographic"),
    ("style_medium",                 "style",       "Style"),
    ("text_render",                  "text",        "Text Overlays"),
]

# Build fast lookup: json_key -> parm_suffix
_KEY_TO_SUFFIX: Dict[str, str] = {k: s for k, s, _ in VGL_CATEGORIES}

# Metadata keys extracted separately (not editable categories)
VGL_META_KEYS = {"short_description"}

# All parm suffixes including "other" catch-all
VGL_ALL_SUFFIXES = [s for _, s, _ in VGL_CATEGORIES] + ["other"]

# ---------------------------------------------------------------------------
# Field-level schema (used by v2 structured parm UI)
# ---------------------------------------------------------------------------

# Object fields: (json_key, parm_suffix, label, is_person_field, field_type)
VGL_OBJECT_FIELDS: List[Tuple[str, str, str, bool, str]] = [
    ("description",           "desc",     "Description",   False, "str"),
    ("location",              "loc",      "Location",      False, "str"),
    ("shape_and_color",       "shape",    "Shape & Color", False, "str"),
    ("relative_size",         "relsize",  "Relative Size", False, "str"),
    ("appearance_details",    "appear",   "Appearance",    False, "str"),
    ("texture",               "tex",      "Texture",       False, "str"),
    ("orientation",           "orient",   "Orientation",   False, "str"),
    ("relationship",          "rel",      "Relationship",  False, "str"),
    ("number_of_objects",     "numobj",   "Count",         False, "int"),
    # Person-specific (collapsed by default in UI)
    ("action",                "action",   "Action",        True,  "str"),
    ("pose",                  "pose",     "Pose",          True,  "str"),
    ("gender",                "gender",   "Gender",        True,  "str"),
    ("expression",            "expr",     "Expression",    True,  "str"),
    ("clothing",              "clothing", "Clothing",      True,  "str"),
    ("skin_tone_and_texture", "skin",     "Skin Tone",     True,  "str"),
]

# Sub-fields for structured categories: (json_key, parm_suffix, label)
VGL_LIGHTING_FIELDS: List[Tuple[str, str, str]] = [
    ("conditions", "cond",    "Conditions"),
    ("direction",  "dir",     "Direction"),
    ("shadows",    "shadows", "Shadows"),
]

VGL_AESTHETICS_FIELDS: List[Tuple[str, str, str]] = [
    ("color_scheme",    "colorscheme", "Color Scheme"),
    ("composition",     "comp",        "Composition"),
    ("mood_atmosphere", "mood",        "Mood & Atmosphere"),
]

VGL_PHOTO_FIELDS: List[Tuple[str, str, str]] = [
    ("camera_angle",      "camangle", "Camera Angle"),
    ("depth_of_field",    "dof",      "Depth of Field"),
    ("focus",             "focus",    "Focus"),
    ("lens_focal_length", "lens",     "Lens / Focal Length"),
]

# Map category parm prefix -> sub-field list (for categories with sub-fields)
VGL_CATEGORY_SUBFIELDS: Dict[str, List[Tuple[str, str, str]]] = {
    "lighting":   VGL_LIGHTING_FIELDS,
    "aesthetics": VGL_AESTHETICS_FIELDS,
    "photo":      VGL_PHOTO_FIELDS,
}

# Known object json keys (for detecting extras)
_KNOWN_OBJECT_KEYS = {jk for jk, _, _, _, _ in VGL_OBJECT_FIELDS}

# ---------------------------------------------------------------------------
# Per-category parse/assemble (v1 — kept for raw JSON path)
# ---------------------------------------------------------------------------


def parse_categories(vgl_json: str) -> Dict[str, str]:
    """Parse full VGL JSON into per-category JSON strings.

    Returns dict mapping parm_suffix -> formatted JSON string for that section.
    Keys not in VGL_CATEGORIES or VGL_META_KEYS go into "other".
    """
    try:
        data = json.loads(vgl_json)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, str] = {}
    other: Dict[str, object] = {}

    for key, value in data.items():
        if key in VGL_META_KEYS:
            continue
        suffix = _KEY_TO_SUFFIX.get(key)
        if suffix is not None:
            result[suffix] = json.dumps(value, indent=2, default=str)
        else:
            other[key] = value

    if other:
        result["other"] = json.dumps(other, indent=2, default=str)

    return result


def assemble_categories(category_parms: Dict[str, str],
                        short_description: str = "") -> str:
    """Reassemble category JSON strings into full VGL JSON.

    *category_parms* maps parm_suffix -> JSON string for that category.
    Returns the formatted full JSON string ready for the API.
    """
    assembled: Dict[str, object] = {}

    if short_description:
        assembled["short_description"] = short_description

    for json_key, suffix, _label in VGL_CATEGORIES:
        raw = category_parms.get(suffix, "").strip()
        if not raw:
            continue
        try:
            assembled[json_key] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # If it's not valid JSON, store as raw string
            assembled[json_key] = raw

    # Merge "other" fields back into the top level
    other_raw = category_parms.get("other", "").strip()
    if other_raw:
        try:
            other_dict = json.loads(other_raw)
            if isinstance(other_dict, dict):
                assembled.update(other_dict)
        except (json.JSONDecodeError, TypeError):
            pass

    return json.dumps(assembled, indent=2, default=str)


def extract_short_description(vgl_json: str) -> str:
    """Extract short_description from VGL JSON, or return empty string."""
    try:
        data = json.loads(vgl_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(data, dict):
        return str(data.get("short_description", ""))
    return ""


# ---------------------------------------------------------------------------
# Per-field parse/assemble (v2 — for structured parm UI)
# ---------------------------------------------------------------------------

def parse_structured(vgl_json: str) -> Optional[Dict[str, Any]]:
    """Parse full VGL JSON into per-field Python values.

    Returns a dict with native Python types (not JSON strings):
      "short_description": str
      "background_setting": str
      "objects": list[dict]  — list of object dicts with all fields
      "lighting": dict       — {json_key: str_value}
      "aesthetics": dict
      "photographic_characteristics": dict
      "style_medium": str
      "text_render": list    — raw array (usually empty)
      "other": dict          — catch-all for unknown top-level keys
    """
    try:
        data = json.loads(vgl_json)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    result: Dict[str, Any] = {}
    other: Dict[str, Any] = {}

    for key, value in data.items():
        if key == "short_description":
            result["short_description"] = str(value) if value else ""
        elif key == "background_setting":
            result["background_setting"] = str(value) if value else ""
        elif key == "objects":
            if isinstance(value, list):
                result["objects"] = value
            else:
                result["objects"] = []
        elif key == "lighting":
            result["lighting"] = value if isinstance(value, dict) else {}
        elif key == "aesthetics":
            result["aesthetics"] = value if isinstance(value, dict) else {}
        elif key == "photographic_characteristics":
            result["photographic_characteristics"] = (
                value if isinstance(value, dict) else {}
            )
        elif key == "style_medium":
            result["style_medium"] = str(value) if value else ""
        elif key == "text_render":
            result["text_render"] = value if isinstance(value, list) else []
        else:
            other[key] = value

    if other:
        result["other"] = other

    return result


def assemble_structured(fields: Dict[str, Any]) -> str:
    """Assemble full VGL JSON from a structured field dict.

    Inverse of parse_structured(). Returns formatted JSON string.
    """
    assembled: Dict[str, Any] = {}

    if fields.get("short_description"):
        assembled["short_description"] = fields["short_description"]

    if fields.get("background_setting"):
        assembled["background_setting"] = fields["background_setting"]

    objects = fields.get("objects")
    if objects:
        assembled["objects"] = objects

    if fields.get("lighting"):
        assembled["lighting"] = fields["lighting"]

    if fields.get("aesthetics"):
        assembled["aesthetics"] = fields["aesthetics"]

    if fields.get("photographic_characteristics"):
        assembled["photographic_characteristics"] = fields[
            "photographic_characteristics"
        ]

    style = fields.get("style_medium")
    if style:
        assembled["style_medium"] = style

    text_render = fields.get("text_render")
    if text_render:
        assembled["text_render"] = text_render

    # Merge "other" catch-all back into top level
    other = fields.get("other")
    if isinstance(other, dict):
        assembled.update(other)

    return json.dumps(assembled, indent=2, default=str)
