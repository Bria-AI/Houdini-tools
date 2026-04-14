"""Bria Sequence Output — batch render a COP chain with Bria AI nodes.

This module powers the Bria Sequence Output COP HDA. It discovers all upstream
Bria COP nodes, topologically sorts them, then for each frame in the range:
triggers each Bria node's API call, and exports the final composite to disk.

The artist builds their comp interactively (with standard Houdini + Bria nodes),
then drops this node at the end and clicks "Render Bria Sequence To Disk."
"""

from __future__ import annotations

import collections
import logging
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from bria_houdini.adapter import (
    erase_from_files,
    expand_from_files,
    fibo_edit_from_files,
    fibo_generate_from_payload,
    genfill_from_files,
    remove_background_from_files,
    upscale_from_files,
)
from bria_houdini.bria_core.utils import download_url, extract_image_url, resolve_proxies
from bria_houdini.cop_export import (
    _find_image_path_on_node,
    cop_to_png,
    export_via_internal_rop,
)
from bria_houdini.node_utils import (
    _safe_exc_str,
    clamp_steps_num,
    opt_parm_bool,
    opt_parm_int,
    opt_parm_menu_str,
    opt_parm_str,
    resolve_result_save_path,
    save_api_metadata,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bria COP node identification
# ---------------------------------------------------------------------------

# Maps the base node type name (without bria:: namespace and version) to a
# dispatch key used by the per-type cook functions.
_BRIA_TYPE_MAP: Dict[str, str] = {
    "bria_enhancer": "enhancer",
    "bria_fibo_edit_recipes": "fibo_edit",
    "bria_fibo_edit": "fibo_edit",
    "bria_fibo_generate": "fibo_generate",
    "bria_expand_v2": "expand",
    "bria_rmbg_v2": "rmbg",
    "bria_erase_v2": "erase",
    "bria_upscale_v2": "upscale",
    "bria_genfill_v2": "genfill",
    "bria_generate_vgl": "generate_vgl",
}

# Node types to explicitly skip (not part of image processing chains).
_SKIP_TYPES: Set[str] = {"bria_viewport_render"}


def _identify_bria_type(node: Any) -> Optional[str]:
    """Return the Bria dispatch key for *node*, or ``None`` if not a Bria COP."""
    try:
        type_name = node.type().name()
    except Exception:
        return None

    # Houdini namespaced types: "bria::<base_name>::<version>"
    parts = type_name.split("::")
    base = parts[1] if len(parts) >= 2 else type_name

    if base in _SKIP_TYPES:
        return None

    # Secondary check: every Bria COP has a result_path parm.
    btype = _BRIA_TYPE_MAP.get(base)
    if btype is not None and node.parm("result_path") is not None:
        return btype
    return None


# ---------------------------------------------------------------------------
# DAG discovery + topological sort
# ---------------------------------------------------------------------------

def discover_upstream_bria_dag(
    output_node: Any,
) -> List[Tuple[str, Any]]:
    """Walk upstream from *output_node* and return Bria nodes in cook order.

    Returns a list of ``(bria_type_key, node)`` tuples sorted so that every
    node appears after all the Bria nodes it depends on.  Non-Bria nodes are
    transparent — they cook automatically via Houdini's COP data flow.

    Supports any DAG topology: linear, branching, merging, parallel paths.
    """
    # Step 1: collect every Bria COP node upstream of output_node.
    all_bria: Dict[Any, str] = {}  # node -> bria_type
    _collect_upstream_bria(output_node, all_bria, visited=set())

    if not all_bria:
        return []

    # Step 2: for each Bria node, find which OTHER Bria nodes it depends on
    #         (transitively through non-Bria intermediaries).
    deps: Dict[Any, Set[Any]] = {}
    for bnode in all_bria:
        deps[bnode] = _find_bria_deps(bnode, set(all_bria.keys()))

    # Step 3: Kahn's topological sort.
    sorted_nodes = _topo_sort(all_bria, deps)
    return [(all_bria[n], n) for n in sorted_nodes]


def _collect_upstream_bria(
    node: Any,
    bria_nodes: Dict[Any, str],
    visited: Set[Any],
) -> None:
    """Recursively walk upstream, adding Bria COP nodes to *bria_nodes*."""
    if node is None or node in visited:
        return
    visited.add(node)

    btype = _identify_bria_type(node)
    if btype is not None:
        bria_nodes[node] = btype

    for inp in node.inputs() or []:
        if inp is not None:
            _collect_upstream_bria(inp, bria_nodes, visited)


def _find_bria_deps(bria_node: Any, all_bria: Set[Any]) -> Set[Any]:
    """Return the set of Bria nodes that *bria_node* depends on.

    Walks upstream through non-Bria nodes until another Bria node is found
    (which is a direct dependency — don't walk past it).
    """
    deps: Set[Any] = set()
    visited: Set[Any] = set()
    queue = [inp for inp in (bria_node.inputs() or []) if inp is not None]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        if node in all_bria:
            deps.add(node)  # Found a Bria dependency — stop here.
        else:
            # Non-Bria: keep walking upstream.
            queue.extend(inp for inp in (node.inputs() or []) if inp is not None)
    return deps


def _topo_sort(
    all_bria: Dict[Any, str],
    deps: Dict[Any, Set[Any]],
) -> List[Any]:
    """Kahn's algorithm topological sort over *all_bria* using *deps*."""
    in_degree: Dict[Any, int] = {n: 0 for n in all_bria}
    for node, node_deps in deps.items():
        in_degree[node] = len(node_deps)

    # Reverse map: for each node, which nodes depend on it?
    dependents: Dict[Any, List[Any]] = collections.defaultdict(list)
    for node, node_deps in deps.items():
        for dep in node_deps:
            dependents[dep].append(node)

    queue = collections.deque(n for n, d in in_degree.items() if d == 0)
    result: List[Any] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for downstream in dependents[node]:
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)

    if len(result) != len(all_bria):
        raise RuntimeError(
            "Cycle detected in Bria node dependencies. "
            "Check your COP network for circular connections."
        )
    return result


