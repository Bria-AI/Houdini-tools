"""
Bria Viewport Restyle HDA Implementation.

This module provides the core logic for capturing Houdini viewport
and reimagining it using Bria's AI with a text prompt.

Adapted from MagAIRender tool for use with Bria API.
"""

import logging
import os
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from typing import Optional

from bria_core.utils import download_url, extract_image_url, resolve_temp_dir
from houdini.adapter import fibo_edit_from_files
from houdini.node_utils import clamp_steps_num

logger = logging.getLogger(__name__)

# Output directory configuration (runtime temp location)
DEFAULT_OUTPUT_DIR = ""


def get_output_directory() -> str:
    """
    Get the output directory for restyle results.

    Returns:
        Normalized path to output directory (creates if needed)
    """
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

    return "restyle"


def get_next_version_number(output_dir: str, noun: str) -> int:
    """
    Find the next available version number for a given noun.

    Scans existing files matching pattern: bria_restyle_{noun}_##.png

    Args:
        output_dir: Directory to scan
        noun: The noun used in filename

    Returns:
        Next version number (1 if no existing files)
    """
    import glob
    import re

    pattern = os.path.join(output_dir, f"bria_restyle_{noun}_*.png")
    existing = glob.glob(pattern)

    max_version = 0
    version_pattern = re.compile(rf"bria_restyle_{noun}_(\d+)\.png$")

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
    filename = f"bria_restyle_{noun}_{version:02d}.png"
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
    except Exception:
        pass

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
    except Exception:
        pass


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
    3) legacy fallback camera /obj/bria_restyle_camera
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
        fallback = hou.node("/obj/bria_restyle_camera")
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
        camera_name = "bria_restyle_camera"
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
        hou.ui.displayMessage(f"Failed to create camera: {e}", title="Bria Error")
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
        raise RuntimeError(f"Viewport render failed: {e}")


