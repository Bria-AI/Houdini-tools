"""Bria Batch — unified batch processing via PDG.

Python Processor TOP node that supports all Bria API operations:
FIBO Generate, FIBO Edit, Enhancer, Upscale, and Remove Background.

Mode is selected via a dropdown on the HDA. Each work item carries a
``mode`` attribute that determines which API is called during cook.

Upstream attributes (e.g. from a Wedge TOP) override node parameter
defaults, enabling seed/prompt/guidance wedging.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

from bria_houdini.bria_core.utils import download_url, extract_image_url
from bria_houdini.adapter import (
    fibo_edit_from_files,
    fibo_generate_from_payload,
    generate_structured_prompt,
    remove_background_from_files,
    upscale_from_files,
)
from bria_houdini.node_utils import _safe_exc_str, clamp_steps_num, save_api_metadata
from bria_houdini.nodes.fibo_edit_recipes import ALL_PRESETS, PRESET_CATEGORIES

logger = logging.getLogger(__name__)

# Mode constants (match menu_items in the HDA)
MODE_GENERATE = "generate"
MODE_EDIT = "edit"
MODE_ENHANCER = "enhancer"
MODE_UPSCALE = "upscale"
MODE_RMBG = "rmbg"

_ALL_MODES = {MODE_GENERATE, MODE_EDIT, MODE_ENHANCER, MODE_UPSCALE, MODE_RMBG}
_MODES_NEED_INPUT = {MODE_EDIT, MODE_ENHANCER, MODE_UPSCALE, MODE_RMBG}

# Batch-eligible categories (excludes custom, compositing)
BATCH_CATEGORY_KEYS = [
    "style", "weather", "seasons", "time_of_day",
    "camera", "lighting", "clean", "ai_corrections", "object_edits",
]

# Targeted presets excluded from batch (need per-image input)
_BATCH_EXCLUDED = {
    "delete_object", "replace_object",
    "change_object_color", "change_object_material",
}


# ------------------------------------------------------------------
# onGenerate — create work items
# ------------------------------------------------------------------

def generate_work_items(node, item_holder, upstream_items, generation_type):
    """Create work items based on selected mode and upstream inputs.

    Called by the Python Processor's ``onGenerate`` callback.
    """
    import hou

    top_node = node.topNode()

    # Read mode
    mode = top_node.parm("mode").evalAsString().strip()
    if mode not in _ALL_MODES:
        raise RuntimeError(f"Unknown mode: {mode}")

    # Warn user about multiple API calls
    num_items = len(upstream_items) if upstream_items else 1
    try:
        confirm = hou.ui.displayMessage(
            f"This will launch {num_items} API call(s) to Bria.\n\n"
            f"Mode: {mode.upper()}\n"
            "Each work item makes a separate API request.\n\n"
            "Continue?",
            buttons=("Continue", "Cancel"),
            severity=hou.severityType.Warning,
            title="Bria Batch",
        )
        if confirm == 1:
            return
    except Exception:
        pass

    # Read common parms
    prompt = top_node.parm("prompt").evalAsString().strip()
    structured_prompt = top_node.parm("structured_prompt").evalAsString().strip()
    negative_prompt = top_node.parm("negative_prompt").evalAsString().strip()
    seed = int(top_node.parm("seed").eval())

    has_upstream = bool(upstream_items)

    # Validate: non-generate modes require upstream images
    if not has_upstream and mode in _MODES_NEED_INPUT:
        raise RuntimeError(
            f"Mode '{mode}' requires upstream images. "
            "Connect a File Pattern TOP (or other source) upstream."
        )

    # Generate mode + incoming images: determine structured prompt behavior
    auto_struct = 0
    if mode == MODE_GENERATE and has_upstream:
        if not structured_prompt and prompt:
            # User has basic prompt + incoming images
            # Show dialog: images will be ignored with basic prompt
            try:
                choice = hou.ui.displayMessage(
                    "Generate mode with incoming images: each image can be "
                    "analyzed into a Structured Prompt via the Bria API, "
                    "then used to generate a new image.\n\n"
                    "With Basic Prompt, incoming images will be ignored and "
                    "all items will use the same text prompt.\n\n"
                    "Use Structured Prompt flow for incoming images?",
                    buttons=("Use Structured Prompt", "Use Basic Prompt"),
                    severity=hou.severityType.Warning,
                    title="Bria Batch — Generate",
                )
                if choice == 0:
                    auto_struct = 1
            except Exception:
                pass
        elif structured_prompt:
            # User already has a structured prompt set — don't auto-generate
            auto_struct = 0
        elif not prompt and not structured_prompt:
            # No prompt at all + incoming images → auto-generate structured prompt
            auto_struct = 1

    # Generate without upstream: create num_images work items
    if not has_upstream and mode == MODE_GENERATE:
        if not prompt and not structured_prompt:
            raise RuntimeError("Provide a Prompt or Structured Prompt for generation.")
        num_images = int(top_node.parm("num_images").eval()) if top_node.parm("num_images") else 1
        num_images = max(1, num_images)
        for i in range(num_images):
            new_item = item_holder.addWorkItem(inProcess=True)
            _set_common_attrs(new_item, None, mode, prompt, structured_prompt,
                              negative_prompt, seed, auto_struct, top_node)
        logger.info("[Bria Batch] Generate: created %d work items (no upstream)", num_images)
        return

    # Standard flow: one work item per upstream item
    for upstream_item in upstream_items:
        new_item = item_holder.addWorkItem(parent=upstream_item, inProcess=True)

        # Get input file from upstream output
        output_files = upstream_item.outputFiles
        if output_files:
            new_item.setStringAttrib("input_image", output_files[0].path)

        _set_common_attrs(new_item, upstream_item, mode, prompt, structured_prompt,
                          negative_prompt, seed, auto_struct, top_node)

    logger.info("[Bria Batch] %s: created %d work items", mode, len(upstream_items))


def _set_common_attrs(new_item, upstream_item, mode, prompt, structured_prompt,
                      negative_prompt, seed, auto_struct, top_node):
    """Set common attributes on a new work item."""
    new_item.setStringAttrib("mode", mode)
    new_item.setIntAttrib("auto_struct", auto_struct)

    # Prompt attributes (upstream override → node default)
    if upstream_item:
        _set_str_attr(new_item, upstream_item, "prompt", prompt)
        _set_str_attr(new_item, upstream_item, "structured_prompt", structured_prompt)
        _set_str_attr(new_item, upstream_item, "negative_prompt", negative_prompt)
        _set_int_attr(new_item, upstream_item, "seed", seed)
        _set_str_attr(new_item, upstream_item, "output_path", "")
    else:
        new_item.setStringAttrib("prompt", prompt)
        new_item.setStringAttrib("structured_prompt", structured_prompt)
        new_item.setStringAttrib("negative_prompt", negative_prompt)
        new_item.setIntAttrib("seed", seed)

    # Auto-generate output_path from output_dir + output_suffix parms
    existing_op = ""
    try:
        existing_op = new_item.attribValue("output_path") or ""
    except Exception:
        pass
    if not existing_op:
        out_dir = top_node.parm("output_dir").evalAsString().strip() if top_node.parm("output_dir") else ""
        suffix = top_node.parm("output_suffix").evalAsString().strip() if top_node.parm("output_suffix") else ""
        if out_dir or suffix:
            inp = ""
            try:
                inp = new_item.attribValue("input_image") or ""
            except Exception:
                pass
            if inp:
                basename = os.path.splitext(os.path.basename(inp))[0]
                ext = os.path.splitext(inp)[1] or ".png"
                filename = basename + suffix + ext
                save_dir = out_dir if out_dir else os.path.dirname(inp)
                new_item.setStringAttrib("output_path", os.path.join(save_dir, filename))

    # Mode-specific attributes from TOP node parms
    if mode in (MODE_GENERATE, MODE_EDIT):
        guidance = int(top_node.parm("guidance_scale").eval()) if top_node.parm("guidance_scale") else 5
        steps = int(top_node.parm("steps_num").eval()) if top_node.parm("steps_num") else 0
        if upstream_item:
            _set_int_attr(new_item, upstream_item, "guidance_scale", guidance)
            _set_int_attr(new_item, upstream_item, "steps_num", steps)
        else:
            new_item.setIntAttrib("guidance_scale", guidance)
            new_item.setIntAttrib("steps_num", steps)

    if mode == MODE_GENERATE:
        ar_parm = top_node.parm("aspect_ratio")
        if ar_parm:
            new_item.setStringAttrib("aspect_ratio", ar_parm.evalAsString().strip())
        pipe_parm = top_node.parm("pipeline")
        if pipe_parm:
            new_item.setStringAttrib("pipeline", pipe_parm.evalAsString().strip())

    if mode == MODE_ENHANCER:
        res_parm = top_node.parm("resolution")
        if res_parm:
            new_item.setStringAttrib("resolution", res_parm.evalAsString().strip())
        steps = int(top_node.parm("steps_num").eval()) if top_node.parm("steps_num") else 0
        new_item.setIntAttrib("steps_num", steps)
        pa_parm = top_node.parm("preserve_alpha")
        if pa_parm:
            new_item.setIntAttrib("preserve_alpha", int(pa_parm.eval()))
        cm_in = top_node.parm("content_moderation_input")
        if cm_in:
            new_item.setIntAttrib("content_moderation_input", int(cm_in.eval()))
        cm_out = top_node.parm("content_moderation_output")
        if cm_out:
            new_item.setIntAttrib("content_moderation_output", int(cm_out.eval()))

    if mode == MODE_UPSCALE:
        dr_parm = top_node.parm("desired_resolution")
        if dr_parm:
            new_item.setStringAttrib("desired_resolution", dr_parm.evalAsString().strip())
        pa_parm = top_node.parm("preserve_alpha")
        if pa_parm:
            new_item.setIntAttrib("preserve_alpha", int(pa_parm.eval()))
        cm_in = top_node.parm("content_moderation_input")
        if cm_in:
            new_item.setIntAttrib("content_moderation_input", int(cm_in.eval()))
        cm_out = top_node.parm("content_moderation_output")
        if cm_out:
            new_item.setIntAttrib("content_moderation_output", int(cm_out.eval()))

    if mode == MODE_RMBG:
        pa_parm = top_node.parm("preserve_alpha")
        if pa_parm:
            new_item.setIntAttrib("preserve_alpha", int(pa_parm.eval()))
        kos_parm = top_node.parm("keep_original_size")
        if kos_parm:
            new_item.setIntAttrib("keep_original_size", int(kos_parm.eval()))
        fbg_parm = top_node.parm("force_bg_detection")
        if fbg_parm:
            new_item.setIntAttrib("force_bg_detection", int(fbg_parm.eval()))
        cm_in = top_node.parm("content_moderation_input")
        if cm_in:
            new_item.setIntAttrib("content_moderation_input", int(cm_in.eval()))
        cm_out = top_node.parm("content_moderation_output")
        if cm_out:
            new_item.setIntAttrib("content_moderation_output", int(cm_out.eval()))


# ------------------------------------------------------------------
# onCookTask — process a single work item
# ------------------------------------------------------------------

def _get_semaphore(max_concurrent: int) -> threading.Semaphore:
    """Return a session-level semaphore for rate-limiting concurrent API calls."""
    try:
        import hou
        key = "_bria_batch_semaphore"
        count_key = "_bria_batch_sem_count"
        current_count = getattr(hou.session, count_key, 0)
        if current_count != max_concurrent or not hasattr(hou.session, key):
            setattr(hou.session, key, threading.Semaphore(max_concurrent))
            setattr(hou.session, count_key, max_concurrent)
        return getattr(hou.session, key)
    except Exception:
        return threading.Semaphore(max_concurrent)


def cook_work_item(node, work_item):
    """Process one work item through the appropriate Bria API.

    Called by the Python Processor's ``onCookTask`` callback.
    """
    # Concurrency control
    max_concurrent = 4
    try:
        import hou
        top_node = node.topNode()
        mc_parm = top_node.parm("max_concurrent")
        if mc_parm:
            max_concurrent = max(1, int(mc_parm.eval()))
    except Exception:
        pass

    sem = _get_semaphore(max_concurrent)
    sem.acquire()
    try:
        _cook_work_item_inner(node, work_item)
    finally:
        sem.release()


# ------------------------------------------------------------------
# Preset callbacks (called from HDA parm script_callback)
# ------------------------------------------------------------------

def on_prompt_mode_changed(kwargs):
    """Callback when prompt_mode toggles between Custom/Preset."""
    node = kwargs.get("node")
    if node is None:
        return
    mode_parm = node.parm("prompt_mode")
    if mode_parm is None:
        return
    if mode_parm.evalAsString() == "preset":
        _fill_preset_prompt(node)


def on_batch_category_changed(kwargs):
    """Callback when batch_category changes — reset preset menu, fill prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    cat = node.parm("batch_category")
    if cat is None:
        return
    cat_key = cat.evalAsString()
    preset_parm = node.parm(f"batch_preset_{cat_key}")
    if preset_parm is not None:
        preset_parm.set(0)
    _fill_preset_prompt(node)


