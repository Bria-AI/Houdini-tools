"""
Bria Viewport Render HDA Implementation.

This module provides the core logic for capturing the Houdini 3D viewport
and rendering it using Bria's FIBO Edit AI with a text prompt.
"""

import logging
import os
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from typing import Optional

from bria_houdini.bria_core.utils import download_url, extract_image_url, resolve_temp_dir
from bria_houdini.adapter import fibo_edit_from_files
from bria_houdini.node_utils import _safe_exc_str, clamp_steps_num

logger = logging.getLogger(__name__)

# Output directory configuration (runtime temp location)
DEFAULT_OUTPUT_DIR = ""

# ---------------------------------------------------------------------------
# Supported FIBO Edit resolutions (width x height)
# ---------------------------------------------------------------------------
SUPPORTED_RESOLUTIONS = {
    "1024x1024": (1024, 1024),    # 1:1 Square
    "1152x768":  (1152, 768),     # 3:2 Landscape
    "768x1152":  (768, 1152),     # 2:3 Portrait
    "1024x768":  (1024, 768),     # 4:3 Landscape
    "768x1024":  (768, 1024),     # 3:4 Portrait
    "960x768":   (960, 768),      # 5:4 Landscape
    "768x960":   (768, 960),      # 4:5 Portrait
    "1024x576":  (1024, 576),     # 16:9 Wide
    "576x1024":  (576, 1024),     # 9:16 Tall
}


def find_closest_resolution(width: int, height: int) -> tuple[int, int]:
    """Find the closest supported FIBO Edit resolution for a given width/height.

    Compares by aspect ratio similarity first, then pixel count.
    """
    if width <= 0 or height <= 0:
        return 1024, 1024
    target_ratio = width / height
    best = (1024, 1024)
    best_score = float("inf")
    for w, h in SUPPORTED_RESOLUTIONS.values():
        ratio_diff = abs((w / h) - target_ratio)
        area_diff = abs((w * h) - (width * height)) / 1e6
        score = ratio_diff * 10 + area_diff  # Weight aspect ratio heavily
        if score < best_score:
            best_score = score
            best = (w, h)
    return best


# ---------------------------------------------------------------------------
# Viewport Render Preset Categories
# ---------------------------------------------------------------------------
CATEGORY_ORDER = [
    ("custom",          "Custom"),
    ("vfx_simulations", "VFX Simulations"),
    ("environments",    "Environments"),
    ("lighting_mood",   "Lighting & Mood"),
    ("stylized",        "Stylized"),
]

PRESET_CATEGORIES = {
    # ---- VFX Simulations (5) ----
    "vfx_simulations": [
        ("destruction", "Destruction & Debris",
         "Render this destruction simulation as a photorealistic scene with realistic material fracturing, concrete dust clouds, scattered debris with naturally varied textures and irregular placement, dramatic directional lighting, and cinematic motion blur. Ensure debris distribution looks organic and chaotic, not grid-aligned."),
        ("water_ocean", "Water & Ocean",
         "Render this water simulation as a photorealistic ocean scene with transparent refractive water, realistic foam and spray with naturally irregular patterns, caustic light patterns, subsurface scattering, and natural coastal lighting. Water surface detail should be organically varied, no repeating wave patterns."),
        ("pyro_fire", "Fire & Explosions",
         "Render this fire simulation as a photorealistic scene with intense volumetric flames, glowing embers with naturally scattered trajectories, heat distortion, realistic fire illumination on surrounding surfaces, and dramatic contrast between fire and shadow. Flame shapes should be organically varied and chaotic."),
        ("smoke_clouds", "Smoke & Clouds",
         "Render this smoke simulation as a photorealistic atmospheric scene with soft volumetric density, realistic light scattering through the volume, subtle color gradients, natural dissipation at the edges, and cinematic depth. Cloud and smoke shapes should be organically irregular with no repeating density patterns."),
        ("particles", "Particles & Sparks",
         "Render this particle simulation as a photorealistic scene with glowing sparks, motion-streaked trajectories with naturally varied spacing, realistic light emission, soft bokeh on distant particles, and dramatic contrast. Particle distribution should look naturally random, not grid-aligned."),
    ],

    # ---- Environments (6) ----
    "environments": [
        ("landscape_mountains", "Mountain Landscape",
         "Render this landscape as a photorealistic and lush mountain vista with waterways, rocky areas, and areas completely covered in natural plant growth, atmospheric haze in distant valleys, natural vegetation with organically varied distribution, volumetric cloud shadows, and epic awe-inspiring cinematic nature photograph. Ensure vegetation and rock placement is natural with no repeating patterns."),
        ("landscape_forest", "Forest & Vegetation",
         "Render this scene as a photorealistic forest environment with detailed foliage in naturally varied clusters, dappled light filtering through the canopy, rich ground cover with organic irregularity, varied bark textures, and lush natural atmosphere. Tree and plant placement must look naturally random, no grid patterns."),
        ("landscape_desert", "Desert & Arid",
         "Render this scene as a photorealistic desert landscape with naturally varied sand textures and ripple patterns, heat shimmer, dramatic rock formations with organic weathering, harsh directional sunlight, and vast arid atmosphere. Surface detail should be irregularly distributed, no tiling patterns."),
        ("landscape_coastal", "Coastal & Beach",
         "Render this scene as a photorealistic coastal environment with turquoise water, wet sand reflections with natural irregularity, detailed shoreline foam with organic edge patterns, naturally scattered coastal vegetation, and warm oceanic atmosphere. No repeating patterns in water or sand detail."),
        ("building_exterior", "Building Exterior",
         "Render this architecture as a photorealistic building exterior with detailed material surfaces, accurate window reflections, natural weathering with organic irregularity, surrounding landscaping with naturally varied plant placement, and realistic environmental lighting. Vegetation and ground detail should look naturally distributed."),
        ("building_interior", "Building Interior",
         "Render this interior as a photorealistic room with accurate material textures showing natural variation, natural light from windows with soft gradients, subtle ambient occlusion, realistic furniture detail, and warm inviting atmosphere. Surface textures should have organic variation, no repeating tile patterns."),
    ],

    # ---- Lighting & Mood (6) ----
    "lighting_mood": [
        ("golden_hour", "Golden Hour",
         "Render this scene in golden hour lighting with rich warm amber sunlight, long dramatic shadows with natural falloff, glowing rim light on surfaces, soft atmospheric haze, and cinematic warmth. All surface detail and textures should appear naturally varied and organic."),
        ("night_scene", "Night Scene",
         "Render this scene as a photorealistic night environment with deep blue ambient light, practical light sources casting pools of warm illumination with natural falloff, subtle moonlight, realistic shadow gradients, and atmospheric night mood. Surface and environmental detail should be organically varied."),
        ("studio_lighting", "Studio Lighting",
         "Render this scene with professional studio lighting featuring clean three-point setup, soft key light, subtle fill, defined rim separation, neutral background, and polished product-photography quality. Material surfaces should show natural micro-variation, no repeating texture patterns."),
        ("overcast_soft", "Overcast & Soft",
         "Render this scene under soft overcast lighting with even diffused illumination, gentle shadow gradients, muted natural color with organic variation, and calm atmospheric mood. Surface detail should appear naturally varied and irregular."),
        ("dramatic_contrast", "Dramatic & High Contrast",
         "Render this scene with dramatic high-contrast lighting featuring bold directional light, deep expressive shadows with natural falloff, strong chiaroscuro, and cinematic intensity. All textures and surface detail should be organically varied."),
        ("neon_urban", "Neon & Urban Night",
         "Render this scene as a neon-lit urban night environment with vivid colored light reflections on wet surfaces showing natural irregularity, atmospheric fog catching light beams, cyberpunk-inspired mood, and high-contrast electric atmosphere. Surface reflections and detail should be organically varied, no repeating patterns."),
    ],

    # ---- Stylized (5) ----
    "stylized": [
        ("motion_graphics", "Motion Graphics",
         "Render this scene as a polished motion graphics piece with clean geometric forms, smooth material surfaces with subtle natural variation, vibrant brand-friendly colors, precise studio lighting, and sleek contemporary design aesthetic. Surface quality should be refined with organic micro-detail."),
        ("abstract_procedural", "Abstract Procedural Art",
         "Render this procedural pattern as detailed abstract art with rich material textures showing organic variation, iridescent surface qualities, dramatic focused lighting, flowing forms with natural irregularity, and gallery-quality artistic presentation. Transform any repeating patterns into organically varied artistic detail."),
        ("concept_art", "Concept Art",
         "Render this scene as professional concept art with painterly detail and organic brushwork quality, atmospheric perspective, rich color palette, dramatic composition lighting, and the polished quality of feature-film pre-production artwork. Detail distribution should feel hand-crafted and naturally varied."),
        ("architectural_viz", "Architectural Visualization",
         "Render this scene as a professional architectural visualization with photorealistic material accuracy showing natural micro-variation, precise natural lighting, clean geometric detail, subtle ambient occlusion, and high-end real estate presentation quality. Surrounding landscaping should have naturally varied plant placement."),
        ("product_render", "Product Render",
         "Render this object as a professional product photograph with pristine material surfaces showing subtle natural variation, precise studio lighting, subtle reflections with organic quality, clean background separation, and commercial advertising quality."),
    ],
}

