"""Houdini Bria FIBO Edit Recipes node logic (thin DCC adapter layer).

A master FIBO Edit node with categorized preset prompts for style transfers,
weather, seasons, time of day, camera effects, lighting, clean/artifacts,
and object edits.  Users can pick a preset and further edit the prompt text
before running.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import hou
import hdefereval

from bria_core.errors import BriaConfigError, BriaRequestError
from bria_core.utils import (
    download_url,
    extract_image_url as _extract_image_url,
    resolve_proxies,
    resolve_temp_dir,
    validate_bria_image_file as _validate_bria_image_file,
)
from houdini.adapter import fibo_edit_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.vgl_parms import assemble_from_parms
from houdini.node_utils import (
    apply_result_to_ui,
    clamp_steps_num,
    debug_logger,
    opt_parm_bool as _opt_parm_bool,
    opt_parm_int as _opt_parm_int,
    opt_parm_str as _opt_parm_str,
    opt_parm_menu_str as _opt_parm_menu_str,
    resolve_output_dir,
    resolve_result_save_path,
    save_api_metadata,
)
if not hasattr(hou.session, "bria_fibo_edit_recipes_session"):
    hou.session.bria_fibo_edit_recipes_session = None


_debug_log = debug_logger("Bria FIBO Edit Recipes")

# ---------------------------------------------------------------------------
# Category definitions: token → list of (preset_token, label, prompt)
# ---------------------------------------------------------------------------
CATEGORY_ORDER = [
    ("custom",       "Custom"),
    ("style",        "Style"),
    ("weather",      "Weather"),
    ("seasons",      "Seasons"),
    ("time_of_day",  "Time of Day"),
    ("camera",       "Camera"),
    ("lighting",     "Lighting"),
    ("compositing",  "Compositing"),
    ("clean",        "Clean / Artifacts"),
    ("object_edits", "Object Edits"),
]

PRESET_CATEGORIES = {
    # ---- Style (18) ----
    "style": [
        ("hand_drawn_classic", "Hand-Drawn Classic",
         "Restyle this image as a hand-drawn animated scene with soft watercolor backgrounds, expressive flowing outlines, painterly surface textures, and the charm of golden-age 2D animation"),
        ("3d_animated", "3D Animated",
         "Restyle this image in a modern 3D animated feature style with smooth stylized forms, soft subsurface skin shading, vivid saturated colors, and cinematic character-focused lighting"),
        ("japanese_fantasy_anime", "Japanese Fantasy Anime",
         "Restyle this image as a lush hand-painted Japanese fantasy anime scene with richly detailed natural environments, soft atmospheric depth, translucent light filtering through foliage, and a warm luminous storybook quality"),
        ("cel_shaded_anime", "Cel-Shaded Anime",
         "Restyle this image in a clean cel-shaded anime style with bold outlines, flat color fills, crisp shadow shapes, and vivid high-contrast animation styling"),
        ("film_noir", "Film Noir",
         "Restyle this image as classic film noir with stark black-and-white contrast, dramatic chiaroscuro lighting, deep oppressive shadows, hard-edged rim light, and moody atmospheric grain"),
        ("aaa_game", "AAA Game",
         "Restyle this image as a photorealistic AAA game scene with high-fidelity materials, realistic surface detail, volumetric lighting, cinematic depth, and polished next-generation rendering"),
        ("blockbuster_cinematic", "Blockbuster Cinematic",
         "Restyle this image with a blockbuster cinematic look featuring anamorphic lens character, dramatic teal-and-orange grading, shallow depth of field, lens flares, and epic large-scale lighting"),
        ("indie_film", "Indie Film",
         "Restyle this image with an indie film aesthetic featuring naturalistic lighting, muted slightly desaturated color, subtle film grain, intimate focus, and a grounded lived-in mood"),
        ("tv_sitcom", "TV Sitcom",
         "Restyle this image as a multi-camera TV sitcom scene with bright even studio lighting, warm neutral color balance, sharp focus throughout, and a clean polished broadcast look"),
        ("oil_painting", "Oil Painting",
         "Restyle this image as a classical oil painting with visible brushwork, rich impasto texture, layered glazing, deep tonal contrast, and dramatic old-master lighting"),
        ("watercolor", "Watercolor",
         "Restyle this image as a delicate watercolor painting with transparent washes, wet-on-wet blending, visible paper texture, soft color transitions, and gently feathered edges"),
        ("comic_book", "Comic Book",
         "Restyle this image as a comic book illustration with bold ink outlines, halftone shading, strong graphic color, punchy contrast, and dynamic printed-comic energy"),
        ("pencil_sketch", "Pencil Sketch",
         "Restyle this image as a detailed pencil sketch with fine cross-hatching, soft graphite shading, subtle tonal gradation, and the textured surface of drawing paper"),
        ("retro_pixel", "Retro Pixel Art",
         "Restyle this image as retro pixel art with a limited color palette, visible pixel structure, dithering patterns, simplified forms, and the nostalgic look of 8-bit and 16-bit graphics"),
        ("cyberpunk", "Cyberpunk",
         "Restyle this image with a cyberpunk aesthetic featuring dark moody shadows, vivid neon magenta and cyan accent lighting, holographic overlays, glossy reflective surfaces, and a high-tech dystopian atmosphere"),
        ("steampunk", "Steampunk",
         "Restyle this image with a steampunk aesthetic featuring brass and copper materials, warm sepia tones, Victorian industrial design, mechanical detailing, and soft gaslit ambience"),
        ("pop_art", "Pop Art",
         "Restyle this image as bold pop art with bright flat colors, thick graphic outlines, halftone dot patterns, strong contrast, and playful poster-like visual impact"),
        ("art_nouveau", "Art Nouveau",
         "Restyle this image in an Art Nouveau style with flowing organic curves, elegant ornamental design, floral motifs, soft pastel color, and refined decorative linework"),
    ],

    # ---- Weather (8) ----
    "weather": [
        ("sunny_clear", "Sunny & Clear",
         "Change the weather to a bright clear sunny day with blue skies, crisp shadows, high visibility, and warm natural sunlight"),
        ("overcast", "Overcast",
         "Change the weather to an overcast day with a soft gray sky, diffused light, muted colors, and a calm evenly lit atmosphere"),
        ("rainy", "Rainy",
         "Change the weather to rain with visible falling raindrops, wet reflective surfaces, puddles, softened contrast, and a cool overcast atmosphere"),
        ("thunderstorm", "Thunderstorm",
         "Change the weather to a heavy thunderstorm with dark storm clouds, flashes of lightning, intense rainfall, turbulent skies, and dramatic storm energy"),
        ("snowy", "Snowy",
         "Change the weather to snowfall with drifting snowflakes, snow accumulation on surfaces, softened ambience, and a cold wintry atmosphere"),
        ("foggy", "Foggy / Misty",
         "Change the weather to dense fog or mist with reduced visibility, soft atmospheric diffusion, muted contrast, and an ethereal atmospheric veil"),
        ("windy", "Windy",
         "Change the weather to strong wind with blowing leaves and debris, swaying foliage, windswept hair or clothing where visible, and fast-moving turbulent clouds"),
        ("hazy_humid", "Hazy / Humid",
         "Change the weather to a hazy humid day with warm air softness, gentle light scatter, slight atmospheric diffusion, and an oppressive summer heat feel"),
    ],

    # ---- Seasons (4) ----
    "seasons": [
        ("spring", "Spring",
         "Change this scene to spring with fresh green growth, blooming flowers, blossoms, soft warm daylight, and a renewed lively atmosphere"),
        ("summer", "Summer",
         "Change this scene to peak summer with lush deep green vegetation, bright intense sunlight, vivid saturated color, and subtle heat shimmer"),
        ("autumn", "Autumn",
         "Change this scene to autumn with orange, red, and gold foliage, scattered fallen leaves, warm angled sunlight, and a cozy harvest-season atmosphere"),
        ("winter", "Winter",
         "Change this scene to winter with bare branches, frost-covered surfaces, cold blue-white light, and a crisp frozen seasonal mood"),
    ],

    # ---- Time of Day (8) ----
    "time_of_day": [
        ("dawn", "Dawn",
         "Change the time of day to early dawn with soft pink and lavender sky gradients, first light on the horizon, long quiet shadows, and a calm waking atmosphere"),
        ("morning", "Morning",
         "Change the time of day to morning with warm fresh sunlight, clear air, gentle shadows, and bright uplifting natural light"),
        ("golden_hour", "Golden Hour",
         "Change the time of day to golden hour with rich amber sunlight, long dramatic shadows, glowing edge light, and a warm cinematic atmosphere"),
        ("midday", "Midday",
         "Change the time of day to bright midday with overhead sun, short defined shadows, strong direct light, and intense daylight clarity"),
        ("blue_hour", "Blue Hour",
         "Change the time of day to blue hour with deep cobalt sky tones, cool ambient twilight, softly emerging practical lights, and a serene transitional mood"),
        ("dusk", "Dusk",
         "Change the time of day to dusk with warm sunset color on the horizon, deepening purples overhead, silhouetted forms, and a fading evening glow"),
        ("night", "Night",
         "Change the time of day to night with a dark sky, moonlight or ambient night illumination, deep shadows, and pools of warm artificial light where appropriate"),
        ("starry_night", "Starry Night",
         "Change the time of day to a clear starry night with a vast star-filled sky, subtle moonlit ambience, deep darkness, and a calm expansive nighttime atmosphere"),
    ],

    # ---- Camera (8) ----
    "camera": [
        ("shallow_dof", "Shallow Depth of Field",
         "Apply a shallow depth of field with the main subject in sharp focus and a softly blurred background with smooth creamy bokeh"),
        ("tilt_shift", "Tilt Shift",
         "Apply a tilt-shift miniature look with selective focus bands, compressed scale perception, and saturated toy-like visual character"),
        ("wide_angle", "Wide Angle",
         "Apply a wide-angle lens look with expanded perspective, subtle barrel distortion, and exaggerated spatial depth"),
        ("macro_closeup", "Macro Close-Up",
         "Apply a macro close-up look with extreme detail, very shallow focus, and strong emphasis on fine surface texture"),
        ("birds_eye", "Bird's Eye View",
         "Reframe this image as an overhead bird's-eye view, emphasizing layout, geometry, spatial patterns, and a top-down perspective"),
        ("dutch_angle", "Dutch Angle",
         "Apply a Dutch angle with a deliberate camera tilt, creating diagonal framing, psychological unease, and dynamic visual tension"),
        ("long_exposure", "Long Exposure",
         "Apply a long-exposure photography effect with motion blur on moving elements, smooth flowing motion, light trails where appropriate, and crisp static details"),
        ("fisheye", "Fisheye",
         "Apply a fisheye lens effect with extreme wide-angle distortion, curved perspective, and a strongly warped spherical field of view"),
    ],

    # ---- Lighting (8) ----
    "lighting": [
        ("dramatic_side", "Dramatic Side Light",
         "Apply dramatic side lighting with a strong directional source from one side, sculpted highlights, deep shadow contrast, and pronounced dimensional form"),
        ("rim_backlight", "Rim / Backlight",
         "Apply rim and backlighting with glowing edge highlights, bright rear illumination, strong subject separation, and a dramatic luminous outline"),
        ("soft_diffused", "Soft Diffused",
         "Apply soft diffused lighting with gentle shadow falloff, even illumination, flattering contrast, and a clean polished appearance"),
        ("neon_glow", "Neon Glow",
         "Apply vibrant neon lighting with glowing magenta, cyan, and purple light sources, colorful reflections, and saturated luminous ambience"),
        ("candlelight", "Candlelight",
         "Apply warm candlelight illumination with soft flickering orange glow, intimate shadowing, gentle contrast, and a cozy low-light atmosphere"),
        ("studio_three_point", "Studio Three-Point",
         "Apply professional three-point studio lighting with balanced key, fill, and back light for clean controlled illumination and clear subject separation"),
        ("volumetric_rays", "Volumetric Rays",
         "Apply volumetric light rays with visible shafts of light, atmospheric particles, depth through haze, and dramatic illuminated atmosphere"),
        ("harsh_flash", "Harsh Flash",
         "Apply a direct harsh flash look with frontal lighting, sharp cast shadows, strong specular highlights, and a stark paparazzi-style photographic effect"),
    ],

    # ---- Clean / Artifacts (8) ----
    "clean": [
        ("color_correction", "Color Correction",
         "Apply professional color correction with balanced exposure, corrected color cast, natural-looking contrast, and clean accurate color throughout the image"),
        ("gamma_correction", "Gamma Correction",
         "Adjust gamma to improve midtone brightness, reveal detail in the middle tonal range, and enhance perceptual contrast without blowing highlights or crushing shadows"),
        ("fix_artifacts", "Fix Artifacts",
         "Remove visual artifacts such as compression blocking, banding, ringing, and digital distortion while preserving true image detail and edge integrity"),
        ("remove_noise", "Remove Noise",
         "Remove visible noise and grain while preserving fine detail, natural texture, and clean edge definition"),
        ("sharpen", "Sharpen",
         "Sharpen the image to enhance fine detail and edge clarity without introducing halos, ringing, or oversharpened artifacts"),
        ("fix_white_balance", "Fix White Balance",
         "Correct the white balance to remove unwanted color casts and restore neutral whites and believable scene color"),
        ("fix_exposure", "Fix Exposure",
         "Recover blown highlights and crushed shadows, restoring detail at both tonal extremes while maintaining natural midtone brightness"),
        ("reduce_chromatic_aberration", "Fix Chromatic Aberration",
         "Remove chromatic aberration and color fringing along high-contrast edges for cleaner optical accuracy throughout the image"),
    ],

    # ---- Compositing (8) ----
    "compositing": [
        ("harmonize_lighting", "Harmonize Lighting",
         "Harmonize the lighting across all elements in this composite so that light direction, intensity, color temperature, and falloff are consistent throughout the scene"),
        ("match_shadows", "Match Shadows",
         "Add or correct shadows for all composited elements so shadow direction, softness, density, and ground contact are consistent with the scene's primary light source"),
        ("blend_edges", "Blend Edges",
         "Soften and blend the hard edges of composited elements into the surrounding scene with natural feathering, anti-aliasing, and seamless edge transitions"),
        ("color_harmonize", "Color Harmonize",
         "Unify the color palette across all composited elements by matching color temperature, saturation, contrast curve, and overall color grading to the background environment"),
        ("fix_reflections", "Fix Reflections",
         "Add or correct reflections for composited objects on nearby reflective surfaces such as water, glass, polished floors, or metal, matching the scene's reflection behavior"),
        ("integrate_elements", "Integrate Elements",
         "Seamlessly integrate all composited elements into the scene by harmonizing lighting, shadows, reflections, edges, color grading, and atmospheric perspective to match the environment"),
        ("match_ambient", "Match Ambient Light",
         "Adjust the ambient light and environmental fill on composited elements to match the scene's overall ambient illumination, bounce light, and atmospheric color"),
        ("depth_consistency", "Depth Consistency",
         "Apply consistent depth cues across composited elements including atmospheric haze, focus falloff, scale, and contrast reduction to match the scene's spatial depth"),
    ],

    # ---- Object Edits (12) ----
    "object_edits": [
        ("delete_object", "Delete Object",
         "Delete the specified object from the scene and seamlessly inpaint the area behind it, reconstructing the background naturally without leaving visible traces"),
        ("replace_object", "Replace Object",
         "Replace the specified object with the described replacement, matching the scene's lighting, perspective, scale, and visual style so the new object integrates naturally"),
        ("change_object_color", "Change Object Color",
         "Change the color of the specified object to the described color while preserving its shape, texture, material properties, lighting response, and all surrounding scene elements"),
        ("change_object_material", "Change Object Material",
         "Change the material or surface texture of the specified object to the described material while preserving its shape, lighting integration, and scene consistency"),
        ("add_vegetation", "Add Vegetation",
         "Add natural-looking vegetation appropriate to the scene, including plants, grass, shrubs, trees, and foliage where visually suitable"),
        ("add_people", "Add People",
         "Add natural-looking people appropriate to the scene's setting, scale, perspective, and context"),
        ("add_clouds", "Add Clouds",
         "Add natural cloud formations appropriate to the sky, such as wispy cirrus or soft cumulus, to enrich the atmosphere and sky detail"),
        ("remove_people", "Remove People",
         "Remove all visible people from the scene and naturally reconstruct the background and surrounding environment behind them"),
        ("add_water_reflection", "Add Water Reflection",
         "Add a water surface with realistic reflections, subtle ripples, and natural reflective behavior integrated into the scene"),
        ("age_weathering", "Add Aging / Weathering",
         "Add realistic aging and weathering with patina, rust, wear, faded paint, surface erosion, and the visual character of time"),
        ("modernize", "Modernize",
         "Modernize the scene by replacing dated visual elements with contemporary equivalents, including clean surfaces, modern materials, updated design details, and current-era objects where appropriate"),
        ("add_text_overlay", "Add Text Overlay",
         "Add a stylized typographic or graphic overlay integrated into the composition, suited to the image's mood, visual balance, and overall design"),
    ],
}

# Flat lookup: preset_token → prompt text (built once at import time).
ALL_PRESETS = {}
for _cat_presets in PRESET_CATEGORIES.values():
    for _token, _label, _prompt in _cat_presets:
        ALL_PRESETS[_token] = _prompt


def _resolve_prompt(cop_node: hou.Node) -> tuple[str, str]:
    """Return (preset_key, prompt_text) from the current category/preset state.

    If category is 'custom', reads the prompt parm directly.
    Otherwise looks up the active per-category preset menu.
    The prompt parm is always the authoritative source — presets merely
    auto-populate it, and the user can edit freely.
    """
    category = _opt_parm_menu_str(cop_node, "category") or "custom"
    if category == "custom":
        return "custom", (_opt_parm_str(cop_node, "prompt") or "").strip()

    # Read the active preset for this category
    parm_name = f"preset_{category}"
    preset_key = _opt_parm_menu_str(cop_node, parm_name) or ""

    # Always use the prompt field (user may have edited it)
    prompt = (_opt_parm_str(cop_node, "prompt") or "").strip()
    return preset_key or category, prompt


def on_category_changed(kwargs: dict) -> None:
    """Callback when the category menu changes — update prompt from first preset."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _opt_parm_menu_str(node, "category") or "custom"
    if category == "custom":
        node.parm("prompt").set("")
        return
    presets = PRESET_CATEGORIES.get(category)
    if presets:
        # Reset the per-category preset menu to index 0
        preset_parm = node.parm(f"preset_{category}")
        if preset_parm is not None:
            preset_parm.set(0)
        # Auto-fill prompt with first preset's text
        node.parm("prompt").set(presets[0][2])