def on_batch_preset_changed(kwargs):
    """Callback when a batch preset menu changes — fill prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    _fill_preset_prompt(node)


def _fill_preset_prompt(node):
    """Look up the selected preset's prompt text and fill the prompt parm."""
    cat_parm = node.parm("batch_category")
    if cat_parm is None:
        return
    cat_key = cat_parm.evalAsString()
    preset_parm = node.parm(f"batch_preset_{cat_key}")
    if preset_parm is None:
        return
    preset_key = preset_parm.evalAsString()
    prompt_text = ALL_PRESETS.get(preset_key, "")
    if prompt_text:
        node.parm("prompt").set(prompt_text)


def _cook_work_item_inner(node, work_item):
    """Inner cook logic — called under the concurrency semaphore."""
    t_start = time.perf_counter()

    mode = work_item.attribValue("mode") or ""

    # Fallback: read mode from TOP node parm if attribute is empty
    if not mode:
        try:
            import hou
            top_node = node.topNode()
            mode = top_node.parm("mode").evalAsString().strip()
        except Exception:
            pass

    if mode not in _ALL_MODES:
        raise RuntimeError(f"Unknown mode: {mode}")

    # Dispatch to per-mode cook function
    if mode == MODE_GENERATE:
        result_path = _cook_generate(node, work_item)
    elif mode == MODE_EDIT:
        result_path = _cook_edit(node, work_item)
    elif mode == MODE_ENHANCER:
        result_path = _cook_enhancer(node, work_item)
    elif mode == MODE_UPSCALE:
        result_path = _cook_upscale(node, work_item)
    elif mode == MODE_RMBG:
        result_path = _cook_rmbg(node, work_item)
    else:
        raise RuntimeError(f"Unhandled mode: {mode}")

    # Set outputs on work item
    work_item.addOutputFile(result_path, tag="result")
    work_item.setStringAttrib("result_path", result_path)

    elapsed = time.perf_counter() - t_start
    logger.info("[Bria Batch] Done (%s): %s (%.1fs)", mode, result_path, elapsed)

    # Optional MPlay display
    try:
        import hou
        top_node = node.topNode()
        show_parm = top_node.parm("open_in_mplay")
        if show_parm and show_parm.eval():
            _send_to_mplay(result_path)
    except Exception as exc:
        logger.debug("[Bria Batch] MPlay send skipped: %s", _safe_exc_str(exc))