# Flat lookup: preset_token → prompt_text
ALL_PRESETS = {
    token: prompt
    for presets in PRESET_CATEGORIES.values()
    for token, _label, prompt in presets
}


def get_output_directory() -> str:
    """
    Get the output directory for render results.

    Returns:
        Normalized path to output directory (creates if needed)
    """
    from bria_houdini.node_utils import _desktop_output_dir

    output_dir = _desktop_output_dir()
    if not output_dir:
        try:
            import hou
            output_dir = resolve_temp_dir(hou)
        except Exception:
            output_dir = tempfile.gettempdir()

    os.makedirs(output_dir, exist_ok=True)
    return output_dir.replace("\\", "/")


def extract_noun_from_prompt(prompt: str) -> str:
    """
    Extract the primary noun from a style prompt for file naming.

    Skips common style/modifier words and returns first meaningful word.

    Args:
        prompt: The style prompt text

    Returns:
        A sanitized noun suitable for filename (lowercase, alphanumeric only)
    """
    import re

    if not prompt:
        return "render"

    # Common words to skip
    skip_words = {
        'a', 'an', 'the', 'with', 'and', 'or', 'in', 'on', 'of', 'for', 'as', 'at',
        'photorealistic', 'realistic', 'cinematic', 'professional', 'artistic',
        'detailed', 'high', 'quality', 'lighting', 'rendering', 'rendered',
        'style', 'styled', 'aesthetic', 'look', 'effect', 'effects',
        'beautiful', 'stunning', 'dramatic', 'vibrant', 'soft', 'hard',
        'bright', 'dark', 'warm', 'cool', 'moody', 'atmospheric'
    }

    # Clean and tokenize
    clean = re.sub(r'[^a-zA-Z\s]', '', prompt.lower())
    words = clean.split()

    # Find first meaningful word
    for word in words:
        if word not in skip_words and len(word) > 2:
            # Sanitize for filename (only lowercase alphanumeric)
            sanitized = re.sub(r'[^a-z0-9]', '', word)[:20]
            if sanitized:
                return sanitized

    return "render"


def get_next_version_number(output_dir: str, noun: str) -> int:
    """
    Find the next available version number for a given noun.

    Scans existing files matching pattern: bria_render_{noun}_##.png

    Args:
        output_dir: Directory to scan
        noun: The noun used in filename

    Returns:
        Next version number (1 if no existing files)
    """
    import glob
    import re

    pattern = os.path.join(output_dir, f"bria_render_{noun}_*.png")
    existing = glob.glob(pattern)

    max_version = 0
    version_pattern = re.compile(rf"bria_render_{noun}_(\d+)\.png$")

    for filepath in existing:
        match = version_pattern.search(os.path.basename(filepath))
        if match:
            version = int(match.group(1))
            max_version = max(max_version, version)

    return max_version + 1


def generate_result_path(prompt: str) -> str:
    """
    Generate a result path with smart naming based on the prompt.

    Args:
        prompt: The style prompt text

    Returns:
        Full path for the result image
    """
    output_dir = get_output_directory()
    noun = extract_noun_from_prompt(prompt)
    version = get_next_version_number(output_dir, noun)
    filename = f"bria_render_{noun}_{version:02d}.png"
    return os.path.join(output_dir, filename).replace("\\", "/")


def _find_parm(node, *names: str):
    for name in names:
        try:
            parm = node.parm(name)
        except Exception:
            parm = None
        if parm is not None:
            return parm
    return None


def _eval_parm_str(node, *names: str) -> str:
    parm = _find_parm(node, *names)
    if parm is None:
        return ""
    try:
        return str(parm.evalAsString() or "").strip()
    except Exception:
        try:
            return str(parm.eval() or "").strip()
        except Exception:
            return ""


def _eval_parm_int(node, *names: str) -> Optional[int]:
    parm = _find_parm(node, *names)
    if parm is None:
        return None
    try:
        return int(parm.eval())
    except Exception:
        return None