# ---------------------------------------------------------------------------
# Render sequence — main entry point
# ---------------------------------------------------------------------------

def render_sequence(node: Any) -> None:
    """Iterate over the frame range, cook all Bria nodes per frame, export output.

    Called by the HDA's 'Render Bria Sequence To Disk' button.
    Uses ``hou.InterruptableOperation`` for a progress dialog with cancel.
    """
    import hou

    start = int(node.evalParm("frame_start"))
    end = int(node.evalParm("frame_end"))
    step = max(1, int(node.evalParm("frame_step")))
    # Use unexpandedString() so $F stays as a variable until per-frame expansion.
    output_path = node.parm("output_path").unexpandedString()

    if not output_path.strip():
        hou.ui.displayMessage(
            "Output Path is empty. Set an output path before rendering.",
            severity=hou.severityType.Error,
            title="Bria Sequence Output",
        )
        return

    # Discover upstream Bria nodes.
    chain = discover_upstream_bria_dag(node)
    if not chain:
        hou.ui.displayMessage(
            "No Bria COP nodes found upstream of this node.\n"
            "Connect Bria nodes (Enhancer, FIBO Edit, RMBG, etc.) upstream.",
            severity=hou.severityType.Warning,
            title="Bria Sequence Output",
        )
        return

    frames = list(range(start, end + 1, step))
    total = len(frames)
    if total == 0:
        hou.ui.displayMessage(
            f"No frames in range {start}-{end} (step {step}).",
            severity=hou.severityType.Warning,
            title="Bria Sequence Output",
        )
        return

    chain_desc = " → ".join(btype for btype, _ in chain)
    logger.info(
        "[Bria Sequence] Starting: %d frames (%d-%d), chain: %s",
        total, start, end, chain_desc,
    )

    status_parm = node.parm("status")
    original_frame = hou.frame()
    errors: List[str] = []

    # Force Qt repaints so the progress bar visually updates between API calls.
    try:
        from PySide2 import QtWidgets
        _qapp = QtWidgets.QApplication.instance()
    except Exception:
        _qapp = None

    def _flush_ui():
        """Flush pending Qt events so the progress bar repaints."""
        if _qapp is not None:
            _qapp.processEvents()

    try:
        with hou.InterruptableOperation(
            "Rendering Bria Sequence",
            "Rendering frame",
            open_interrupt_dialog=True,
        ) as op:
            for i, frame in enumerate(frames):
                op.updateProgress(i / total)
                op.updateLongProgress(
                    -1,
                    f"Frame {frame} ({i + 1}/{total}) — {chain_desc}",
                )
                if status_parm:
                    status_parm.set(f"Frame {frame} ({i + 1}/{total})")
                _flush_ui()

                hou.setFrame(frame)

                try:
                    _cook_frame(node, chain, output_path)
                except Exception as exc:
                    msg = f"Frame {frame}: {_safe_exc_str(exc)}"
                    logger.error("[Bria Sequence] %s", msg)
                    errors.append(msg)

                # Update bar after frame completes and flush so it repaints.
                op.updateProgress((i + 1) / total)
                _flush_ui()

    except hou.OperationInterrupted:
        logger.info("[Bria Sequence] Cancelled by user at frame %d", frame)
        if status_parm:
            status_parm.set(f"Cancelled at frame {frame}")
        hou.ui.setStatusMessage(
            f"Bria Sequence cancelled at frame {frame} ({i}/{total} completed)"
        )
        return
    finally:
        # Restore original frame.
        hou.setFrame(original_frame)

    # Done.
    if status_parm:
        status_parm.set("Done!" if not errors else f"Done with {len(errors)} error(s)")

    if errors:
        error_text = "\n".join(errors[:20])
        if len(errors) > 20:
            error_text += f"\n... and {len(errors) - 20} more"
        hou.ui.displayMessage(
            f"Bria Sequence completed {total - len(errors)}/{total} frames.\n\n"
            f"Errors:\n{error_text}",
            severity=hou.severityType.Warning,
            title="Bria Sequence Output",
        )
    else:
        hou.ui.setStatusMessage(
            f"Bria Sequence complete: {total} frames → {output_path}"
        )