# ------------------------------------------------------------------
# Per-mode cook functions
# ------------------------------------------------------------------

def _read_prompt_attrs(node, work_item):
    """Read prompt-related attributes with fallback to TOP node parms."""
    prompt = work_item.attribValue("prompt") or ""
    structured_prompt = work_item.attribValue("structured_prompt") or ""
    negative_prompt = work_item.attribValue("negative_prompt") or ""

    # Fallback: read directly from TOP node parms if work item attributes
    # are empty (handles re-cook after parm change without regeneration).
    if not prompt and not structured_prompt:
        try:
            import hou
            top_node = node.topNode()
            prompt = top_node.parm("prompt").evalAsString().strip()
            structured_prompt = top_node.parm("structured_prompt").evalAsString().strip()
            if not negative_prompt:
                negative_prompt = top_node.parm("negative_prompt").evalAsString().strip()
        except Exception:
            pass

    # Preset mode fallback: resolve prompt from preset data if still empty
    if not prompt and not structured_prompt:
        try:
            import hou
            top_node = node.topNode()
            pm = top_node.parm("prompt_mode")
            if pm and pm.evalAsString() == "preset":
                cat = top_node.parm("batch_category")
                if cat:
                    cat_key = cat.evalAsString()
                    pp = top_node.parm(f"batch_preset_{cat_key}")
                    if pp:
                        preset_key = pp.evalAsString()
                        prompt = ALL_PRESETS.get(preset_key, "")
        except Exception:
            pass

    return prompt, structured_prompt, negative_prompt