def on_preset_changed(kwargs: dict) -> None:
    """Callback when any per-category preset menu changes — update prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _opt_parm_menu_str(node, "category") or "custom"
    if category == "custom":
        return
    parm_name = f"preset_{category}"
    preset_key = _opt_parm_menu_str(node, parm_name) or ""
    prompt_text = ALL_PRESETS.get(preset_key, "")
    if prompt_text:
        node.parm("prompt").set(prompt_text)


def fibo_edit_recipes_bria(cop_node: hou.Node) -> None:
    t_start_click = time.perf_counter()

    try:
        preset_key, prompt = _resolve_prompt(cop_node)

        # Priority: VGL structured parms -> raw structured_prompt
        structured_prompt = assemble_from_parms(cop_node)
        if not structured_prompt:
            structured_prompt = (_opt_parm_str(cop_node, "structured_prompt") or "").strip()
        negative_prompt = (_opt_parm_str(cop_node, "negative_prompt") or "").strip()

        if not prompt and not structured_prompt:
            hou.ui.displayMessage(
                "Select a preset or enter a custom prompt.",
                severity=hou.severityType.Error,
                title="Bria FIBO Edit",
            )
            return

        inputs = cop_node.inputs()
        input_op = inputs[0] if len(inputs) > 0 else None

        temp_dir = resolve_temp_dir(hou)

        run_id = str(int(time.time() * 1000))
        img_path = os.path.join(temp_dir, f"bria_fibo_edit_recipes_input_{run_id}.png")
        out_path = resolve_output_dir(temp_dir, run_id, "fibo_edit_recipes")

        t_disk_start = time.perf_counter()
        if input_op is None:
            hou.ui.setStatusMessage(
                "Connect an image to input 1",
                severity=hou.severityType.Error,
            )
            return
        img_path = (
            export_via_internal_rop(cop_node, "rop_save_input", img_path)
            or cop_to_png(input_op, img_path)
        )

        _validate_bria_image_file(img_path, "Input image")

        t_disk_end = time.perf_counter()
        _debug_log(f"Disk Write Overhead: {(t_disk_end - t_disk_start):.4f} sec")

        guidance_scale = _opt_parm_int(cop_node, "guidance_scale")
        if guidance_scale is not None and guidance_scale > 0:
            guidance_scale = min(guidance_scale, 5)
        else:
            guidance_scale = None
        seed = _opt_parm_int(cop_node, "seed")
        if seed is not None and seed <= 0:
            seed = None
        steps_num = clamp_steps_num(_opt_parm_int(cop_node, "steps_num"))

        use_bearer_auth = bool(_opt_parm_bool(cop_node, "use_bearer_auth"))

        use_env_proxy = _opt_parm_bool(cop_node, "use_env_proxy")
        http_proxy = _opt_parm_str(cop_node, "http_proxy")
        https_proxy = _opt_parm_str(cop_node, "https_proxy")
        proxies = resolve_proxies(
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            use_env_proxy=use_env_proxy,
        )

        api_key = _opt_parm_str(cop_node, "api_token")
        if api_key:
            msg = "Bria FIBO Edit Presets: api_token parm is deprecated. Prefer config/env-based auth."
            _debug_log(msg)
            try:
                hou.ui.setStatusMessage(msg, severity=hou.severityType.Warning)
            except Exception:
                pass
        api_endpoint = _opt_parm_str(cop_node, "api_base_url")

        _debug_log(f"Preset: {preset_key} | Prompt: {prompt[:80]}...")

        data = fibo_edit_from_files(
            image_path=img_path,
            prompt=prompt or None,
            structured_prompt=structured_prompt or None,
            guidance_scale=guidance_scale,
            negative_prompt=negative_prompt or None,
            seed=seed,
            steps_num=steps_num,
            api_key=api_key,
            api_endpoint=api_endpoint,
            use_bearer=use_bearer_auth,
            proxies=proxies,
            session=hou.session.bria_fibo_edit_recipes_session,
        )

        dl_url = _extract_image_url(data)
        if not dl_url:
            raise BriaRequestError(f"Unexpected API response (no image_url): {data}")

        t_dl_start = time.perf_counter()
        img_bytes, content_type = download_url(dl_url, timeout_s=300, proxies=proxies)
        t_dl_end = time.perf_counter()

        save_path = resolve_result_save_path(out_path, content_type)

        with open(save_path, "wb") as f:
            f.write(img_bytes)

        if not os.path.exists(save_path) or os.path.getsize(save_path) <= 0:
            raise RuntimeError(f"Bria download produced an empty file: {save_path}")

        t_final = time.perf_counter()
        total_time = t_final - t_start_click
        api_time = t_dl_start - t_disk_end
        dl_time = t_dl_end - t_dl_start

        _debug_log(f"API Edit Time:    {api_time:.4f} sec")
        _debug_log(f"Image Download:   {dl_time:.4f} sec")
        _debug_log(f"Total Turnaround: {total_time:.4f} sec")
        _debug_log(
            f"Saved result: {save_path} ({os.path.getsize(save_path)} bytes) | content-type={content_type or 'unknown'}"
        )

        save_api_metadata(save_path, data, "fibo_edit_recipes", {
            "api_time": round(api_time, 4),
            "download_time": round(dl_time, 4),
            "total_time": round(total_time, 4),
            "preset": preset_key,
        }, request_params={
            "prompt": prompt or None,
            "structured_prompt": structured_prompt or None,
            "negative_prompt": negative_prompt or None,
            "preset": preset_key,
        })

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria FIBO Edit Complete ({total:.2f}s) \u2192 {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria FIBO Edit Presets Error: {repr(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria FIBO Edit Presets Exception: {repr(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_fibo_edit_recipes(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    fibo_edit_recipes_bria(node)