# ---------------------------------------------------------------------------
# Per-frame cook
# ---------------------------------------------------------------------------

def _cook_frame(node: Any, chain: List[Tuple[str, Any]], output_path: str) -> None:
    """Process one frame: trigger each Bria node, then export final output."""
    import hou

    for bria_type, bria_node in chain:
        t0 = time.perf_counter()

        # VGL nodes with Lock VGL enabled skip regeneration.
        if bria_type == "generate_vgl":
            locked = opt_parm_bool(bria_node, "lock_vgl")
            if locked:
                logger.info("[Bria Sequence] %s (%s) locked — skipping", bria_type, bria_node.path())
                continue

        # 1. Export this Bria node's COP input(s) to temp file(s).
        #    Generate and VGL nodes don't require an input image.
        input_path = None
        if bria_type not in ("fibo_generate", "generate_vgl"):
            input_path = _export_node_input(bria_node)
        mask_path = None
        if bria_type in ("erase", "genfill"):
            mask_path = _export_node_mask(bria_node)

        # 2. Read parameters and call the appropriate adapter function.
        api_data = _dispatch_cook(bria_type, bria_node, input_path, mask_path)

        # 3. VGL nodes update result_json and push downstream; image nodes download.
        if bria_type == "generate_vgl":
            _apply_vgl_result(bria_node, api_data)
        else:
            _download_and_apply(bria_node, api_data, bria_type)

        elapsed = time.perf_counter() - t0
        logger.info(
            "[Bria Sequence] %s (%s) done in %.1fs",
            bria_type, bria_node.path(), elapsed,
        )

    # 4. Export final composited result to output path.
    resolved = hou.expandString(output_path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)

    _export_final_output(node, chain, resolved)
    logger.info("[Bria Sequence] Frame output: %s", resolved)


def _find_nearest_upstream_result(node: Any) -> Optional[str]:
    """Walk upstream from *node* to find the nearest Bria node with a valid result_path."""
    visited: Set[Any] = set()
    queue = list(node.inputs() or [])
    while queue:
        current = queue.pop(0)
        if current is None or current in visited:
            continue
        visited.add(current)
        rp = current.parm("result_path")
        if rp is not None:
            path = (rp.eval() or "").strip()
            if path and os.path.isfile(path):
                return path
        for inp in current.inputs() or []:
            if inp is not None:
                queue.append(inp)
    return None