def _cook_generate(node, work_item) -> str:
    """Generate an image via FIBO Generate API."""
    input_image = work_item.attribValue("input_image") or ""
    prompt, structured_prompt, negative_prompt = _read_prompt_attrs(node, work_item)
    auto_struct = work_item.intAttribValue("auto_struct") or 0

    # Auto-generate structured prompt from input image
    if input_image and auto_struct and os.path.exists(input_image):
        logger.info("[Bria Batch] Auto-generating structured prompt from: %s", input_image)
        struct_data = generate_structured_prompt(image_path=input_image)
        result = struct_data.get("result", {})
        sp = result.get("structured_prompt") if isinstance(result, dict) else None
        if sp is None:
            sp = struct_data.get("structured_prompt")
        if isinstance(sp, dict):
            structured_prompt = json.dumps(sp)
        elif isinstance(sp, str):
            structured_prompt = sp
        prompt = ""  # Use structured prompt, not basic prompt

    if not prompt and not structured_prompt:
        raise RuntimeError("No prompt or structured_prompt provided for generation")

    seed_val = work_item.intAttribValue("seed")
    seed = seed_val if seed_val and seed_val > 0 else None
    guidance_scale = work_item.intAttribValue("guidance_scale") or 5
    steps_num = clamp_steps_num(work_item.intAttribValue("steps_num") or 0)
    aspect_ratio = work_item.attribValue("aspect_ratio") or ""
    pipeline = work_item.attribValue("pipeline") or "standard"

    # Build payload
    payload = {}
    if structured_prompt:
        payload["structured_prompt"] = structured_prompt
    elif prompt:
        payload["prompt"] = prompt
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if seed is not None and seed > 0:
        payload["seed"] = seed
    if guidance_scale and guidance_scale > 0:
        payload["guidance_scale"] = min(guidance_scale, 5)
    if steps_num:
        payload["steps_num"] = steps_num

    use_structured = bool(structured_prompt)
    logger.info("[Bria Batch] Generate: %s (pipeline=%s)",
                "structured_prompt" if use_structured else "text_prompt", pipeline)

    data = fibo_generate_from_payload(
        payload=payload,
        pipeline=pipeline,
        use_structured_prompt=use_structured,
    )

    return _download_result(data, work_item, "generate")