def _eval_parm_float(node, *names: str) -> Optional[float]:
    parm = _find_parm(node, *names)
    if parm is None:
        return None
    try:
        return float(parm.eval())
    except Exception:
        return None


def _eval_parm_bool(node, *names: str, default: bool = False) -> bool:
    parm = _find_parm(node, *names)
    if parm is None:
        return bool(default)
    try:
        return bool(parm.eval())
    except Exception:
        return bool(default)


def _resolution_wh_from_node(node) -> tuple[int, int]:
    import re

    resolution_str = _eval_parm_str(node, "resolution")
    if not resolution_str:
        return 1024, 1024

    try:
        nums = re.findall(r"\d+", str(resolution_str))
        if len(nums) >= 2:
            width = int(nums[0])
            height = int(nums[1])
            if width > 0 and height > 0:
                return width, height
    except Exception as e:
        logger.debug("Resolution parse error: %s", _safe_exc_str(e))

    logger.warning("Could not parse resolution '%s'; falling back to 1024x1024.", resolution_str)
    return 1024, 1024


def _set_camera_resolution(camera_node, width: int, height: int) -> None:
    try:
        resx = camera_node.parm("resx")
        resy = camera_node.parm("resy")
        if resx is not None:
            resx.set(int(width))
        if resy is not None:
            resy.set(int(height))
    except Exception as e:
        logger.debug("Failed to set camera resolution: %s", _safe_exc_str(e))


def _is_camera_node(node) -> bool:
    if node is None:
        return False
    try:
        if node.parm("aperture") is not None and node.parm("focal") is not None:
            return True
    except Exception:
        pass
    try:
        type_name = node.type().name().lower()
        if "cam" in type_name:
            return True
    except Exception:
        pass
    return False


def resolve_render_camera(node):
    """Resolve projection/render camera with deterministic priority.

    Priority:
    1) explicit camera parm on node (camera_path/camera/capture_camera)
    2) this node itself when it is a camera HDA
    3) legacy fallback camera /obj/bria_render_camera
    """
    import hou

    for parm_name in ("camera_path", "camera", "capture_camera"):
        try:
            parm = node.parm(parm_name)
            if parm is None:
                continue
            raw = (parm.evalAsString() or "").strip()
            if not raw:
                continue
            cam = hou.node(raw)
            if cam is not None and _is_camera_node(cam):
                return cam
        except Exception:
            continue

    if _is_camera_node(node):
        return node

    try:
        fallback = hou.node("/obj/bria_render_camera")
        if fallback is not None and _is_camera_node(fallback):
            return fallback
    except Exception:
        pass

    return None


def create_render_camera(node) -> Optional[object]:
    """
    Create or update a camera at the current viewport position.

    Args:
        node: The HDA node (used for positioning and resolution)

    Returns:
        Camera node object or None on failure
    """
    import hou

    try:
        # Get current scene viewer
        scene_viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if not scene_viewer:
            hou.ui.displayMessage("No Scene Viewer found!", title="Bria Error")
            return None

        viewport = scene_viewer.curViewport()
        if not viewport:
            hou.ui.displayMessage("No active viewport!", title="Bria Error")
            return None

        # Get /obj context
        obj_context = hou.node("/obj")

        width, height = _resolution_wh_from_node(node)

        # If this HDA itself is a camera, update it in place.
        if _is_camera_node(node):
            _set_camera_resolution(node, width, height)
            viewport.saveViewToCamera(node)
            hou.ui.displayMessage(
                f"Updated camera '{node.path()}' with current viewport view.\n"
                f"Resolution: {width}x{height}",
                title="Camera Updated"
            )
            return node

        # Otherwise keep legacy shared camera behavior.
        camera_name = "bria_render_camera"
        existing_camera = obj_context.node(camera_name)

        if existing_camera:
            # Update existing camera
            _set_camera_resolution(existing_camera, width, height)
            viewport.saveViewToCamera(existing_camera)
            hou.ui.displayMessage(
                f"Updated camera '{camera_name}' with current viewport view.\n"
                f"Resolution: {width}x{height}",
                title="Camera Updated"
            )
            return existing_camera
        else:
            # Create new camera
            camera = obj_context.createNode("cam", camera_name)
            _set_camera_resolution(camera, width, height)
            viewport.saveViewToCamera(camera)

            # Position below the node
            camera.setPosition(node.position() + hou.Vector2(0, -2))

            hou.ui.displayMessage(
                f"Created camera '{camera_name}' at current viewport view.\n"
                f"Resolution: {width}x{height}",
                title="Camera Created"
            )
            return camera

    except Exception as e:
        logger.exception("Failed to create camera")
        hou.ui.displayMessage(f"Failed to create camera: {_safe_exc_str(e)}", title="Bria Error")
        return None


def render_viewport_opengl(node) -> Optional[str]:
    """
    Render the current viewport as an OpenGL capture.

    Args:
        node: The HDA node (used for resolution)

    Returns:
        Path to rendered image or None on failure
    """
    import hou

    try:
        # Get scene viewer and viewport
        scene_viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if not scene_viewer:
            raise RuntimeError("No Scene Viewer found")

        viewport = scene_viewer.curViewport()
        if not viewport:
            raise RuntimeError("No active viewport")

        render_camera = resolve_render_camera(node)
        original_camera = None
        if render_camera is not None:
            width, height = _resolution_wh_from_node(node)
            _set_camera_resolution(render_camera, width, height)
            try:
                original_camera = viewport.camera()
            except Exception:
                original_camera = None
            try:
                viewport.setCamera(render_camera)
            except Exception:
                pass

        # Get resolution
        width, height = _resolution_wh_from_node(node)

        # Generate output path with timestamp
        timestamp = int(time.time())
        output_dir = get_output_directory()
        output_path = os.path.join(output_dir, f"viewport_capture_{timestamp}.png")
        output_path = output_path.replace("\\", "/")

        # Get flipbook settings
        flip_book_settings = scene_viewer.flipbookSettings().stash()

        # Configure flipbook
        current_frame = hou.frame()
        flip_book_settings.frameRange((current_frame, current_frame))
        flip_book_settings.resolution((width, height))
        flip_book_settings.useResolution(True)
        flip_book_settings.output(output_path)
        flip_book_settings.outputToMPlay(False)
        flip_book_settings.beautyPassOnly(False)

        # Execute render
        try:
            scene_viewer.flipbook(viewport, flip_book_settings)
        finally:
            if render_camera is not None and original_camera is not None:
                try:
                    viewport.setCamera(original_camera)
                except Exception:
                    pass

        # Verify file exists and is fresh
        if not os.path.exists(output_path):
            raise RuntimeError("Viewport render file was not created")

        file_age = time.time() - os.path.getmtime(output_path)
        if file_age > 10:
            logger.warning(f"Viewport render file may be stale (age: {file_age:.1f}s)")

        logger.info(f"Viewport captured: {output_path} ({width}x{height})")

        return output_path

    except Exception as e:
        logger.exception("Viewport render failed")
        raise RuntimeError(f"Viewport render failed: {_safe_exc_str(e)}")