# ---------------------------------------------------------------------------
# COP input/output export helpers
# ---------------------------------------------------------------------------

def _export_node_input(bria_node: Any) -> str:
    """Export a Bria COP node's primary input (input 0) to a temp PNG."""
    tmp = os.path.join(tempfile.gettempdir(), f"bria_seq_in_{uuid.uuid4().hex[:8]}.png")

    # Tier 1: internal ROP (cooks the full upstream chain).
    result = export_via_internal_rop(bria_node, "rop_save_input", tmp)
    if result and os.path.exists(result):
        return result

    # Tier 2: direct COP pixel export from input node.
    inputs = bria_node.inputs()
    input_op = inputs[0] if inputs else None
    if input_op is not None:
        result = cop_to_png(input_op, tmp)
        if result and os.path.exists(result):
            return result

    raise RuntimeError(
        f"Could not export input for {bria_node.path()}. "
        "Ensure the node has a connected input."
    )


def _export_node_mask(bria_node: Any) -> Optional[str]:
    """Export a Bria COP node's mask input (input 1) to a temp PNG."""
    tmp = os.path.join(tempfile.gettempdir(), f"bria_seq_mask_{uuid.uuid4().hex[:8]}.png")

    # Tier 1: internal mask ROP.
    result = export_via_internal_rop(bria_node, "rop_save_mask", tmp)
    if result and os.path.exists(result):
        return result

    # Tier 2: check input 1 node directly.
    inputs = bria_node.inputs()
    mask_op = inputs[1] if len(inputs) > 1 else None
    if mask_op is not None:
        # Check if mask node has a file on disk.
        found = _find_image_path_on_node(mask_op)
        if found:
            return found
        # Direct COP export.
        result = cop_to_png(mask_op, tmp)
        if result and os.path.exists(result):
            return result

    return None


def _export_final_output(node: Any, chain: List[Tuple[str, Any]], output_path: str) -> None:
    """Export the Sequence Output node's final composited result.

    Strategy:
    1. Internal ROP (rop_save_input) — renders the full upstream COP network
       including Houdini compositing nodes (over, screen, etc.).
    2. Direct COP pixel export from the input node.
    3. Nearest upstream Bria node's result_path (simple chains with no compositing).
    """
    import shutil

    inputs = node.inputs()
    input_op = inputs[0] if inputs else None
    if input_op is None:
        raise RuntimeError("Bria Sequence Output has no connected input to export.")

    # Tier 1: Internal ROP — renders the full composite.
    result = export_via_internal_rop(node, "rop_save_input", output_path)
    if result and os.path.isfile(result):
        if os.path.abspath(result) != os.path.abspath(output_path):
            shutil.copyfile(result, output_path)
        return

    # Tier 2: Direct COP pixel export.
    result = cop_to_png(input_op, output_path)
    if result and os.path.isfile(result):
        return

    # Tier 3: Walk upstream to find nearest Bria node's result_path.
    result_file = _find_nearest_upstream_result(node)
    if result_file:
        shutil.copyfile(result_file, output_path)
        return

    raise RuntimeError(f"Failed to export final output to {output_path}")


# ---------------------------------------------------------------------------
# Per-type cook dispatch
# ---------------------------------------------------------------------------

def _dispatch_cook(
    bria_type: str,
    cop_node: Any,
    input_path: str,
    mask_path: Optional[str] = None,
) -> Dict:
    """Read parameters from *cop_node* and call the appropriate Bria API."""
    cook_fn = _COOK_TABLE.get(bria_type)
    if cook_fn is None:
        raise RuntimeError(f"Unknown Bria node type: {bria_type} ({cop_node.path()})")
    return cook_fn(cop_node, input_path, mask_path)


def _read_connection_params(cop_node: Any) -> Tuple[Optional[str], Optional[str], bool, Optional[Dict]]:
    """Read API key, endpoint, bearer auth, and proxy settings from a COP node."""
    api_key = opt_parm_str(cop_node, "api_token") or None
    api_endpoint = opt_parm_str(cop_node, "api_base_url") or None
    use_bearer = bool(opt_parm_bool(cop_node, "use_bearer_auth"))

    http_proxy = opt_parm_str(cop_node, "http_proxy")
    https_proxy = opt_parm_str(cop_node, "https_proxy")
    use_env_proxy = opt_parm_bool(cop_node, "use_env_proxy")
    proxies = resolve_proxies(http_proxy, https_proxy, use_env_proxy)

    return api_key, api_endpoint, use_bearer, proxies


