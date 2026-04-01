"""Shared Houdini parameter read/write logic for VGL structured prompts.

Both FIBO Generate and FIBO Edit Presets import from this module.
Centralizes all VGL parm population, assembly, and button callbacks.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import hou

from bria_houdini.node_utils import debug_logger
from bria_houdini.vgl_utils import (
    VGL_OBJECT_FIELDS,
    VGL_CATEGORY_SUBFIELDS,
    VGL_LIGHTING_FIELDS,
    VGL_AESTHETICS_FIELDS,
    VGL_PHOTO_FIELDS,
    extract_short_description,
    parse_structured,
    assemble_structured,
)

_debug_log = debug_logger("VGL Parms")


# ---------------------------------------------------------------------------
# Read parms -> Python data
# ---------------------------------------------------------------------------

def read_objects_from_parms(node: hou.Node) -> List[Dict[str, Any]]:
    """Read MultiparmBlock object instances into a list of dicts."""
    count_parm = node.parm("vgl_obj_count")
    if count_parm is None:
        return []
    count = count_parm.eval()
    if not count or count <= 0:
        return []

    objects = []
    for i in range(1, count + 1):
        obj: Dict[str, Any] = {}
        for json_key, suffix, _label, _is_person, field_type in VGL_OBJECT_FIELDS:
            parm_name = f"vgl_obj_{suffix}_{i}"
            parm = node.parm(parm_name)
            if parm is None:
                obj[json_key] = None
                continue
            if field_type == "int":
                val = parm.eval()
                obj[json_key] = val if val and val > 0 else None
            else:
                val = (parm.eval() or "").strip()
                obj[json_key] = val or None
        objects.append(obj)
    return objects


def read_subfields_from_parms(
    node: hou.Node, category_suffix: str
) -> Dict[str, str]:
    """Read structured sub-fields for a category (lighting, aesthetics, photo)."""
    subfields = VGL_CATEGORY_SUBFIELDS.get(category_suffix, [])
    result: Dict[str, str] = {}
    for json_key, field_suffix, _label in subfields:
        parm_name = f"vgl_{category_suffix}_{field_suffix}"
        parm = node.parm(parm_name)
        val = (parm.eval() or "").strip() if parm else ""
        if val:
            result[json_key] = val
    return result


# ---------------------------------------------------------------------------
# Write Python data -> parms
# ---------------------------------------------------------------------------

def write_objects_to_parms(node: hou.Node, objects: List[Dict[str, Any]]) -> None:
    """Write a list of object dicts into MultiparmBlock instances."""
    count_parm = node.parm("vgl_obj_count")
    if count_parm is None:
        return
    count_parm.set(len(objects))
    for i, obj in enumerate(objects, start=1):
        for json_key, suffix, _label, _is_person, field_type in VGL_OBJECT_FIELDS:
            parm_name = f"vgl_obj_{suffix}_{i}"
            parm = node.parm(parm_name)
            if parm is None:
                continue
            val = obj.get(json_key)
            if field_type == "int":
                parm.set(val if val is not None else 0)
            else:
                parm.set(str(val) if val else "")


def write_subfields_to_parms(
    node: hou.Node, category_suffix: str, data: Dict[str, Any]
) -> None:
    """Write structured sub-fields for a category."""
    subfields = VGL_CATEGORY_SUBFIELDS.get(category_suffix, [])
    for json_key, field_suffix, _label in subfields:
        parm_name = f"vgl_{category_suffix}_{field_suffix}"
        parm = node.parm(parm_name)
        if parm:
            parm.set(str(data.get(json_key, "") or ""))


# ---------------------------------------------------------------------------
# High-level assemble / populate
# ---------------------------------------------------------------------------

_SUBFIELD_JSON_KEY_MAP = {
    "lighting": "lighting",
    "aesthetics": "aesthetics",
    "photo": "photographic_characteristics",
}


def assemble_from_parms(node: hou.Node) -> Optional[str]:
    """Read all VGL parms and assemble into full VGL JSON.

    Returns None if all fields are empty (no VGL data).
    """
    fields: Dict[str, Any] = {}

    # Short description (hidden parm for round-trip)
    desc_parm = node.parm("vgl_short_desc")
    if desc_parm:
        desc = (desc_parm.eval() or "").strip()
        if desc:
            fields["short_description"] = desc

    # Background setting
    bg_parm = node.parm("vgl_scene_text")
    bg = (bg_parm.eval() or "").strip() if bg_parm else ""
    if bg:
        fields["background_setting"] = bg

    # Objects (multiparm)
    objects = read_objects_from_parms(node)
    if objects:
        fields["objects"] = objects

    # Structured sub-field categories
    for cat_suffix, json_key in _SUBFIELD_JSON_KEY_MAP.items():
        sub = read_subfields_from_parms(node, cat_suffix)
        if sub:
            fields[json_key] = sub

    # Style
    style_parm = node.parm("vgl_style_text")
    style = (style_parm.eval() or "").strip() if style_parm else ""
    if style:
        fields["style_medium"] = style

    # Text render (raw JSON)
    text_parm = node.parm("vgl_text_json")
    text_val = (text_parm.eval() or "").strip() if text_parm else ""
    if text_val:
        try:
            fields["text_render"] = json.loads(text_val)
        except (json.JSONDecodeError, TypeError):
            pass

    # Other (raw JSON catch-all)
    other_parm = node.parm("vgl_other")
    other_val = (other_parm.eval() or "").strip() if other_parm else ""
    if other_val:
        try:
            other_dict = json.loads(other_val)
            if isinstance(other_dict, dict):
                fields["other"] = other_dict
        except (json.JSONDecodeError, TypeError):
            pass

    # Check if we have any real content (not just short_description)
    content_keys = set(fields.keys()) - {"short_description"}
    if not content_keys:
        return None

    _debug_log(f"Assembled VGL from {len(content_keys)} section(s)")
    return assemble_structured(fields)


def populate_parms_from_json(node: hou.Node, vgl_json: str) -> int:
    """Parse VGL JSON and populate all structured parms.

    Returns count of populated sections.
    """
    parsed = parse_structured(vgl_json)
    if not parsed:
        return 0

    populated = 0

    # Short description
    desc = parsed.get("short_description", "")
    desc_parm = node.parm("vgl_short_desc")
    if desc_parm:
        desc_parm.set(desc)
    if desc:
        update_vgl_description(node, desc)

    # Background setting
    bg = parsed.get("background_setting", "")
    bg_parm = node.parm("vgl_scene_text")
    if bg_parm:
        bg_parm.set(bg)
        if bg:
            populated += 1

    # Objects (multiparm)
    objects = parsed.get("objects", [])
    if objects:
        write_objects_to_parms(node, objects)
        populated += 1
    else:
        count_parm = node.parm("vgl_obj_count")
        if count_parm:
            count_parm.set(0)

    # Structured sub-field categories
    for cat_suffix, json_key in _SUBFIELD_JSON_KEY_MAP.items():
        cat_data = parsed.get(json_key, {})
        if isinstance(cat_data, dict) and cat_data:
            write_subfields_to_parms(node, cat_suffix, cat_data)
            populated += 1
        else:
            # Clear sub-fields
            write_subfields_to_parms(node, cat_suffix, {})

    # Style
    style = parsed.get("style_medium", "")
    style_parm = node.parm("vgl_style_text")
    if style_parm:
        style_parm.set(str(style) if style else "")
        if style:
            populated += 1

    # Text render
    text_render = parsed.get("text_render", [])
    text_parm = node.parm("vgl_text_json")
    if text_parm:
        text_parm.set(
            json.dumps(text_render, indent=2) if text_render else ""
        )
        if text_render:
            populated += 1

    # Other
    other = parsed.get("other")
    other_parm = node.parm("vgl_other")
    if other_parm:
        other_parm.set(
            json.dumps(other, indent=2, default=str)
            if isinstance(other, dict) and other
            else ""
        )
        if other:
            populated += 1

    return populated


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def update_vgl_description(node: hou.Node, description: str) -> None:
    """Update the vgl_description label parm with the short description."""
    try:
        ptg = node.parmTemplateGroup()
        old = ptg.find("vgl_description")
        if old is not None:
            replacement = hou.LabelParmTemplate(
                "vgl_description",
                "Description:",
                column_labels=[description[:120]],
            )
            ptg.replace("vgl_description", replacement)
            node.setParmTemplateGroup(ptg)
    except Exception as exc:
        _debug_log(f"Could not update description label: {repr(exc)}")


def clear_vgl_parms(node: hou.Node) -> None:
    """Clear all VGL structured parms on a node."""
    for pname in ("vgl_short_desc", "vgl_scene_text", "vgl_style_text",
                  "vgl_text_json", "vgl_other"):
        p = node.parm(pname)
        if p:
            p.set("")

    # Clear sub-field categories
    for cat_suffix, subfields in VGL_CATEGORY_SUBFIELDS.items():
        for _jk, field_suffix, _label in subfields:
            p = node.parm(f"vgl_{cat_suffix}_{field_suffix}")
            if p:
                p.set("")

    # Clear multiparm
    count_p = node.parm("vgl_obj_count")
    if count_p:
        count_p.set(0)


# ---------------------------------------------------------------------------
# Button callbacks (used by PythonModule wrappers via hou.phm())
# ---------------------------------------------------------------------------

def on_parse_vgl(kwargs: dict) -> None:
    """Decompose raw structured_prompt into structured VGL parms."""
    node = kwargs.get("node")
    if node is None:
        return
    raw = (node.parm("structured_prompt").eval() or "").strip()
    if not raw:
        hou.ui.setStatusMessage(
            "No raw VGL JSON to parse \u2014 paste JSON in the Raw JSON section first.",
            severity=hou.severityType.Warning,
        )
        return

    populated = populate_parms_from_json(node, raw)
    hou.ui.setStatusMessage(f"Parsed VGL into {populated} section(s).")


def sync_vgl_to_json(kwargs: dict) -> None:
    """Assemble the organized VGL fields back into the raw JSON parm."""
    node = kwargs.get("node")
    if node is None:
        return
    json_str = assemble_from_parms(node)
    if not json_str:
        hou.ui.setStatusMessage(
            "No VGL fields to assemble \u2014 fill in the structured fields first.",
            severity=hou.severityType.Warning,
        )
        return
    sp_parm = node.parm("structured_prompt")
    if sp_parm:
        sp_parm.set(json_str)
    hou.ui.setStatusMessage("Raw JSON updated from structured fields.")


def on_refresh_upstream(kwargs: dict) -> None:
    """Pull structured prompt JSON from the connected upstream node.

    Checks ``result_json`` first (Generate Structured Prompt node), then
    falls back to ``structured_prompt`` (FIBO Generate, FIBO Edit, etc.).
    """
    node = kwargs.get("node")
    if node is None:
        return
    inputs = node.inputs()
    input_op = inputs[0] if len(inputs) > 0 else None
    if input_op is None:
        hou.ui.setStatusMessage(
            "No upstream node connected.",
            severity=hou.severityType.Warning,
        )
        return

    # Try result_json first (Generate Structured Prompt node stores here)
    result_parm = input_op.parm("result_json")
    if not result_parm:
        # Fall back to structured_prompt (FIBO Generate, FIBO Edit, etc.)
        result_parm = input_op.parm("structured_prompt")
    if not result_parm:
        hou.ui.setStatusMessage(
            "Upstream node has no structured prompt data.",
            severity=hou.severityType.Warning,
        )
        return

    json_val = (result_parm.eval() or "").strip()
    if not json_val:
        hou.ui.setStatusMessage(
            "Upstream structured prompt is empty \u2014 run the upstream node first.",
            severity=hou.severityType.Warning,
        )
        return

    # Re-format for readability
    try:
        json_val = json.dumps(json.loads(json_val), indent=2)
    except Exception:
        pass

    node.parm("structured_prompt").set(json_val)
    on_parse_vgl(kwargs)
    hou.ui.setStatusMessage("Refreshed VGL from upstream.")