def call_bria_render(
    image_path: str,
    prompt: Optional[str] = None,
    result_path: Optional[str] = None,
    seed: Optional[int] = None,
    steps_num: Optional[int] = None,
    guidance_scale: int = 5,
    use_cache: bool = True,
    structured_prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
) -> Optional[str]:
    """Call Bria FIBO Edit API to render the viewport capture."""

    data = fibo_edit_from_files(
        image_path=image_path,
        prompt=prompt,
        structured_prompt=structured_prompt,
        negative_prompt=negative_prompt,
        guidance_scale=int(guidance_scale) if guidance_scale is not None else None,
        seed=seed,
        steps_num=steps_num,
        use_cache=bool(use_cache),
    )

    dl_url = extract_image_url(data)
    if not dl_url:
        raise RuntimeError(f"Unexpected Bria response (no image_url): {data}")

    img_bytes, _content_type = download_url(dl_url, timeout_s=300, proxies=None)

    if result_path:
        result_path = str(result_path).strip().replace("\\", "/")
        if result_path:
            os.makedirs(os.path.dirname(result_path), exist_ok=True)
        else:
            result_path = None

    if not result_path:
        result_path = generate_result_path(prompt)

    with open(result_path, "wb") as f:
        f.write(img_bytes)

    logger.info(f"Bria render complete: {result_path}")
    return result_path


def _reapply_texture_to_objects(image_path: str) -> int:
    """Update basecolor_texture on all geometry objects that have a Bria material applied.

    Returns the number of objects updated.
    """
    import hou

    count = 0
    try:
        for geo_obj in get_displayed_geometry_objects():
            mat_sop = geo_obj.node("bria_material")
            if mat_sop is None:
                continue
            mat_path_parm = mat_sop.parm("shop_materialpath1")
            if not mat_path_parm:
                continue
            mat_node = hou.node(mat_path_parm.eval())
            if mat_node is None:
                continue
            tex_parm = mat_node.parm("basecolor_texture")
            if tex_parm is not None:
                tex_parm.set(image_path)
                count += 1
    except Exception as exc:
        logger.warning("Auto-reapply texture failed (non-fatal): %s", _safe_exc_str(exc))

    if count > 0:
        logger.info("Auto-reapplied texture to %d object(s)", count)
    return count


def _find_houdini_binary(name: str) -> Optional[str]:
    """Locate a Houdini binary (mplay, imdisplay, etc.) in $HFS/bin."""
    import hou

    bin_name = f"{name}.exe" if sys.platform == "win32" else name

    # Method 1: hou.findFile
    try:
        path = hou.findFile(f"bin/{bin_name}")
        if path and os.path.exists(path):
            return path
    except Exception:
        pass

    # Method 2: Direct $HFS/bin path
    try:
        hfs = hou.getenv("HFS")
        if hfs:
            path = os.path.join(hfs, "bin", bin_name)
            if os.path.exists(path):
                return path
    except Exception:
        pass

    return None


def display_in_mplay(image_path: str) -> bool:
    """Display the result image in Houdini's MPlay.

    Uses ``imdisplay -Y "Bria Viewport"`` so every Bria render is sent to
    the same labeled MPlay window.  If no MPlay with that label exists yet,
    ``imdisplay`` creates one automatically.  Each new image appears as the
    next frame in the sequence — matching how flipbooks and renders behave.

    Args:
        image_path: Path to image file

    Returns:
        True if successfully sent, False otherwise
    """
    normalized_path = image_path.replace("\\", "/")

    # Use imdisplay with a label — creates or reuses a named MPlay session
    imdisplay_path = _find_houdini_binary("imdisplay")
    if imdisplay_path:
        try:
            subprocess.Popen([
                imdisplay_path,
                "-Y", "Bria Viewport",
                normalized_path,
            ])
            logger.info("Sent to MPlay (Bria Viewport): %s", normalized_path)
            return True
        except Exception as exc:
            logger.warning("imdisplay failed: %s", _safe_exc_str(exc))

    # Fallback: launch mplay directly (opens a new window each time)
    mplay_path = _find_houdini_binary("mplay")
    if mplay_path:
        try:
            subprocess.Popen([mplay_path, normalized_path])
            logger.info("Launched MPlay: %s", normalized_path)
            return True
        except Exception as exc:
            logger.warning("mplay launch failed: %s", _safe_exc_str(exc))

    # Windows fallback: open with default viewer
    if sys.platform == "win32":
        try:
            os.startfile(normalized_path)
            return True
        except Exception:
            pass

    logger.warning("Could not display result in MPlay: %s", normalized_path)
    return False


def _swap_display_for_clean_capture(node):
    """Temporarily swap display to the node feeding into the Bria texture chain.

    For each displayed geometry object that has a ``bria_uv_project`` node,
    sets the display flag to whatever is wired into its input 0.  This
    captures the current untextured geometry — including any SOPs the user
    added after the initial texture application (e.g. a Smooth).

    Objects that don't have a Bria texture chain yet are left untouched.

    Returns:
        dict mapping geo_path → bria_material SOP node (to restore later),
        or empty dict if nothing was swapped.
    """
    import hou

    restored = {}
    for geo_obj in get_displayed_geometry_objects():
        uv_proj = geo_obj.node("bria_uv_project")
        mat_sop = geo_obj.node("bria_material")
        if uv_proj is None or mat_sop is None:
            continue

        # The node wired into bria_uv_project input 0 is the last
        # user SOP before the Bria chain — this is what we capture.
        inputs = uv_proj.inputs()
        if not inputs or inputs[0] is None:
            continue

        pre_bria_node = inputs[0]
        pre_bria_node.setDisplayFlag(True)
        restored[geo_obj.path()] = mat_sop

    return restored


def _restore_material_display(restored):
    """Restore material SOPs as display nodes after clean capture.

    Args:
        restored: dict of geo_path → material SOP node (from ``_swap_display_for_clean_capture``).
    """
    for _geo_path, mat_sop in restored.items():
        if mat_sop is not None:
            mat_sop.setDisplayFlag(True)
            mat_sop.setRenderFlag(True)