def _cook_edit(node, work_item) -> str:
    """Edit an image via FIBO Edit API."""
    input_image = work_item.attribValue("input_image") or ""
    if not input_image or not os.path.exists(input_image):
        raise RuntimeError(f"Input image not found: {input_image}")

    prompt, structured_prompt, negative_prompt = _read_prompt_attrs(node, work_item)

    if not prompt and not structured_prompt:
        raise RuntimeError("No prompt or structured_prompt provided for edit")

    seed_val = work_item.intAttribValue("seed")
    seed = seed_val if seed_val and seed_val > 0 else None
    guidance_scale = work_item.intAttribValue("guidance_scale") or 5
    steps_num = clamp_steps_num(work_item.intAttribValue("steps_num") or 0)

    logger.info("[Bria Batch] Edit: %s (item %d)", input_image, work_item.index)

    data = fibo_edit_from_files(
        image_path=input_image,
        prompt=prompt or None,
        structured_prompt=structured_prompt or None,
        negative_prompt=negative_prompt or None,
        guidance_scale=min(guidance_scale, 5) if guidance_scale else None,
        seed=seed,
        steps_num=steps_num,
    )

    return _download_result(data, work_item, "edit")


def _cook_enhancer(node, work_item) -> str:
    """Enhance an image via Bria Enhance API."""
    input_image = work_item.attribValue("input_image") or ""
    if not input_image or not os.path.exists(input_image):
        raise RuntimeError(f"Input image not found: {input_image}")

    resolution = work_item.attribValue("resolution") or "1MP"
    seed_val = work_item.intAttribValue("seed")
    seed = seed_val if seed_val and seed_val > 0 else None
    steps_num = clamp_steps_num(work_item.intAttribValue("steps_num") or 0)
    preserve_alpha = bool(work_item.intAttribValue("preserve_alpha"))
    cm_input = bool(work_item.intAttribValue("content_moderation_input"))
    cm_output = bool(work_item.intAttribValue("content_moderation_output"))

    logger.info("[Bria Batch] Enhance: %s (resolution=%s)", input_image, resolution)

    data = upscale_from_files(
        image_path=input_image,
        mode="enhance",
        resolution=resolution,
        preserve_alpha=preserve_alpha,
        seed=seed,
        steps_num=steps_num,
        content_moderation_input=cm_input or None,
        content_moderation_output=cm_output or None,
    )

    return _download_result(data, work_item, "enhancer")