def call_bria_restyle(
    image_path: str,
    prompt: str,
    result_path: Optional[str] = None,
    structure_influence: float = 0.75,
    seed: Optional[int] = None,
    steps_num: Optional[int] = None,
    content_moderation: bool = True,
    use_fibo_edit: bool = True,
    guidance_scale: int = 5,
    negative_prompt: Optional[str] = None,
    use_cache: bool = True
) -> Optional[str]:
    """Call Bria API to restyle the viewport capture.

    Uses this repo's adapter stack. Legacy reimagine mode is mapped to FIBO Edit
    when no dedicated legacy endpoint is configured in this integration.
    """

    if not use_fibo_edit:
        logger.warning("Legacy reimagine mode is not wired in this repo; using FIBO Edit endpoint.")
    if content_moderation is not None:
        logger.info("content_moderation is currently ignored for viewport restyle FIBO Edit path.")
    if structure_influence is not None:
        logger.info("structure_influence is currently ignored for viewport restyle FIBO Edit path.")

    data = fibo_edit_from_files(
        image_path=image_path,
        prompt=prompt,
        structured_prompt=None,
        guidance_scale=int(guidance_scale) if guidance_scale is not None else None,
        negative_prompt=negative_prompt,
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

    logger.info(f"Bria restyle complete: {result_path}")
    return result_path


def display_in_mplay(image_path: str) -> bool:
    """
    Display the result image in Houdini's MPlay.

    Args:
        image_path: Path to image file

    Returns:
        True if successfully launched, False otherwise
    """
    import hou

    normalized_path = image_path.replace("\\", "/")

    # Determine platform
    if sys.platform == "win32":
        mplay_name = "mplay.exe"
    else:
        mplay_name = "mplay"

    failures: list[str] = []

    # Method 1: hou.findFile
    try:
        mplay_path = hou.findFile(f"bin/{mplay_name}")
        if mplay_path and os.path.exists(mplay_path):
            subprocess.Popen([mplay_path, normalized_path])
            return True
        elif mplay_path:
            failures.append(f"method1: resolved path does not exist ({mplay_path})")
        else:
            failures.append("method1: hou.findFile returned empty path")
    except Exception as e:
        failures.append(f"method1: {e}")

    # Method 2: Direct HFS path
    try:
        hfs = hou.getenv("HFS")
        if hfs:
            mplay_direct = os.path.join(hfs, "bin", mplay_name)
            if os.path.exists(mplay_direct):
                subprocess.Popen([mplay_direct, normalized_path])
                return True
            failures.append(f"method2: executable not found at {mplay_direct}")
        else:
            failures.append("method2: HFS not set")
    except Exception as e:
        failures.append(f"method2: {e}")

    # Method 3: Windows default (fallback)
    if sys.platform == "win32":
        try:
            os.startfile(normalized_path)
            return True
        except Exception as e:
            failures.append(f"method3: {e}")

    if failures:
        logger.warning("Failed to open result in MPlay (%s): %s", normalized_path, " | ".join(failures))

    return False


def restyle_viewport(node) -> Optional[str]:
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

        # Validate prompt
        prompt = _eval_parm_str(node, "prompt")
        if not prompt or not prompt.strip():
            hou.ui.displayMessage(
                "Please enter a prompt describing the desired style.",
                title="Bria Error"
            )
            return None

        # Get parameters
        use_cache = _eval_parm_bool(node, "use_cache", default=True)

        # FIBO Edit toggle (default: on)
        use_fibo_edit = _eval_parm_bool(node, "use_fibo_edit", default=True)

        # Get structure influence — used by legacy reimagine path
        structure_influence = float(_eval_parm_float(node, "structure_influence") or 0.75)

        # Get guidance_scale — used by FIBO Edit path
        guidance_scale = int(_eval_parm_int(node, "guidance_scale") or 5)

        # Get negative_prompt — used by FIBO Edit path
        negative_prompt_val = _eval_parm_str(node, "negative_prompt")
        negative_prompt = negative_prompt_val.strip() if negative_prompt_val else None

        # Get seed (0 means no seed / random)
        seed_val = _eval_parm_int(node, "seed") or 0
        seed = seed_val if seed_val > 0 else None

        # Get steps_num (0 means use API default).
        steps_val = _eval_parm_int(node, "steps_num") or 0
        steps_num = clamp_steps_num(steps_val)

        # Get content moderation setting (legacy path only)
        content_moderation = _eval_parm_bool(node, "content_moderation", default=True)

        requested_result_path = _eval_parm_str(node, "result_path")
        if requested_result_path:
            normalized_requested = requested_result_path.replace("\\", "/")
            try:
                hip_dir = str(hou.getenv("HIP") or "").strip().replace("\\", "/")
            except Exception:
                hip_dir = ""

            if hip_dir:
                hip_prefix = hip_dir.rstrip("/") + "/"
                if normalized_requested == hip_dir.rstrip("/") or normalized_requested.startswith(hip_prefix):
                    logger.info(
                        "Ignoring result_path under HIP and using temp output directory instead: %s",
                        normalized_requested,
                    )
                    requested_result_path = ""

        # Step 1: Capture viewport
        if status_parm:
            status_parm.set("Capturing viewport...")

        viewport_path = render_viewport_opengl(node)
        if not viewport_path:
            raise RuntimeError("Failed to capture viewport")

        source_image_parm = _find_parm(node, "source_image")
        if source_image_parm is not None:
            source_image_parm.set(viewport_path)

        # Step 2: Call Bria API
        if status_parm:
            engine = "FIBO Edit" if use_fibo_edit else "Reimagine"
            status_parm.set(f"Restyling with {engine}...")

        result_path = call_bria_restyle(
            image_path=viewport_path,
            prompt=prompt,
            result_path=requested_result_path,
            structure_influence=structure_influence,
            seed=seed,
            steps_num=steps_num,
            content_moderation=content_moderation,
            use_fibo_edit=use_fibo_edit,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt,
            use_cache=use_cache
        )

        if not result_path:
            raise RuntimeError("Failed to get result from Bria")

        result_image_parm = _find_parm(node, "result_image")
        if result_image_parm is not None:
            result_image_parm.set(result_path)
        result_path_parm = _find_parm(node, "result_path")
        if result_path_parm is not None:
            result_path_parm.set(result_path)

        # Step 3: Display in MPlay
        if status_parm:
            status_parm.set("Opening in MPlay...")

        display_in_mplay(result_path)

        # Success
        if status_parm:
            status_parm.set("Done!")

        output_dir = get_output_directory()
        hou.ui.displayMessage(
            f"Bria Restyle Complete!\n\n"
            f"Saved to:\n{result_path}\n\n"
            f"Output folder:\n{output_dir}",
            title="Bria Restyle"
        )

        return result_path

    except Exception as e:
        logger.exception("Restyle failed")
        if status_parm:
            status_parm.set("Error")
        hou.ui.displayMessage(f"Restyle failed: {e}", title="Bria Error")
        return None


# ============== Callback Functions for HDA ==============

def create_camera_callback():
    """Callback for 'Create Camera' button."""
    import hou
    node = hou.pwd()
    create_render_camera(node)


def restyle_viewport_callback():
    """Callback for 'Restyle Viewport' button."""
    import hou
    node = hou.pwd()
    restyle_viewport(node)


def capture_edit_viewport_callback():
    """Callback alias for Main.capture_edit_viewport button."""
    import hou
    node = hou.pwd()
    restyle_viewport(node)


# ============== Apply Texture Functions ==============

def get_available_restyle_images() -> list:
    """
    Scan the output directory for existing restyle images.

    Returns:
        List of tuples: (display_name, full_path) sorted by modification time (newest first)
    """
    import glob

    output_dir = get_output_directory()
    pattern = os.path.join(output_dir, "bria_restyle_*.png")

    images = []
    for filepath in sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True):
        filename = os.path.basename(filepath)
        # Remove prefix and extension for display
        display_name = filename.replace("bria_restyle_", "").replace(".png", "")
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
    Create a material in /mat that uses the restyle image as diffuse texture.

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

    # Set base color to use texture
    material.parm("basecolor_useTexture").set(1)
    material.parm("basecolor_texture").set(image_path)

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

        # Get parameters
        image_path = _eval_parm_str(node, "result_image") or _eval_parm_str(node, "source_image")
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

                # Set material path on material SOP
                if material_sop:
                    material_sop.parm("shop_materialpath1").set(material_path)

                applied_count += 1

            except Exception as e:
                logger.warning(f"Failed to apply texture to {geo_obj.path()}: {e}")

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
        hou.ui.displayMessage(f"Apply texture failed: {e}", title="Bria Error")
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