def render_viewport(node) -> Optional[str]:
    """
    Main orchestration function: capture viewport, call Bria, display result.

    Args:
        node: The HDA node

    Returns:
        Path to result image or None on failure
    """
    import hou

    try:
        # Update status
        status_parm = node.parm("status")
        if status_parm:
            status_parm.set("Starting...")

        # Determine prompt mode (basic text vs structured VGL)
        use_basic = _eval_parm_bool(node, "use_basic_prompt", default=True)
        use_struct = _eval_parm_bool(node, "use_structured_prompt", default=False)

        prompt = ""
        structured_prompt = None
        negative_prompt = ""

        if use_basic:
            prompt = _eval_parm_str(node, "prompt")
            negative_prompt = _eval_parm_str(node, "negative_prompt")
        if use_struct:
            # Try VGL structured parms first, fall back to raw JSON
            try:
                from bria_houdini.vgl_parms import assemble_from_parms
                structured_prompt = assemble_from_parms(node)
            except Exception as e:
                logger.debug("VGL assembly failed, falling back to raw JSON: %s", _safe_exc_str(e))
                structured_prompt = None
            if not structured_prompt:
                structured_prompt = _eval_parm_str(node, "structured_prompt")
        # Enforce mutual exclusion: clear the inactive mode
        if not use_basic:
            prompt = ""
        if not use_struct:
            structured_prompt = None

        if not prompt and not structured_prompt:
            hou.ui.displayMessage(
                "Please provide either a basic prompt or a structured prompt.",
                title="Bria Error"
            )
            return None

        # Get parameters
        use_cache = _eval_parm_bool(node, "use_cache", default=True)
        guidance_scale = int(_eval_parm_int(node, "guidance_scale") or 5)

        # Get seed (0 means no seed / random)
        seed_val = _eval_parm_int(node, "seed") or 0
        seed = seed_val if seed_val > 0 else None

        # Get steps_num (0 means use API default).
        steps_val = _eval_parm_int(node, "steps_num") or 0
        steps_num = clamp_steps_num(steps_val)

        # Check camera mode — "use_existing" validates camera exists
        # (Resolution validation is handled by validate_existing_camera_callback)
        camera_mode = _eval_parm_str(node, "camera_mode") or "create_new"
        if camera_mode == "use_existing":
            cam_path = _eval_parm_str(node, "camera_path")
            if not cam_path:
                hou.ui.displayMessage(
                    "Please specify a camera path.",
                    title="Bria Error"
                )
                return None
            cam_node = hou.node(cam_path)
            if cam_node is None or not _is_camera_node(cam_node):
                hou.ui.displayMessage(
                    f"Camera not found or invalid: {cam_path}",
                    title="Bria Error"
                )
                return None

        requested_result_path = ""

        # Determine iteration mode
        render_mode = _eval_parm_str(node, "render_mode") or "create_new"

        # Step 1: Capture viewport
        # In "create_new" mode, temporarily restore original display nodes
        # so the flipbook captures the greybox geometry, not the textured view.
        restored = {}
        if render_mode == "create_new":
            restored = _swap_display_for_clean_capture(node)

        if status_parm:
            status_parm.set("Capturing viewport...")

        try:
            viewport_path = render_viewport_opengl(node)
        finally:
            # Always restore material display after capture, even on failure
            if restored:
                _restore_material_display(restored)

        if not viewport_path:
            raise RuntimeError("Failed to capture viewport")

        source_image_parm = _find_parm(node, "source_image")
        if source_image_parm is not None:
            source_image_parm.set(viewport_path)

        # Step 2: Call Bria API
        if status_parm:
            status_parm.set("Rendering with FIBO Edit...")

        result_path = call_bria_render(
            image_path=viewport_path,
            prompt=prompt or None,
            result_path=requested_result_path,
            seed=seed,
            steps_num=steps_num,
            guidance_scale=guidance_scale,
            use_cache=use_cache,
            structured_prompt=structured_prompt or None,
            negative_prompt=negative_prompt or None,
        )

        if not result_path:
            raise RuntimeError("Failed to get result from Bria")

        result_image_parm = _find_parm(node, "result_image")
        if result_image_parm is not None:
            result_image_parm.set(result_path)
        result_path_parm = _find_parm(node, "result_path")
        if result_path_parm is not None:
            result_path_parm.set(result_path)

        # Step 3: Auto-populate VGL structured prompt fields after basic render
        # so the user can switch to the Structured Prompt tab and refine
        if use_basic and prompt:
            try:
                import json
                from bria_houdini.adapter import generate_structured_prompt
                from bria_houdini.vgl_parms import populate_parms_from_json

                if status_parm:
                    status_parm.set("Generating VGL from prompt...")

                data = generate_structured_prompt(prompt=prompt)
                result_data = data.get("result", {})
                sp = result_data.get("structured_prompt") or data.get("structured_prompt")
                if isinstance(sp, dict):
                    json_str = json.dumps(sp, indent=2)
                elif isinstance(sp, str):
                    try:
                        json_str = json.dumps(json.loads(sp), indent=2)
                    except Exception as e:
                        logger.debug("VGL JSON re-format failed, using raw: %s", _safe_exc_str(e))
                        json_str = sp
                else:
                    json_str = None

                if json_str:
                    sp_parm = node.parm("structured_prompt")
                    if sp_parm:
                        sp_parm.set(json_str)
                    populate_parms_from_json(node, json_str)
                    logger.info("Auto-populated VGL fields from basic prompt")
            except Exception as e:
                logger.warning(f"Auto-populate VGL failed: {_safe_exc_str(e)}")
                if status_parm:
                    status_parm.set(f"VGL update failed: {_safe_exc_str(e)}")

        # Step 4: Auto-reapply texture if previously applied
        _reapply_texture_to_objects(result_path)

        # Step 5: Display in MPlay
        if status_parm:
            status_parm.set("Opening in MPlay...")

        display_in_mplay(result_path)

        # Success
        if status_parm:
            status_parm.set("Done!")

        output_dir = get_output_directory()
        hou.ui.displayMessage(
            f"Bria Viewport Render Complete!\n\n"
            f"Saved to:\n{result_path}\n\n"
            f"Output folder:\n{output_dir}",
            title="Bria Viewport Render"
        )

        return result_path

    except Exception as e:
        logger.exception("Viewport render failed")
        if status_parm:
            status_parm.set("Error")
        hou.ui.displayMessage(f"Viewport render failed: {_safe_exc_str(e)}", title="Bria Error")
        return None


# ============== Camera Callbacks ==============