def _cook_upscale(node, work_item) -> str:
    """Upscale an image via Bria Increase Resolution API."""
    input_image = work_item.attribValue("input_image") or ""
    if not input_image or not os.path.exists(input_image):
        raise RuntimeError(f"Input image not found: {input_image}")

    desired_resolution = work_item.attribValue("desired_resolution") or "2x"
    seed_val = work_item.intAttribValue("seed")
    seed = seed_val if seed_val and seed_val > 0 else None
    preserve_alpha = bool(work_item.intAttribValue("preserve_alpha"))
    cm_input = bool(work_item.intAttribValue("content_moderation_input"))
    cm_output = bool(work_item.intAttribValue("content_moderation_output"))

    logger.info("[Bria Batch] Upscale: %s (resolution=%s)", input_image, desired_resolution)

    data = upscale_from_files(
        image_path=input_image,
        mode="increase_resolution",
        desired_resolution=desired_resolution,
        preserve_alpha=preserve_alpha,
        seed=seed,
        content_moderation_input=cm_input or None,
        content_moderation_output=cm_output or None,
    )

    return _download_result(data, work_item, "upscale")


def _cook_rmbg(node, work_item) -> str:
    """Remove background via Bria RMBG API."""
    input_image = work_item.attribValue("input_image") or ""
    if not input_image or not os.path.exists(input_image):
        raise RuntimeError(f"Input image not found: {input_image}")

    preserve_alpha = bool(work_item.intAttribValue("preserve_alpha"))
    keep_original_size = bool(work_item.intAttribValue("keep_original_size"))
    force_bg_detection = bool(work_item.intAttribValue("force_bg_detection"))
    cm_input = bool(work_item.intAttribValue("content_moderation_input"))
    cm_output = bool(work_item.intAttribValue("content_moderation_output"))

    logger.info("[Bria Batch] Remove BG: %s", input_image)

    data = remove_background_from_files(
        image_path=input_image,
        preserve_alpha=preserve_alpha,
        keep_original_size=keep_original_size or None,
        force_bg_detection=force_bg_detection or None,
        content_moderation_input=cm_input or None,
        content_moderation_output=cm_output or None,
    )

    return _download_result(data, work_item, "rmbg")