# -- Enhancer ---------------------------------------------------------------

def _cook_enhancer(cop_node: Any, input_path: str, _mask: Any) -> Dict:
    resolution = opt_parm_menu_str(cop_node, "resolution") or "1MP"
    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    steps_num = clamp_steps_num(opt_parm_int(cop_node, "steps_num"))
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return upscale_from_files(
        image_path=input_path,
        mode="enhance",
        resolution=resolution,
        preserve_alpha=preserve_alpha,
        seed=seed,
        steps_num=steps_num,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- FIBO Edit (also used for FIBO Edit Recipes) ----------------------------

def _cook_fibo_edit(cop_node: Any, input_path: str, _mask: Any) -> Dict:
    prompt = (opt_parm_str(cop_node, "prompt") or "").strip()
    structured_prompt = (opt_parm_str(cop_node, "structured_prompt") or "").strip()
    negative_prompt = (opt_parm_str(cop_node, "negative_prompt") or "").strip()

    # Respect toggle parms if present.
    if opt_parm_bool(cop_node, "use_basic_prompt") is False:
        prompt = ""
    if opt_parm_bool(cop_node, "use_structured_prompt") is False:
        structured_prompt = ""
    if opt_parm_bool(cop_node, "enable_negative_prompt") is False:
        negative_prompt = ""

    if not prompt and not structured_prompt:
        raise RuntimeError(
            f"FIBO Edit ({cop_node.path()}): no prompt or structured prompt set."
        )

    guidance_scale = opt_parm_int(cop_node, "guidance_scale")
    if guidance_scale is not None and guidance_scale > 0:
        guidance_scale = min(guidance_scale, 5)
    else:
        guidance_scale = None
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    steps_num = clamp_steps_num(opt_parm_int(cop_node, "steps_num"))
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return fibo_edit_from_files(
        image_path=input_path,
        prompt=prompt or None,
        structured_prompt=structured_prompt or None,
        guidance_scale=guidance_scale,
        negative_prompt=negative_prompt or None,
        seed=seed,
        steps_num=steps_num,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- FIBO Generate -----------------------------------------------------------

def _cook_fibo_generate(cop_node: Any, _input_path: str, _mask: Any) -> Dict:
    prompt = (opt_parm_str(cop_node, "prompt") or "").strip()
    structured_prompt = (opt_parm_str(cop_node, "structured_prompt") or "").strip()
    negative_prompt = (opt_parm_str(cop_node, "negative_prompt") or "").strip()

    # Respect mode toggles — match interactive node behavior
    use_basic = opt_parm_bool(cop_node, "use_basic_prompt")
    use_struct = opt_parm_bool(cop_node, "use_structured_prompt")
    if use_basic is False:
        prompt = ""
    if use_struct is False:
        structured_prompt = ""

    if not prompt and not structured_prompt:
        raise RuntimeError(
            f"FIBO Generate ({cop_node.path()}): no prompt or structured prompt set."
        )

    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    guidance_scale = opt_parm_int(cop_node, "guidance_scale") or 5
    if guidance_scale > 0:
        guidance_scale = min(guidance_scale, 5)
    steps_num = clamp_steps_num(opt_parm_int(cop_node, "steps_num"))
    aspect_ratio = opt_parm_menu_str(cop_node, "aspect_ratio") or "1:1"
    pipeline = opt_parm_menu_str(cop_node, "pipeline") or "standard"
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    payload: Dict[str, Any] = {}
    use_structured = False
    if structured_prompt:
        payload["structured_prompt"] = structured_prompt
        use_structured = True
    elif prompt:
        payload["prompt"] = prompt
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if seed is not None:
        payload["seed"] = seed
    if guidance_scale:
        payload["guidance_scale"] = guidance_scale
    if steps_num:
        payload["steps_num"] = steps_num

    return fibo_generate_from_payload(
        payload=payload,
        pipeline=pipeline,
        use_structured_prompt=use_structured,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- Expand ------------------------------------------------------------------

def _cook_expand(cop_node: Any, input_path: str, _mask: Any) -> Dict:
    prompt = (opt_parm_str(cop_node, "prompt") or "").strip() or None
    negative_prompt = (opt_parm_str(cop_node, "negative_prompt") or "").strip() or None
    if opt_parm_bool(cop_node, "enable_negative_prompt") is False:
        negative_prompt = None

    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    fast = opt_parm_bool(cop_node, "fast")
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    cm_prompt = opt_parm_bool(cop_node, "content_moderation_prompt")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    # Expansion mode determines which API params to send.
    expansion_mode = opt_parm_menu_str(cop_node, "expansion_mode") or "aspect_ratio"

    aspect_ratio = None
    original_image_size = None
    original_image_location = None
    canvas_size = None

    if expansion_mode == "aspect_ratio":
        aspect_ratio = opt_parm_menu_str(cop_node, "aspect_ratio")
    elif expansion_mode == "directional":
        el = opt_parm_int(cop_node, "expand_left") or 0
        er = opt_parm_int(cop_node, "expand_right") or 0
        et = opt_parm_int(cop_node, "expand_top") or 0
        eb = opt_parm_int(cop_node, "expand_bottom") or 0
        # Directional expansion is converted to canvas_size + image location.
        # Read image dimensions to compute canvas.
        try:
            from PIL import Image
            with Image.open(input_path) as img:
                w, h = img.size
        except Exception:
            w, h = 1024, 1024
        canvas_size = [w + el + er, h + et + eb]
        original_image_size = {"width": w, "height": h}
        original_image_location = {"x": el, "y": et}
    elif expansion_mode == "canvas_size":
        cw = opt_parm_int(cop_node, "canvas_width") or 0
        ch = opt_parm_int(cop_node, "canvas_height") or 0
        if cw > 0 and ch > 0:
            canvas_size = [cw, ch]
        anchor = opt_parm_menu_str(cop_node, "anchor")
        # Anchor determines original_image_location relative to canvas.
        try:
            from PIL import Image
            with Image.open(input_path) as img:
                w, h = img.size
        except Exception:
            w, h = 1024, 1024
        original_image_size = {"width": w, "height": h}
        if anchor and canvas_size:
            original_image_location = _anchor_to_location(
                anchor, w, h, canvas_size[0], canvas_size[1]
            )

    return expand_from_files(
        image_path=input_path,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        original_image_size=original_image_size,
        original_image_location=original_image_location,
        canvas_size=canvas_size,
        seed=seed,
        negative_prompt=negative_prompt,
        preserve_alpha=preserve_alpha,
        fast=fast,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        content_moderation_prompt=cm_prompt,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


def _anchor_to_location(
    anchor: str, img_w: int, img_h: int, canvas_w: int, canvas_h: int
) -> Dict[str, int]:
    """Convert an anchor position string to an (x, y) location dict."""
    anchor = (anchor or "center").lower().replace("-", "_")
    dx = canvas_w - img_w
    dy = canvas_h - img_h
    cx, cy = dx // 2, dy // 2

    positions = {
        "top_left": (0, 0),
        "top_center": (cx, 0),
        "top_right": (dx, 0),
        "center_left": (0, cy),
        "center": (cx, cy),
        "center_right": (dx, cy),
        "bottom_left": (0, dy),
        "bottom_center": (cx, dy),
        "bottom_right": (dx, dy),
    }
    x, y = positions.get(anchor, (cx, cy))
    return {"x": max(0, x), "y": max(0, y)}


# -- RMBG --------------------------------------------------------------------

def _cook_rmbg(cop_node: Any, input_path: str, _mask: Any) -> Dict:
    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    keep_original_size = opt_parm_bool(cop_node, "keep_original_size")
    force_bg_detection = opt_parm_bool(cop_node, "force_bg_detection")
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return remove_background_from_files(
        image_path=input_path,
        preserve_alpha=bool(preserve_alpha) if preserve_alpha is not None else True,
        keep_original_size=keep_original_size,
        force_bg_detection=force_bg_detection,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- Erase -------------------------------------------------------------------

def _cook_erase(cop_node: Any, input_path: str, mask_path: Optional[str]) -> Dict:
    if not mask_path:
        raise RuntimeError(
            f"Erase ({cop_node.path()}): mask input required but could not be exported. "
            "Ensure a mask is connected to input 2."
        )

    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return erase_from_files(
        image_path=input_path,
        mask_path=mask_path,
        preserve_alpha=bool(preserve_alpha) if preserve_alpha is not None else True,
        seed=seed,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- Upscale -----------------------------------------------------------------

def _cook_upscale(cop_node: Any, input_path: str, _mask: Any) -> Dict:
    desired_resolution = opt_parm_menu_str(cop_node, "desired_resolution") or "2x"
    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return upscale_from_files(
        image_path=input_path,
        mode="increase_resolution",
        desired_resolution=desired_resolution,
        preserve_alpha=preserve_alpha,
        seed=seed,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- GenFill -----------------------------------------------------------------

def _cook_genfill(cop_node: Any, input_path: str, mask_path: Optional[str]) -> Dict:
    if not mask_path:
        raise RuntimeError(
            f"GenFill ({cop_node.path()}): mask input required but could not be exported. "
            "Ensure a mask is connected to input 2."
        )

    prompt = (opt_parm_str(cop_node, "prompt") or "").strip()
    if not prompt:
        raise RuntimeError(
            f"GenFill ({cop_node.path()}): prompt is required."
        )

    negative_prompt = (opt_parm_str(cop_node, "negative_prompt") or "").strip() or None
    if opt_parm_bool(cop_node, "enable_negative_prompt") is False:
        negative_prompt = None
    preserve_alpha = opt_parm_bool(cop_node, "preserve_alpha")
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None
    refine_prompt = opt_parm_bool(cop_node, "refine_prompt")
    fast = opt_parm_bool(cop_node, "fast")
    keep_original_size = opt_parm_bool(cop_node, "keep_original_size")
    tailored_model_id = opt_parm_str(cop_node, "tailored_model_id") or None
    cm_in = opt_parm_bool(cop_node, "content_moderation_input")
    cm_out = opt_parm_bool(cop_node, "content_moderation_output")
    cm_prompt = opt_parm_bool(cop_node, "content_moderation_prompt")
    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return genfill_from_files(
        image_path=input_path,
        mask_path=mask_path,
        prompt=prompt,
        negative_prompt=negative_prompt,
        preserve_alpha=bool(preserve_alpha) if preserve_alpha is not None else True,
        seed=seed,
        refine_prompt=refine_prompt,
        fast=fast,
        keep_original_size=keep_original_size,
        tailored_model_id=tailored_model_id,
        content_moderation_input=cm_in,
        content_moderation_output=cm_out,
        content_moderation_prompt=cm_prompt,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- Generate VGL ------------------------------------------------------------

def _cook_generate_vgl(cop_node: Any, _input_path: str, _mask: Any) -> Dict:
    from bria_houdini.adapter import generate_structured_prompt
    from bria_houdini.cop_export import cop_to_png, export_via_internal_rop

    prompt = (opt_parm_str(cop_node, "prompt") or "").strip()
    seed = opt_parm_int(cop_node, "seed")
    if seed is not None and seed <= 0:
        seed = None

    image_path = None
    inputs = cop_node.inputs()
    input_op = inputs[0] if inputs else None
    if input_op is not None:
        tmp = os.path.join(tempfile.gettempdir(), f"bria_seq_vgl_in_{uuid.uuid4().hex[:8]}.png")
        image_path = (
            export_via_internal_rop(cop_node, "rop_save_input", tmp)
            or cop_to_png(input_op, tmp)
        )

    if not prompt and not image_path:
        raise RuntimeError(f"Generate VGL ({cop_node.path()}): no prompt or image input.")

    api_key, api_endpoint, use_bearer, proxies = _read_connection_params(cop_node)

    return generate_structured_prompt(
        prompt=prompt or None,
        image_path=image_path,
        seed=seed,
        api_key=api_key,
        api_endpoint=api_endpoint,
        use_bearer=use_bearer,
        proxies=proxies,
    )


# -- Dispatch table ----------------------------------------------------------

_COOK_TABLE: Dict[str, Any] = {
    "enhancer": _cook_enhancer,
    "fibo_edit": _cook_fibo_edit,
    "fibo_generate": _cook_fibo_generate,
    "generate_vgl": _cook_generate_vgl,
    "expand": _cook_expand,
    "rmbg": _cook_rmbg,
    "erase": _cook_erase,
    "upscale": _cook_upscale,
    "genfill": _cook_genfill,
}


# ---------------------------------------------------------------------------
# Result download + apply
# ---------------------------------------------------------------------------

def _download_and_apply(bria_node: Any, api_data: Dict, bria_type: str) -> str:
    """Download the API result image and set ``result_path`` synchronously."""
    import hou

    dl_url = extract_image_url(api_data)
    if not dl_url:
        raise RuntimeError(
            f"No image_url in API response for {bria_type} ({bria_node.path()}): "
            f"{api_data}"
        )

    img_bytes, content_type = download_url(dl_url, timeout_s=300)

    # Save to a temp file.
    run_id = uuid.uuid4().hex[:8]
    out_dir = tempfile.gettempdir()
    out_path = os.path.join(out_dir, f"bria_seq_{bria_type}_{run_id}.png")
    out_path = resolve_result_save_path(out_path, content_type)

    with open(out_path, "wb") as fh:
        fh.write(img_bytes)

    # Set result_path directly — we're on the main thread, no defer needed.
    rp = bria_node.parm("result_path")
    if rp is not None:
        rp.set(out_path)

    # Clear texture/GL caches so downstream COP nodes see the new image.
    try:
        hou.hscript("texcache -c")
        hou.hscript("glcache -c")
    except Exception:
        pass

    # Save metadata sidecar.
    try:
        save_api_metadata(out_path, api_data, f"seq_{bria_type}")
    except Exception:
        pass

    return out_path


def _apply_vgl_result(bria_node: Any, api_data: Dict) -> None:
    """Extract structured prompt from API response and push to downstream nodes."""
    import json

    result = api_data.get("result", {})
    if isinstance(result, dict):
        structured_prompt = result.get("structured_prompt")
    else:
        structured_prompt = api_data.get("structured_prompt")
    if structured_prompt is None:
        raise RuntimeError(f"No structured_prompt in API response for {bria_node.path()}")

    if isinstance(structured_prompt, dict):
        result_json = json.dumps(structured_prompt, indent=2)
    elif isinstance(structured_prompt, str):
        try:
            result_json = json.dumps(json.loads(structured_prompt), indent=2)
        except Exception:
            result_json = structured_prompt
    else:
        result_json = json.dumps(structured_prompt, indent=2, default=str)

    rj = bria_node.parm("result_json")
    if rj is not None:
        rj.set(result_json)

    for output_node in bria_node.outputs():
        sp = output_node.parm("structured_prompt")
        if sp is not None:
            sp.set(result_json)
            try:
                phm = output_node.hdaModule()
                if hasattr(phm, "on_parse_vgl"):
                    phm.on_parse_vgl({"node": output_node})
            except Exception:
                pass

    logger.info("[Bria Sequence] VGL updated on %s and pushed downstream", bria_node.path())


# ---------------------------------------------------------------------------
# UI callbacks (wired into the HDA's PythonModule)
# ---------------------------------------------------------------------------

def on_render(kwargs: dict) -> None:
    """Callback for the 'Render Bria Sequence To Disk' button."""
    node = kwargs.get("node")
    if node is None:
        return
    render_sequence(node)


def on_refresh_chain(kwargs: dict) -> None:
    """Callback for the 'Refresh Chain Info' button."""
    node = kwargs.get("node")
    if node is None:
        return

    chain_parm = node.parm("chain_info")
    if chain_parm is None:
        return

    try:
        chain = discover_upstream_bria_dag(node)
    except Exception as exc:
        chain_parm.set(f"Error: {_safe_exc_str(exc)}")
        return

    if not chain:
        chain_parm.set("No Bria COP nodes found upstream.")
        return

    lines = [f"{len(chain)} Bria node(s) detected:"]
    for i, (btype, bnode) in enumerate(chain, 1):
        lines.append(f"  {i}. {btype} ({bnode.name()})")
    chain_parm.set("\n".join(lines))