def validate_existing_camera_callback():
    """Callback for 'Validate Camera' button — check if camera exists and resolution matches."""
    import hou
    node = hou.pwd()
    cam_path = _eval_parm_str(node, "camera_path")
    if not cam_path:
        hou.ui.displayMessage("Please specify a camera path.", title="Bria Error")
        return
    cam_node = hou.node(cam_path)
    if cam_node is None or not _is_camera_node(cam_node):
        hou.ui.displayMessage(f"Camera not found or invalid:\n{cam_path}", title="Bria Error")
        return
    cam_resx = cam_node.parm("resx")
    cam_resy = cam_node.parm("resy")
    if cam_resx and cam_resy:
        cw, ch = int(cam_resx.eval()), int(cam_resy.eval())
        res_key = f"{cw}x{ch}"
        if res_key in SUPPORTED_RESOLUTIONS:
            # Set the resolution menu to match the camera
            res_parm = node.parm("resolution")
            if res_parm is not None:
                res_parm.set(res_key)
            hou.ui.displayMessage(
                f"Camera '{cam_path}' is valid.\nResolution: {cw}x{ch} (supported)",
                title="Camera OK"
            )
        else:
            match_w, match_h = find_closest_resolution(cw, ch)
            # Set the resolution menu to the closest supported match
            res_parm = node.parm("resolution")
            if res_parm is not None:
                res_parm.set(f"{match_w}x{match_h}")
            hou.ui.displayMessage(
                f"Camera '{cam_path}' is valid but resolution {cw}x{ch} is not directly supported.\n\n"
                f"Viewport will be captured at {match_w}x{match_h} (closest supported resolution).\n\n"
                f"Tip: Use the Bria Upscale node afterward to scale the result up to your target resolution.",
                severity=hou.severityType.Warning,
                title="Resolution Mismatch"
            )
    else:
        hou.ui.displayMessage(f"Camera '{cam_path}' is valid.", title="Camera OK")


# ============== Preset Callbacks ==============

def on_category_changed(kwargs):
    """Callback when the category menu changes — update prompt from first preset."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _eval_parm_str(node, "category") or "custom"
    if category == "custom":
        node.parm("prompt").set("")
        return
    presets = PRESET_CATEGORIES.get(category)
    if presets:
        preset_parm = node.parm(f"preset_{category}")
        if preset_parm is not None:
            preset_parm.set(0)
        node.parm("prompt").set(presets[0][2])


def on_preset_changed(kwargs):
    """Callback when any per-category preset menu changes — update prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _eval_parm_str(node, "category") or "custom"
    if category == "custom":
        return
    parm_name = f"preset_{category}"
    preset_key = _eval_parm_str(node, parm_name) or ""
    prompt_text = ALL_PRESETS.get(preset_key, "")
    if prompt_text:
        node.parm("prompt").set(prompt_text)


# ============== Callback Functions for HDA ==============

def create_camera_callback():
    """Callback for 'Create Camera' button."""
    import hou
    node = hou.pwd()
    create_render_camera(node)


def render_viewport_callback():
    """Callback for 'Restyle Viewport' button."""
    import hou
    node = hou.pwd()
    render_viewport(node)


def capture_render_viewport_callback():
    """Callback alias for Main.capture_render_viewport button."""
    import hou
    node = hou.pwd()
    render_viewport(node)


def upscale_result_callback():
    """Callback for 'Run Bria Upscale' button — upscale the last render result."""
    import hou
    from bria_houdini.adapter import upscale_from_files

    node = hou.pwd()
    status_parm = node.parm("status")

    try:
        result_path = _eval_parm_str(node, "result_path")
        if not result_path or not os.path.exists(result_path):
            hou.ui.displayMessage(
                "No render result to upscale.\nPlease render the viewport first.",
                title="Bria Error"
            )
            return

        scale = _eval_parm_str(node, "upscale_scale") or "2x"
        if status_parm:
            status_parm.set(f"Upscaling {scale}...")

        data = upscale_from_files(
            image_path=result_path,
            mode="increase_resolution",
            desired_resolution=scale,
        )

        dl_url = extract_image_url(data)
        if not dl_url:
            raise RuntimeError(f"Unexpected Bria upscale response (no image_url): {data}")

        img_bytes, _content_type = download_url(dl_url, timeout_s=300, proxies=None)

        # Save upscaled image alongside the original
        base, ext = os.path.splitext(result_path)
        upscaled_path = f"{base}_upscaled_{scale}{ext}"
        with open(upscaled_path, "wb") as f:
            f.write(img_bytes)

        # Update node parms so Apply Texture uses the upscaled image
        result_path_parm = node.parm("result_path")
        if result_path_parm is not None:
            result_path_parm.set(upscaled_path)
        source_image_parm = node.parm("source_image")
        if source_image_parm is not None:
            source_image_parm.set(upscaled_path)

        # Re-apply texture to any geometry that already has a Bria material
        _reapply_texture_to_objects(upscaled_path)

        # Show in existing MPlay
        display_in_mplay(upscaled_path)

        if status_parm:
            status_parm.set(f"Upscale {scale} complete!")

        hou.ui.displayMessage(
            f"Bria Upscale Complete!\n\n"
            f"Scale: {scale}\n"
            f"Saved to:\n{upscaled_path}",
            title="Bria Upscale"
        )

    except Exception as e:
        logger.exception("Upscale failed")
        if status_parm:
            status_parm.set("Upscale error")
        hou.ui.displayMessage(f"Upscale failed: {_safe_exc_str(e)}", title="Bria Error")


def enhance_result_callback():
    """Callback for 'Run Bria Enhance' button — enhance the last render result."""
    import hou
    from bria_houdini.adapter import upscale_from_files

    node = hou.pwd()
    status_parm = node.parm("status")

    try:
        result_path = _eval_parm_str(node, "result_path")
        if not result_path or not os.path.exists(result_path):
            hou.ui.displayMessage(
                "No render result to enhance.\nPlease render the viewport first.",
                title="Bria Error"
            )
            return

        resolution = _eval_parm_str(node, "enhance_resolution") or "1MP"
        if status_parm:
            status_parm.set(f"Enhancing ({resolution})...")

        data = upscale_from_files(
            image_path=result_path,
            mode="enhance",
            resolution=resolution,
        )

        dl_url = extract_image_url(data)
        if not dl_url:
            raise RuntimeError(f"Unexpected Bria enhance response (no image_url): {data}")

        img_bytes, _content_type = download_url(dl_url, timeout_s=300, proxies=None)

        # Save enhanced image alongside the original
        base, ext = os.path.splitext(result_path)
        enhanced_path = f"{base}_enhanced_{resolution}{ext}"
        with open(enhanced_path, "wb") as f:
            f.write(img_bytes)

        # Update node parms so subsequent operations use the enhanced image
        result_path_parm = node.parm("result_path")
        if result_path_parm is not None:
            result_path_parm.set(enhanced_path)
        source_image_parm = node.parm("source_image")
        if source_image_parm is not None:
            source_image_parm.set(enhanced_path)

        # Re-apply texture to any geometry that already has a Bria material
        _reapply_texture_to_objects(enhanced_path)

        # Show in existing MPlay
        display_in_mplay(enhanced_path)

        if status_parm:
            status_parm.set(f"Enhance ({resolution}) complete!")

        hou.ui.displayMessage(
            f"Bria Enhance Complete!\n\n"
            f"Resolution: {resolution}\n"
            f"Saved to:\n{enhanced_path}",
            title="Bria Enhance"
        )

    except Exception as e:
        logger.exception("Enhance failed")
        if status_parm:
            status_parm.set("Enhance error")
        hou.ui.displayMessage(f"Enhance failed: {_safe_exc_str(e)}", title="Bria Error")