# ------------------------------------------------------------------
# Common helpers
# ------------------------------------------------------------------

def _download_result(data: dict, work_item, prefix: str) -> str:
    """Extract image URL from API response, download, and save.

    If the work item has an ``output_path`` attribute (set by an upstream
    Python Script TOP or auto-generated from output_dir/output_suffix parms),
    the result is saved there.  Otherwise falls back to the temp directory.
    """
    dl_url = extract_image_url(data)
    if not dl_url:
        raise RuntimeError(f"No image_url in API response: {data}")

    img_bytes, _content_type = download_url(dl_url, timeout_s=300)

    # Use upstream output_path if set, otherwise auto-generate in temp dir
    custom_output = ""
    try:
        custom_output = work_item.attribValue("output_path") or ""
    except Exception:
        pass

    if custom_output:
        output_path = custom_output
    else:
        output_dir = work_item.tempDir
        index = work_item.index
        input_image = work_item.attribValue("input_image") or ""
        if input_image:
            basename = os.path.splitext(os.path.basename(input_image))[0]
        else:
            basename = "generated"
        output_path = os.path.join(output_dir, f"bria_{prefix}_{basename}_{index:04d}.png")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "wb") as fh:
        fh.write(img_bytes)

    # Save API metadata sidecar (matches COP node pattern)
    try:
        save_api_metadata(output_path, data, prefix)
    except Exception:
        pass

    return output_path


def _set_str_attr(new_item, upstream_item, name: str, default: str):
    """Use upstream string attribute if present, else node default."""
    try:
        val = upstream_item.attribValue(name)
        if val:
            new_item.setStringAttrib(name, val)
            return
    except Exception:
        pass
    new_item.setStringAttrib(name, default)


def _set_int_attr(new_item, upstream_item, name: str, default: int):
    """Use upstream int attribute if present, else node default."""
    try:
        val = upstream_item.intAttribValue(name)
        if val is not None and val != 0:
            new_item.setIntAttrib(name, val)
            return
    except Exception:
        pass
    new_item.setIntAttrib(name, int(default))


def _find_houdini_binary(name: str):
    """Locate a Houdini binary (mplay, imdisplay, etc.) in $HFS/bin."""
    import sys
    import hou

    bin_name = f"{name}.exe" if sys.platform == "win32" else name

    try:
        path = hou.findFile(f"bin/{bin_name}")
        if path and os.path.exists(path):
            return path
    except Exception:
        pass

    try:
        hfs = hou.getenv("HFS")
        if hfs:
            path = os.path.join(hfs, "bin", bin_name)
            if os.path.exists(path):
                return path
    except Exception:
        pass

    return None


def _send_to_mplay(image_path: str) -> None:
    """Send a result image to a shared MPlay session labeled 'Bria Batch'."""
    import subprocess

    normalized = image_path.replace("\\", "/")

    imdisplay = _find_houdini_binary("imdisplay")
    if imdisplay:
        try:
            subprocess.Popen([imdisplay, "-Y", "Bria Batch", normalized])
            logger.info("[Bria Batch] Sent to MPlay: %s", normalized)
            return
        except Exception as exc:
            logger.warning("[Bria Batch] imdisplay failed: %s", _safe_exc_str(exc))

    mplay = _find_houdini_binary("mplay")
    if mplay:
        try:
            subprocess.Popen([mplay, normalized])
            logger.info("[Bria Batch] Launched MPlay: %s", normalized)
            return
        except Exception as exc:
            logger.warning("[Bria Batch] mplay launch failed: %s", _safe_exc_str(exc))

    logger.warning("[Bria Batch] Neither imdisplay nor mplay found in $HFS/bin")