# ============== Structured Prompt Callbacks ==============

def generate_vgl_callback():
    """Generate VGL structured prompt from a text description via Bria API."""
    import hou
    import json
    from bria_houdini.adapter import generate_structured_prompt
    from bria_houdini.vgl_parms import populate_parms_from_json

    node = hou.pwd()
    status_parm = node.parm("status")

    prompt = _eval_parm_str(node, "generate_vgl_prompt")
    if not prompt:
        hou.ui.displayMessage(
            "Enter a scene description to generate VGL from.",
            title="Bria Error",
        )
        return

    if status_parm:
        status_parm.set("Generating VGL...")

    try:
        data = generate_structured_prompt(prompt=prompt)

        # Extract structured_prompt from nested response
        result = data.get("result", {})
        sp = result.get("structured_prompt") or data.get("structured_prompt")
        if isinstance(sp, dict):
            json_str = json.dumps(sp, indent=2)
        elif isinstance(sp, str):
            try:
                json_str = json.dumps(json.loads(sp), indent=2)
            except Exception:
                json_str = sp
        else:
            raise RuntimeError(f"Unexpected API response: {data}")

        # Store raw JSON and populate VGL parms
        sp_parm = node.parm("structured_prompt")
        if sp_parm:
            sp_parm.set(json_str)
        populated = populate_parms_from_json(node, json_str)

        # Auto-switch to structured mode
        bp = node.parm("use_basic_prompt")
        if bp is not None:
            bp.set(0)
        sp_toggle = node.parm("use_structured_prompt")
        if sp_toggle is not None:
            sp_toggle.set(1)

        if status_parm:
            status_parm.set("VGL generated!")

        hou.ui.displayMessage(
            f"Generated VGL with {populated} section(s).\n\n"
            f"Fields populated from:\n{prompt[:120]}",
            title="Bria Generate VGL",
        )

    except Exception as e:
        logger.exception("VGL generation failed")
        if status_parm:
            status_parm.set("VGL generation error")
        hou.ui.displayMessage(f"VGL generation failed: {_safe_exc_str(e)}", title="Bria Error")


def on_parse_vgl(kwargs):
    """Parse raw VGL JSON into structured fields. Wraps vgl_parms.on_parse_vgl."""
    from bria_houdini.vgl_parms import on_parse_vgl as _on_parse_vgl
    _on_parse_vgl(kwargs)


def sync_vgl_to_json(kwargs):
    """Assemble structured VGL fields back into raw JSON. Wraps vgl_parms.sync_vgl_to_json."""
    from bria_houdini.vgl_parms import sync_vgl_to_json as _sync
    _sync(kwargs)


# ============== Apply Texture Functions ==============

def get_available_render_images() -> list:
    """
    Scan the output directory for existing render images.

    Returns:
        List of tuples: (display_name, full_path) sorted by modification time (newest first)
    """
    import glob

    output_dir = get_output_directory()
    pattern = os.path.join(output_dir, "bria_render_*.png")

    images = []
    for filepath in sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True):
        filename = os.path.basename(filepath)
        # Remove prefix and extension for display
        display_name = filename.replace("bria_render_", "").replace(".png", "")
        images.append((display_name, filepath))

    return images[:20]  # Limit to 20 most recent


def get_displayed_geometry_objects() -> list:
    """
    Find all geometry objects in /obj that have displayable content.

    Returns:
        List of hou.ObjNode geometry objects that have a display node set
    """
    import hou

    obj_context = hou.node("/obj")
    if not obj_context:
        return []

    displayed_objects = []
    for child in obj_context.children():
        # Check if it's a geometry object
        if child.type().name() == "geo":
            # Check if object has a display node (has content to display)
            # and is not hidden via the display flag parameter
            display_node = child.displayNode()
            if display_node:
                # Check if the object isn't explicitly hidden
                # tdisplay parm: 0=use display flag, 1=always display, 2=never display
                tdisplay = child.parm("tdisplay")
                if tdisplay is None or tdisplay.eval() != 2:
                    displayed_objects.append(child)

    return displayed_objects


def create_bria_material(image_path: str, use_pbr: bool = False) -> object:
    """
    Create a material in /mat that uses the render result image as diffuse texture.

    Args:
        image_path: Path to the texture image
        use_pbr: If True, configure for PBR rendering; if False, optimize for OpenGL

    Returns:
        The material node
    """
    import hou

    mat_context = hou.node("/mat")
    if not mat_context:
        mat_context = hou.node("/").createNode("mat")

    # Generate material name from image filename
    basename = os.path.splitext(os.path.basename(image_path))[0]
    material_name = f"bria_mat_{basename}"

    # Check if material already exists
    existing = mat_context.node(material_name)
    if existing:
        # Update texture path
        if existing.parm("basecolor_texture"):
            existing.parm("basecolor_texture").set(image_path)
        return existing

    # Create Principled Shader (works for both OpenGL and renders)
    material = mat_context.createNode("principledshader::2.0", material_name)

    # Set base color to use texture at full brightness
    material.parm("basecolor_useTexture").set(1)
    material.parm("basecolor_texture").set(image_path)
    material.parm("basecolorr").set(1.0)
    material.parm("basecolorg").set(1.0)
    material.parm("basecolorb").set(1.0)

    # Use default UV attribute (empty string = default "uv")
    # Note: This parameter may not exist in all Houdini versions
    uvset_parm = material.parm("basecolor_uvSet")
    if uvset_parm:
        uvset_parm.set("")

    if use_pbr:
        # PBR settings for rendering
        material.parm("rough").set(0.3)
        material.parm("reflect").set(0.04)
    else:
        # OpenGL-optimized settings
        material.parm("rough").set(0.8)
        material.parm("reflect").set(0.0)

    material.moveToGoodPosition()
    return material


def create_texture_nodes(geo_obj, camera_path: str) -> object:
    """
    Create texture projection nodes directly in a geometry object.

    Creates the following node chain connected to the display node:
    - UV Texture (Perspective from Camera projection)
    - Attribute Promote (vertex→point UV conversion for shader compatibility)
    - Material SOP (assigns the bria material)

    Args:
        geo_obj: The geometry object node
        camera_path: Path to the projection camera

    Returns:
        The material SOP node (final node in chain with display/render flags)
    """
    import hou

    UV_NODE_NAME = "bria_uv_project"
    PROMOTE_NODE_NAME = "bria_promote_uv"
    MATERIAL_NODE_NAME = "bria_material"

    # Check if nodes already exist (return existing material SOP)
    existing_material = geo_obj.node(MATERIAL_NODE_NAME)
    if existing_material:
        return existing_material

    # Get current display node
    display_node = geo_obj.displayNode()
    if not display_node:
        raise RuntimeError(f"No display node found in {geo_obj.path()}")

    # 1. Create UV Texture SOP with Perspective from Camera
    #    Connected directly to the display node (no object_merge needed)
    uv_texture = geo_obj.createNode("texture", UV_NODE_NAME)
    uv_texture.setInput(0, display_node)  # Direct connection to display node
    uv_texture.setPosition(display_node.position() + hou.Vector2(0, -1))

    # Configure UV Texture
    uv_texture.parm("type").set(9)  # 9 = "Perspective From Camera"
    uv_texture.parm("campath").set(camera_path)
    uv_texture.parm("uvattrib").set("uv")  # Use default "uv" attribute

    # 2. Create Attribute Promote to convert vertex UVs to point UVs
    #    This ensures shaders read the UVs correctly
    attrib_promote = geo_obj.createNode("attribpromote", PROMOTE_NODE_NAME)
    attrib_promote.setInput(0, uv_texture)
    attrib_promote.setPosition(uv_texture.position() + hou.Vector2(0, -1))

    # Configure Attribute Promote: vertex → point
    attrib_promote.parm("inname").set("uv")
    attrib_promote.parm("inclass").set(3)   # 3 = Vertex
    attrib_promote.parm("outclass").set(2)  # 2 = Point
    attrib_promote.parm("method").set(0)    # 0 = Average (works well for UVs)

    # 3. Create Material SOP
    material_sop = geo_obj.createNode("material", MATERIAL_NODE_NAME)
    material_sop.setInput(0, attrib_promote)
    material_sop.setPosition(attrib_promote.position() + hou.Vector2(0, -1))
    # Material path will be set by apply_texture function

    # Set display/render flags on material SOP
    material_sop.setDisplayFlag(True)
    material_sop.setRenderFlag(True)

    return material_sop


def apply_texture(node) -> bool:
    """
    Main function to apply selected texture to all displayed objects.

    Args:
        node: The HDA node

    Returns:
        True on success, False on failure
    """
    import hou

    try:
        status_parm = node.parm("status")

        # Get parameters — prefer the AI render result,
        # fall back to the source image (viewport screenshot)
        image_path = _eval_parm_str(node, "result_path") or _eval_parm_str(node, "source_image")
        use_pbr = node.parm("use_pbr").eval() if node.parm("use_pbr") else False

        if not image_path or not os.path.exists(image_path):
            hou.ui.displayMessage(
                "Please select a valid source image.",
                title="Bria Error"
            )
            return False

        # Check for camera
        camera = resolve_render_camera(node)
        if not camera:
            hou.ui.displayMessage(
                "No valid camera found for projection.\n"
                "Set camera_path or use this node as a camera.",
                title="Bria Error"
            )
            return False
        camera_path = camera.path()

        target_mat_path = _eval_parm_str(node, "mat_path")
        if target_mat_path:
            mat_node = hou.node(target_mat_path)
            if mat_node is None:
                hou.ui.displayMessage(f"Material not found: {target_mat_path}", title="Bria Error")
                return False
            basecolor = mat_node.parm("basecolor_texture")
            if basecolor is None:
                hou.ui.displayMessage(
                    f"Material has no 'basecolor_texture' parm: {target_mat_path}",
                    title="Bria Error",
                )
                return False
            if mat_node.parm("basecolor_useTexture") is not None:
                mat_node.parm("basecolor_useTexture").set(1)
            basecolor.set(image_path)
            if status_parm:
                status_parm.set("Done!")
            hou.ui.displayMessage(
                f"Applied image to material:\n{target_mat_path}\n\nTexture: {os.path.basename(image_path)}",
                title="Bria Apply Result",
            )
            return True

        if status_parm:
            status_parm.set("Finding displayed objects...")

        # Get displayed objects
        displayed_objects = get_displayed_geometry_objects()
        if not displayed_objects:
            hou.ui.displayMessage(
                "No displayed geometry objects found in /obj.",
                title="Bria Error"
            )
            return False

        if status_parm:
            status_parm.set("Creating material...")

        # Create material
        material = create_bria_material(image_path, use_pbr)
        material_path = material.path()

        if status_parm:
            status_parm.set("Applying texture...")

        # Apply to each object
        applied_count = 0
        for geo_obj in displayed_objects:
            try:
                # Create/get texture nodes (returns material SOP directly)
                material_sop = create_texture_nodes(geo_obj, camera_path)

                # Set material path on material SOP and ensure display flag
                if material_sop:
                    material_sop.parm("shop_materialpath1").set(material_path)
                    material_sop.setDisplayFlag(True)
                    material_sop.setRenderFlag(True)

                applied_count += 1

            except Exception as e:
                logger.warning(f"Failed to apply texture to {geo_obj.path()}: {_safe_exc_str(e)}")

        if status_parm:
            status_parm.set("Done!")

        hou.ui.displayMessage(
            f"Applied texture to {applied_count} object(s).\n\n"
            f"Material: {material_path}\n"
            f"Texture: {os.path.basename(image_path)}",
            title="Bria Apply Texture"
        )

        return True

    except Exception as e:
        logger.exception("Apply texture failed")
        if status_parm:
            status_parm.set("Error")
        hou.ui.displayMessage(f"Apply texture failed: {_safe_exc_str(e)}", title="Bria Error")
        return False


# ============== Apply Texture Callbacks ==============

def refresh_image_list_callback():
    """Callback for refreshing the image list."""
    import hou
    # The menu script handles population automatically
    # This callback is for manual feedback
    hou.ui.displayMessage("Image list refreshed.", title="Bria")


def apply_texture_callback():
    """Callback for 'Apply Texture' button."""
    import hou
    node = hou.pwd()
    apply_texture(node)


def apply_result_callback():
    """Callback alias for Project Texture.apply_result button."""
    import hou
    node = hou.pwd()
    apply_texture(node)
