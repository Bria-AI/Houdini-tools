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
    ensure_api_aspect_ratio as _ensure_api_aspect_ratio,
    extract_image_url as _extract_image_url,
    resolve_proxies,
    resolve_temp_dir,
    validate_bria_image_file as _validate_bria_image_file,
)
from houdini.adapter import fibo_edit_from_files
from houdini.cop_export import cop_to_png, export_via_internal_rop
from houdini.vgl_parms import assemble_from_parms
from houdini.node_utils import (
    _safe_exc_str,
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
    store_vgl_from_response,
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
    ("clean",           "Clean / Artifacts"),
    ("ai_corrections",  "AI Corrections"),
    ("object_edits",    "Object Edits"),
]

# ---------------------------------------------------------------------------
# Object-targeting presets: structured constraint backbones
# ---------------------------------------------------------------------------
TARGETED_OBJECT_PRESETS = frozenset({
    "delete_object", "replace_object", "change_object_color", "change_object_material",
})

# Action sentence templates per preset.
# {obj1} = single object name, {mod1} = single modifier (replacement/color/material)
# {obj_list} = comma-separated object names
# {obj_mod_list} = semicolon-separated "object to modifier" pairs
_OBJ_ACTIONS = {
    "delete_object": {
        "fallback": "Delete the specified object from the scene.",
        "single": "Delete {obj1} from the scene.",
        "multi": "Delete the following objects from the scene: {obj_list}.",
    },
    "replace_object": {
        "fallback": "Replace the specified object with the described replacement.",
        "single": "Replace {obj1} with {mod1}.",
        "multi": "Replace the following objects: {obj_mod_list}.",
    },
    "change_object_color": {
        "fallback": "Change the color of the specified object to the described color.",
        "single": "Change the color of {obj1} to {mod1}.",
        "multi": "Change the colors of the following objects: {obj_mod_list}.",
    },
    "change_object_material": {
        "fallback": "Change the material of the specified object to the described material.",
        "single": "Change the material of {obj1} to {mod1}.",
        "multi": "Change the materials of the following objects: {obj_mod_list}.",
    },
}

# Structured constraint body per preset (after the action sentence)
_OBJ_BODIES = {
    "delete_object": (
        "STRICT LOCKS (non-negotiable):\n"
        "Do NOT move, warp, scale, rotate, or reshape any remaining objects.\n"
        "Do NOT change the overall color grade, lighting, or artistic style.\n"
        "Do NOT alter any objects other than those specified for deletion.\n"
        "Scope of work:\n"
        "Completely remove the specified object(s) from the scene.\n"
        "Seamlessly inpaint the revealed area behind each deleted object, reconstructing the background naturally.\n"
        "Match the inpainted region's texture, lighting, and perspective to the surrounding scene.\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to the deleted object(s) and the area directly behind them.\n"
        "Do NOT remove or modify any other objects in the scene.\n"
        "Do NOT change the background outside the inpainted regions.\n"
        "The inpainted area must be indistinguishable from the original background.\n"
        "Result requirement:\n"
        "The output should appear as if the deleted object(s) were never present. "
        "If the specified object cannot be identified, return the image unchanged."
    ),
    "replace_object": (
        "STRICT LOCKS (non-negotiable):\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects other than the one(s) being replaced.\n"
        "Do NOT change the overall color grade, lighting direction, or artistic style.\n"
        "Do NOT alter the background or surrounding scene elements.\n"
        "Scope of work:\n"
        "Remove the specified object(s) and place the described replacement(s) in the same position.\n"
        "Match the replacement's lighting, perspective, scale, and shadow to the scene.\n"
        "Blend the replacement naturally into the surrounding environment.\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to the replaced object(s) and their immediate surroundings.\n"
        "The replacement must occupy approximately the same spatial footprint as the original.\n"
        "Do NOT change any other objects or scene elements.\n"
        "Preserve the scene's existing lighting direction and shadow behavior.\n"
        "Result requirement:\n"
        "The output should appear as if the replacement object(s) were always part of the original scene. "
        "If the specified object cannot be identified, return the image unchanged."
    ),
    "change_object_color": (
        "STRICT LOCKS (non-negotiable):\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change the overall color grade, lighting, or artistic style.\n"
        "Do NOT alter any objects other than those specified for color change.\n"
        "Scope of work:\n"
        "Change only the color of the specified object(s) to the described target color(s).\n"
        "Preserve each object's shape, texture detail, material properties, and surface finish.\n"
        "Maintain correct lighting response — highlights, shadows, and reflections should adapt naturally to the new color.\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to the surface color of the specified object(s).\n"
        "Do NOT change the object's shape, texture pattern, or material type.\n"
        "Do NOT affect the background or any other objects.\n"
        "Do NOT alter the scene's lighting or shadows beyond natural color-dependent changes.\n"
        "Result requirement:\n"
        "The output should appear as if the object(s) were always the target color, with natural lighting response. "
        "If the specified object cannot be identified, return the image unchanged."
    ),
    "change_object_material": (
        "STRICT LOCKS (non-negotiable):\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change the overall color grade, lighting direction, or artistic style.\n"
        "Do NOT alter any objects other than those specified for material change.\n"
        "Scope of work:\n"
        "Change only the material and surface texture of the specified object(s) to the described target material(s).\n"
        "Preserve each object's shape and silhouette exactly.\n"
        "Apply correct material properties — reflectivity, roughness, transparency, and texture pattern appropriate to the new material.\n"
        "Maintain natural lighting response for the new material.\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to the surface material of the specified object(s).\n"
        "Do NOT change the object's shape, size, or position.\n"
        "Do NOT affect the background or any other objects.\n"
        "Lighting and shadow changes should only reflect the new material's natural properties.\n"
        "Result requirement:\n"
        "The output should appear as if the object(s) were always made of the target material, with correct surface properties. "
        "If the specified object cannot be identified, return the image unchanged."
    ),
}


def _obj_fallback_prompt(key: str) -> str:
    """Build the default structured prompt for an object preset (no objects specified)."""
    return _OBJ_ACTIONS[key]["fallback"] + "\n" + _OBJ_BODIES[key]


# ---------------------------------------------------------------------------
# Compositing-element-targeting presets: structured constraint backbones
# ---------------------------------------------------------------------------
TARGETED_COMP_PRESETS = frozenset({
    "harmonize_lighting", "match_shadows", "blend_edges", "color_harmonize",
    "fix_reflections", "integrate_elements", "match_ambient",
})

# Action sentence templates per compositing preset.
# {elem1} = single element description
# {elem_list} = comma-separated element descriptions
_COMP_ACTIONS = {
    "harmonize_lighting": {
        "fallback": "Perform a targeted lighting harmonization pass on this composite image.",
        "single": "Perform a targeted lighting harmonization pass on this composite image, focusing on {elem1}.",
        "multi": "Perform a targeted lighting harmonization pass on this composite image, focusing on the following composited elements: {elem_list}.",
    },
    "match_shadows": {
        "fallback": "Perform a targeted shadow correction pass on this composite image.",
        "single": "Perform a targeted shadow correction pass on this composite image, focusing on {elem1}.",
        "multi": "Perform a targeted shadow correction pass on this composite image, focusing on the following composited elements: {elem_list}.",
    },
    "blend_edges": {
        "fallback": "Perform a targeted edge blending pass on this composite image.",
        "single": "Perform a targeted edge blending pass on this composite image, focusing on the edges of {elem1}.",
        "multi": "Perform a targeted edge blending pass on this composite image, focusing on the edges of the following composited elements: {elem_list}.",
    },
    "color_harmonize": {
        "fallback": "Perform a targeted color harmonization pass on this composite image.",
        "single": "Perform a targeted color harmonization pass on this composite image, focusing on {elem1}.",
        "multi": "Perform a targeted color harmonization pass on this composite image, focusing on the following composited elements: {elem_list}.",
    },
    "fix_reflections": {
        "fallback": "Perform a targeted reflection correction pass on this composite image.",
        "single": "Perform a targeted reflection correction pass on this composite image, focusing on reflections of {elem1}.",
        "multi": "Perform a targeted reflection correction pass on this composite image, focusing on reflections of the following composited elements: {elem_list}.",
    },
    "integrate_elements": {
        "fallback": "Perform a targeted compositing cleanup pass on the image.",
        "single": "Perform a targeted compositing cleanup pass on this image, focusing on {elem1}.",
        "multi": "Perform a targeted compositing cleanup pass on this image, focusing on the following composited elements: {elem_list}.",
    },
    "match_ambient": {
        "fallback": "Perform a targeted ambient light matching pass on this composite image.",
        "single": "Perform a targeted ambient light matching pass on this composite image, focusing on {elem1}.",
        "multi": "Perform a targeted ambient light matching pass on this composite image, focusing on the following composited elements: {elem_list}.",
    },
}

# Structured constraint body per compositing preset (after the action sentence)
_COMP_BODIES = {
    "harmonize_lighting": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change the overall color grade or artistic style.\n"
        "Scope of work (local fixes only):\n"
        "Identify regions where composited elements have inconsistent lighting compared to the scene, including:\n"
        "- light direction mismatch (highlights/shadows facing wrong way)\n"
        "- intensity mismatch (element too bright or too dark for the scene)\n"
        "- color temperature mismatch (warm element in cool scene or vice versa)\n"
        "- missing or incorrect light falloff on composited objects\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- adjust highlight and shadow placement on affected elements to match scene light direction\n"
        "- correct brightness/exposure ONLY on mismatched elements to blend with surroundings\n"
        "- shift color temperature ONLY on affected elements to match the scene's dominant light\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to composited elements that show lighting inconsistency.\n"
        "Do NOT re-light the entire scene or change the background lighting.\n"
        "Do NOT add new light sources or remove existing ones.\n"
        "Do NOT alter textures, materials, or shapes.\n"
        "Result requirement:\n"
        "The output should appear as if all elements were photographed under the same lighting conditions. If no lighting issues are detected, return the image unchanged."
    ),
    "match_shadows": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change global lighting, color balance, or overall image appearance.\n"
        "Scope of work (local fixes only):\n"
        "Identify regions where composited elements have incorrect or missing shadows, including:\n"
        "- shadow direction inconsistent with the scene's primary light source\n"
        "- missing contact shadows where objects meet surfaces\n"
        "- shadow softness/hardness not matching the scene's light quality\n"
        "- shadow density too strong or too weak relative to scene shadows\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- add or reposition contact shadows at object bases to match scene light direction\n"
        "- adjust shadow softness to match the scene's diffusion level\n"
        "- correct shadow density/opacity to be consistent with existing scene shadows\n"
        "- blend shadow edges naturally into the ground plane\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to shadow regions of composited elements.\n"
        "Do NOT modify the objects themselves, only their shadows.\n"
        "Do NOT change scene lighting or add new light sources.\n"
        "Do NOT affect areas that already have correct shadows.\n"
        "Result requirement:\n"
        "The output should have consistent shadow behavior across all elements as if lit by the same source. If no shadow issues are detected, return the image unchanged."
    ),
    "blend_edges": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change global lighting, shadows, or color balance.\n"
        "Do NOT modify the overall image appearance or grade.\n"
        "Scope of work (local fixes only):\n"
        "Identify regions where composited elements have visible edge artifacts, including:\n"
        "- hard cutout edges with aliasing or jagged pixels\n"
        "- visible halos, fringing, or matte lines around composited objects\n"
        "- unnatural sharp boundaries between foreground elements and background\n"
        "- color spill or edge contamination from the original background\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- soften and anti-alias hard edges to remove visible matte lines\n"
        "- remove halos and fringing artifacts along element boundaries\n"
        "- gently blend transitions between foreground edges and background\n"
        "- clean color spill at edges to match adjacent background pixels\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to the edge regions of composited elements (within a few pixels of boundaries).\n"
        "Do NOT affect the interior of any element or the background.\n"
        "Do NOT blur or soften the overall image.\n"
        "Do NOT change the shape or silhouette of any object.\n"
        "Result requirement:\n"
        "The output should have clean, natural-looking edges on all composited elements with no visible cutout artifacts. If no edge issues are detected, return the image unchanged."
    ),
    "color_harmonize": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change the lighting direction, shadow placement, or overall exposure.\n"
        "Scope of work (local fixes only):\n"
        "Identify composited elements whose color characteristics do not match the scene, including:\n"
        "- color temperature mismatch (element shot under different lighting than the background)\n"
        "- saturation mismatch (element more or less saturated than surroundings)\n"
        "- contrast curve mismatch (element has different tonal range than scene)\n"
        "- overall color cast inconsistency between elements and background\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- shift color temperature of affected elements to match the scene's dominant color\n"
        "- adjust saturation ONLY on mismatched elements to blend with surroundings\n"
        "- match contrast and tonal curve of elements to the background's tonal range\n"
        "- remove conflicting color casts from composited elements\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to composited elements that show color inconsistency.\n"
        "Do NOT apply a new color grade to the entire image.\n"
        "Do NOT change the background's color characteristics.\n"
        "Do NOT alter textures, materials, or object identity.\n"
        "Result requirement:\n"
        "The output should appear as if all elements share the same color environment and were captured in the same scene. If no color issues are detected, return the image unchanged."
    ),
    "fix_reflections": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change global lighting, shadows, or color balance.\n"
        "Do NOT modify the overall image appearance or grade.\n"
        "Scope of work (local fixes only):\n"
        "Identify regions where composited elements are missing reflections or have incorrect reflections on nearby reflective surfaces, including:\n"
        "- missing reflections on water, glass, polished floors, or metal surfaces\n"
        "- reflection angle inconsistent with the object's position and the camera\n"
        "- reflection intensity or blur not matching the surface's reflective properties\n"
        "- reflection color not matching the reflected object\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- add subtle reflections where composited objects meet reflective surfaces\n"
        "- adjust existing reflections to match correct angle and perspective\n"
        "- match reflection blur and intensity to the surface's material properties\n"
        "- ensure reflection color and brightness are consistent with the scene\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to reflective surface areas near composited elements.\n"
        "Do NOT add reflections to non-reflective surfaces.\n"
        "Do NOT modify the objects themselves, only their reflections.\n"
        "Do NOT change the reflective surface's material or appearance.\n"
        "Result requirement:\n"
        "The output should have consistent reflection behavior for all composited elements on nearby reflective surfaces. If no reflection issues are detected, return the image unchanged."
    ),
    "integrate_elements": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change global lighting, shadows, or color balance.\n"
        "Do NOT modify the overall image appearance or grade.\n"
        "Scope of work (local fixes only):\n"
        "Identify small regions where elements appear poorly composited, including:\n"
        "- edge artifacts (aliasing, halos, fringing, cutout edges)\n"
        "- minor color mismatch against immediate surroundings\n"
        "- slight exposure or contrast mismatch\n"
        "- missing or weak contact grounding at object boundaries\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- clean and soften edges to remove visible matte lines\n"
        "- subtly adjust color/exposure ONLY within affected elements to match adjacent pixels\n"
        "- add or refine very subtle contact shadowing only at object boundaries if clearly missing\n"
        "- gently blend transitions between foreground and background\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to small, specific regions.\n"
        "Do NOT affect large areas of the image.\n"
        "Do NOT introduce new lighting, new shadows, or re-light the scene.\n"
        "Do NOT change textures, materials, or shapes.\n"
        "Do NOT enhance or stylize \u2014 this is a corrective pass only.\n"
        "Result requirement:\n"
        "The output should appear almost identical to the original image, with only subtle fixes visible upon close inspection. If no issues are detected, return the image unchanged."
    ),
    "match_ambient": (
        "STRICT LOCKS (non-negotiable):\n"
        "The image must remain pixel-identical in layout and composition.\n"
        "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
        "Do NOT change the primary directional lighting or shadow placement.\n"
        "Do NOT modify the overall image grade or artistic style.\n"
        "Scope of work (local fixes only):\n"
        "Identify composited elements whose ambient illumination does not match the scene, including:\n"
        "- shadow regions too dark or too light compared to scene's ambient fill\n"
        "- missing environmental bounce light that the scene provides\n"
        "- ambient color in shadow areas not matching the scene's ambient color (e.g., blue sky fill, warm ground bounce)\n"
        "- overall ambient exposure level on element inconsistent with surroundings\n"
        "Apply ONLY minimal, localized corrections:\n"
        "- adjust shadow fill brightness on affected elements to match scene's ambient level\n"
        "- tint ambient/shadow areas of elements to match the scene's environmental color\n"
        "- add subtle bounce light influence where the scene clearly provides it\n"
        "- balance ambient-to-direct light ratio on elements to match surroundings\n"
        "CRITICAL RULES:\n"
        "All edits must be confined to ambient/fill regions of composited elements.\n"
        "Do NOT change the direct/key lighting on any element.\n"
        "Do NOT alter the background's ambient characteristics.\n"
        "Do NOT change the overall exposure or brightness of the image.\n"
        "Result requirement:\n"
        "The output should have consistent ambient illumination across all elements as if they exist in the same environment. If no ambient mismatch is detected, return the image unchanged."
    ),
}


def _comp_fallback_prompt(key: str) -> str:
    """Build the default structured prompt for a compositing preset (no elements specified)."""
    return _COMP_ACTIONS[key]["fallback"] + "\n" + _COMP_BODIES[key]


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

    # ---- AI Corrections (8) ----
    "ai_corrections": [
        ("fix_face", "Fix Face Distortion",
         "Correct facial distortions in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the person's identity, expression, or apparent age.\n"
         "Do NOT alter the image composition, background, or non-facial elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct facial generation artifacts, including:\n"
         "- asymmetrical or misaligned facial features (eyes, nose, mouth, ears)\n"
         "- warped or melted facial geometry\n"
         "- unnatural facial proportions (too wide, too narrow, misshapen)\n"
         "- duplicated or blended facial features\n"
         "- uncanny valley smoothness or plasticity in facial structure\n"
         "Apply corrections that restore natural human facial anatomy while preserving the intended appearance.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the face and immediate surrounding area.\n"
         "Do NOT alter clothing, body, hands, or background.\n"
         "Do NOT change hairstyle, hair color, or facial hair.\n"
         "Preserve the person's apparent identity, gender, ethnicity, and age.\n"
         "Result requirement:\n"
         "The output should have natural, anatomically correct facial features that look like a real photograph. If no facial distortions are detected, return the image unchanged."),
        ("fix_eyes", "Fix Eyes",
         "Correct eye-related defects in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the person's identity, expression, or eye color.\n"
         "Do NOT alter the image composition, background, or non-eye elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct eye generation artifacts, including:\n"
         "- crossed eyes or misaligned gaze direction\n"
         "- pupils pointing in different directions\n"
         "- uneven eye size or shape between left and right\n"
         "- deformed eyelids, missing eyelashes, or distorted eye sockets\n"
         "- unnatural iris patterns or reflections\n"
         "- extra or merged eyes\n"
         "Apply corrections that restore natural, aligned eye anatomy with consistent gaze direction.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the eye region (eyes, eyelids, eyebrows).\n"
         "Do NOT alter facial structure, nose, mouth, or other features.\n"
         "Preserve the person's eye color, apparent gaze intent, and expression.\n"
         "Both eyes should appear to look in a consistent, natural direction.\n"
         "Result requirement:\n"
         "The output should have natural, symmetrical eyes with aligned gaze that look like a real photograph. If no eye defects are detected, return the image unchanged."),
        ("fix_hands", "Fix Hands & Fingers",
         "Correct hand and finger anatomy errors in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the hand pose, gesture intent, or position in the scene.\n"
         "Do NOT alter the image composition, background, or non-hand elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct hand generation artifacts, including:\n"
         "- wrong finger count (more or fewer than five per hand)\n"
         "- fused, split, or duplicated fingers\n"
         "- fingers bending in anatomically impossible directions\n"
         "- twisted or malformed joints and knuckles\n"
         "- unnatural finger length ratios or hand proportions\n"
         "- missing or extra thumbs\n"
         "Apply corrections that restore natural human hand anatomy with five fingers per hand and correct joint articulation.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the hands, fingers, and wrists.\n"
         "Do NOT alter arms, clothing, or any other body parts.\n"
         "Preserve the intended hand pose and gesture as closely as possible.\n"
         "Each hand must have exactly five fingers with natural proportions.\n"
         "Result requirement:\n"
         "The output should have anatomically correct hands with proper finger count, natural joint angles, and realistic proportions. If no hand defects are detected, return the image unchanged."),
        ("fix_teeth_mouth", "Fix Teeth & Mouth",
         "Correct teeth and mouth defects in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the person's expression, smile intent, or facial identity.\n"
         "Do NOT alter the image composition, background, or non-mouth elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct mouth and dental generation artifacts, including:\n"
         "- too many or too few teeth\n"
         "- misaligned, overlapping, or impossibly arranged teeth\n"
         "- distorted jaw shape or asymmetric mouth\n"
         "- unnatural gum exposure or gum texture\n"
         "- blurred or melted lip boundaries\n"
         "- teeth that appear fused, floating, or duplicated\n"
         "Apply corrections that restore natural dental and mouth anatomy consistent with the person's expression.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the mouth, lips, teeth, and jaw region.\n"
         "Do NOT alter the rest of the face, nose, eyes, or other features.\n"
         "Preserve the intended expression (smile, open mouth, etc.).\n"
         "Teeth should appear natural and properly aligned.\n"
         "Result requirement:\n"
         "The output should have natural-looking teeth and mouth anatomy appropriate to the expression. If no mouth defects are detected, return the image unchanged."),
        ("fix_body_anatomy", "Fix Body Anatomy",
         "Correct body anatomy errors in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the person's pose intent, clothing, or position in the scene.\n"
         "Do NOT alter the image composition, background, or facial features.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct body generation artifacts, including:\n"
         "- limbs bending in anatomically impossible directions\n"
         "- extra or missing limbs\n"
         "- unnatural body proportions (too long, too short, mismatched segments)\n"
         "- twisted torso or impossible body contortions\n"
         "- joints appearing in wrong locations\n"
         "- body parts clipping through each other or through clothing\n"
         "Apply corrections that restore natural human body anatomy while preserving the intended pose.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the body anatomy regions showing defects.\n"
         "Do NOT alter the face, background, or overall scene.\n"
         "Preserve clothing, accessories, and the intended pose as closely as possible.\n"
         "Body proportions should follow natural human anatomy.\n"
         "Result requirement:\n"
         "The output should have anatomically plausible body proportions and joint articulation. If no body anatomy errors are detected, return the image unchanged."),
        ("fix_skin_texture", "Fix Skin Texture",
         "Correct unnatural skin texture in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the person's identity, features, or skin tone.\n"
         "Do NOT alter the image composition, background, or non-skin elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct skin texture generation artifacts, including:\n"
         "- waxy or plastic-looking skin surface\n"
         "- uncanny valley over-smoothing with no visible pores or texture\n"
         "- inconsistent skin texture between adjacent areas\n"
         "- artificial-looking skin sheen or reflectivity\n"
         "- patchy or blotchy texture transitions\n"
         "- skin that appears painted or airbrushed rather than photographic\n"
         "Apply corrections that restore natural photographic skin texture with appropriate pore detail, subtle imperfections, and realistic surface quality.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to visible skin surfaces.\n"
         "Do NOT alter clothing, hair, background, or facial features/structure.\n"
         "Preserve the person's skin tone, freckles, and natural markings.\n"
         "Do NOT add blemishes \u2014 aim for natural but clean skin texture.\n"
         "Result requirement:\n"
         "The output should have realistic photographic skin texture that avoids the plastic or waxy AI look. If no skin texture issues are detected, return the image unchanged."),
        ("fix_hair", "Fix Hair",
         "Correct hair generation artifacts in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the hairstyle, hair color, or hair length.\n"
         "Do NOT alter the image composition, background, or non-hair elements.\n"
         "Do NOT change the overall color grade, lighting, or artistic style.\n"
         "Scope of work:\n"
         "Identify and correct hair generation artifacts, including:\n"
         "- floating or disconnected hair strands\n"
         "- hair clumps that merge into solid masses without strand detail\n"
         "- unnatural growth direction or impossible hair physics\n"
         "- hair texture that abruptly changes between regions\n"
         "- hair clipping through face, ears, or clothing\n"
         "- bald patches or missing hair in areas that should have coverage\n"
         "Apply corrections that restore natural hair texture, strand detail, and consistent growth patterns.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to the hair and immediate hairline region.\n"
         "Do NOT alter the face, ears, clothing, or background.\n"
         "Preserve the intended hairstyle, color, and overall silhouette.\n"
         "Hair should show natural strand variation and consistent texture.\n"
         "Result requirement:\n"
         "The output should have natural-looking hair with consistent texture and realistic strand detail. If no hair artifacts are detected, return the image unchanged."),
        ("fix_background_coherence", "Fix Background Coherence",
         "Correct background coherence errors in this AI-generated image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "Do NOT change the foreground subjects, people, or main elements.\n"
         "Do NOT alter the overall color grade, lighting direction, or artistic style.\n"
         "Do NOT move, resize, or reposition any foreground objects.\n"
         "Scope of work:\n"
         "Identify and correct background generation artifacts, including:\n"
         "- repeating or tiling patterns that break spatial logic\n"
         "- impossible geometry (stairs to nowhere, walls that don't connect, floating structures)\n"
         "- perspective inconsistencies (vanishing points that don't align)\n"
         "- objects that abruptly cut off, merge, or duplicate\n"
         "- text or signage that appears garbled or nonsensical\n"
         "- seamless blending artifacts where background regions were stitched together\n"
         "Apply corrections that restore spatial coherence and logical consistency in the background.\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to background regions showing coherence issues.\n"
         "Do NOT alter foreground subjects, people, or primary objects.\n"
         "Preserve the intended scene type, setting, and atmosphere.\n"
         "Corrections should make the background appear naturally photographed.\n"
         "Result requirement:\n"
         "The output should have a spatially coherent background with consistent perspective and no impossible geometry. If no background coherence issues are detected, return the image unchanged."),
    ],

    # ---- Compositing (8) ----
    "compositing": [
        ("harmonize_lighting", "Harmonize Lighting", _comp_fallback_prompt("harmonize_lighting")),
        ("match_shadows", "Match Shadows", _comp_fallback_prompt("match_shadows")),
        ("blend_edges", "Blend Edges", _comp_fallback_prompt("blend_edges")),
        ("color_harmonize", "Color Harmonize", _comp_fallback_prompt("color_harmonize")),
        ("fix_reflections", "Fix Reflections", _comp_fallback_prompt("fix_reflections")),
        ("integrate_elements", "Integrate Elements", _comp_fallback_prompt("integrate_elements")),
        ("match_ambient", "Match Ambient Light", _comp_fallback_prompt("match_ambient")),
        ("depth_consistency", "Depth Consistency",
         "Perform a targeted depth consistency pass on this composite image.\n"
         "STRICT LOCKS (non-negotiable):\n"
         "The image must remain pixel-identical in layout and composition.\n"
         "Do NOT move, warp, scale, rotate, or reshape any objects.\n"
         "Do NOT change global lighting, shadows, or color balance.\n"
         "Do NOT modify the overall image appearance or grade.\n"
         "Scope of work (local fixes only):\n"
         "Identify composited elements whose depth cues are inconsistent with their position in the scene, including:\n"
         "- element too sharp or too soft for its apparent distance from the camera\n"
         "- missing atmospheric haze or aerial perspective for distant elements\n"
         "- contrast and saturation not reduced appropriately for depth\n"
         "- scale inconsistency suggesting wrong depth placement\n"
         "Apply ONLY minimal, localized corrections:\n"
         "- apply subtle focus softening to elements that should appear farther from the camera\n"
         "- add gentle atmospheric haze or desaturation to distant composited elements\n"
         "- reduce contrast slightly on far elements to match the scene's depth falloff\n"
         "- sharpen near elements that appear too soft for their position\n"
         "CRITICAL RULES:\n"
         "All edits must be confined to composited elements that show depth inconsistency.\n"
         "Do NOT apply depth-of-field blur to the entire image.\n"
         "Do NOT change the background's existing depth characteristics.\n"
         "Do NOT modify the position or scale of any objects.\n"
         "Result requirement:\n"
         "The output should have consistent depth cues across all elements matching their spatial position in the scene. If no depth issues are detected, return the image unchanged."),
    ],

    # ---- Object Edits (12) ----
    "object_edits": [
        ("delete_object", "Delete Object", _obj_fallback_prompt("delete_object")),
        ("replace_object", "Replace Object", _obj_fallback_prompt("replace_object")),
        ("change_object_color", "Change Object Color", _obj_fallback_prompt("change_object_color")),
        ("change_object_material", "Change Object Material", _obj_fallback_prompt("change_object_material")),
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


# ---------------------------------------------------------------------------
# Object-targeting prompt assembly
# ---------------------------------------------------------------------------

def _collect_object_targets(cop_node: hou.Node) -> list[tuple[str, str]]:
    """Read object target MultiparmBlock instances.

    Returns list of (object_name, modifier) pairs, skipping empty slots.
    """
    count_parm = cop_node.parm("obj_target_count")
    if count_parm is None:
        return []
    count = int(count_parm.eval())
    targets = []
    for i in range(1, count + 1):
        name = (_opt_parm_str(cop_node, f"obj_target_name_{i}") or "").strip()
        mod = (_opt_parm_str(cop_node, f"obj_target_mod_{i}") or "").strip()
        if name:
            targets.append((name, mod))
    return targets


def _build_object_prompt(preset_key: str, targets: list[tuple[str, str]]) -> str | None:
    """Assemble a prompt from object targets for the given preset.

    Returns None if preset is not targeted or no valid targets provided.
    """
    if preset_key not in TARGETED_OBJECT_PRESETS or not targets:
        return None

    actions = _OBJ_ACTIONS[preset_key]
    body = _OBJ_BODIES[preset_key]

    if len(targets) == 1:
        obj1, mod1 = targets[0]
        action = actions["single"].replace("{obj1}", obj1)
        if mod1:
            action = action.replace("{mod1}", mod1)
        elif preset_key != "delete_object":
            # replace/color/material need a modifier — fall back to generic
            return None
    else:
        if preset_key == "delete_object":
            obj_list = ", ".join(name for name, _ in targets)
            action = actions["multi"].replace("{obj_list}", obj_list)
        else:
            pairs = []
            for name, mod in targets:
                if mod:
                    pairs.append(f"{name} to {mod}")
                else:
                    pairs.append(name)
            obj_mod_list = "; ".join(pairs)
            action = actions["multi"].replace("{obj_mod_list}", obj_mod_list)

    return action + "\n" + body


def _sync_object_prompt(node: hou.Node, preset_key: str) -> None:
    """Rebuild the prompt from object targets if user hasn't manually edited."""
    auto_parm = node.parm("_auto_prompt")
    prompt_parm = node.parm("prompt")
    if auto_parm is None or prompt_parm is None:
        return

    current_prompt = (prompt_parm.evalAsString() or "").strip()
    auto_prompt = (auto_parm.evalAsString() or "").strip()

    # Only auto-update if the prompt matches our last auto-generated version
    # (or is empty, or matches the fallback preset text)
    fallback = ALL_PRESETS.get(preset_key, "")
    user_has_edited = (
        current_prompt
        and current_prompt != auto_prompt
        and current_prompt != fallback
    )
    if user_has_edited:
        return

    targets = _collect_object_targets(node)
    new_prompt = _build_object_prompt(preset_key, targets)
    if new_prompt is None:
        new_prompt = fallback

    prompt_parm.set(new_prompt)
    auto_parm.set(new_prompt)


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
        first_prompt = presets[0][2]
        node.parm("prompt").set(first_prompt)

        first_token = presets[0][0]
        auto_parm = node.parm("_auto_prompt")

        # Object targeting: init/clear multiparm
        obj_count = node.parm("obj_target_count")
        if obj_count is not None:
            if category == "object_edits" and first_token in TARGETED_OBJECT_PRESETS:
                if int(obj_count.eval()) == 0:
                    obj_count.set(1)
            else:
                obj_count.set(0)

        # Compositing element targeting: init/clear multiparm
        comp_count = node.parm("comp_element_count")
        if comp_count is not None:
            if category == "compositing" and first_token in TARGETED_COMP_PRESETS:
                if int(comp_count.eval()) == 0:
                    comp_count.set(1)
            else:
                comp_count.set(0)

        # Auto-prompt tracking
        if auto_parm is not None:
            if ((category == "object_edits" and first_token in TARGETED_OBJECT_PRESETS)
                    or (category == "compositing" and first_token in TARGETED_COMP_PRESETS)):
                auto_parm.set(first_prompt)
            else:
                auto_parm.set("")


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

    auto_parm = node.parm("_auto_prompt")
    targeting_active = False

    # Object targeting: init/clear multiparm and build prompt with targets
    obj_count = node.parm("obj_target_count")
    if obj_count is not None:
        if preset_key in TARGETED_OBJECT_PRESETS:
            if int(obj_count.eval()) == 0:
                obj_count.set(1)
            targets = _collect_object_targets(node)
            injected = _build_object_prompt(preset_key, targets)
            if injected:
                prompt_text = injected
            targeting_active = True
        else:
            obj_count.set(0)

    # Compositing element targeting: init/clear multiparm and build prompt with elements
    comp_count = node.parm("comp_element_count")
    if comp_count is not None:
        if preset_key in TARGETED_COMP_PRESETS:
            if int(comp_count.eval()) == 0:
                comp_count.set(1)
            elements = _collect_comp_elements(node)
            injected = _build_comp_prompt(preset_key, elements)
            if injected:
                prompt_text = injected
            targeting_active = True
        else:
            comp_count.set(0)

    # Auto-prompt tracking
    if auto_parm is not None:
        if targeting_active:
            auto_parm.set(prompt_text)
        else:
            auto_parm.set("")

    if prompt_text:
        node.parm("prompt").set(prompt_text)


def on_object_target_changed(kwargs: dict) -> None:
    """Callback when any object target field changes — rebuild prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _opt_parm_menu_str(node, "category") or "custom"
    if category != "object_edits":
        return
    preset_key = _opt_parm_menu_str(node, "preset_object_edits") or ""
    if preset_key not in TARGETED_OBJECT_PRESETS:
        return
    _sync_object_prompt(node, preset_key)


# ---------------------------------------------------------------------------
# Compositing-element-targeting prompt assembly
# ---------------------------------------------------------------------------

def _collect_comp_elements(cop_node: hou.Node) -> list[str]:
    """Read compositing element MultiparmBlock instances.

    Returns list of non-empty element descriptions.
    """
    count_parm = cop_node.parm("comp_element_count")
    if count_parm is None:
        return []
    count = int(count_parm.eval())
    elements = []
    for i in range(1, count + 1):
        desc = (_opt_parm_str(cop_node, f"comp_element_desc_{i}") or "").strip()
        if desc:
            elements.append(desc)
    return elements


def _build_comp_prompt(preset_key: str, elements: list[str]) -> str | None:
    """Assemble a prompt from compositing elements for the given preset.

    Returns None if preset is not targeted or no valid elements provided.
    """
    if preset_key not in TARGETED_COMP_PRESETS or not elements:
        return None

    actions = _COMP_ACTIONS[preset_key]
    body = _COMP_BODIES[preset_key]

    if len(elements) == 1:
        action = actions["single"].replace("{elem1}", elements[0])
    else:
        elem_list = ", ".join(elements)
        action = actions["multi"].replace("{elem_list}", elem_list)

    return action + "\n" + body


def _sync_comp_prompt(node: hou.Node, preset_key: str) -> None:
    """Rebuild the prompt from compositing elements if user hasn't manually edited."""
    auto_parm = node.parm("_auto_prompt")
    prompt_parm = node.parm("prompt")
    if auto_parm is None or prompt_parm is None:
        return

    current_prompt = (prompt_parm.evalAsString() or "").strip()
    auto_prompt = (auto_parm.evalAsString() or "").strip()

    fallback = ALL_PRESETS.get(preset_key, "")
    user_has_edited = (
        current_prompt
        and current_prompt != auto_prompt
        and current_prompt != fallback
    )
    if user_has_edited:
        return

    elements = _collect_comp_elements(node)
    new_prompt = _build_comp_prompt(preset_key, elements)
    if new_prompt is None:
        new_prompt = fallback

    prompt_parm.set(new_prompt)
    auto_parm.set(new_prompt)


def on_comp_element_changed(kwargs: dict) -> None:
    """Callback when any compositing element field changes — rebuild prompt."""
    node = kwargs.get("node")
    if node is None:
        return
    category = _opt_parm_menu_str(node, "category") or "custom"
    if category != "compositing":
        return
    preset_key = _opt_parm_menu_str(node, "preset_compositing") or ""
    if preset_key not in TARGETED_COMP_PRESETS:
        return
    _sync_comp_prompt(node, preset_key)


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
        img_path = _ensure_api_aspect_ratio(img_path)

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

        # Store structured_prompt from API response if present (defensive)
        hdefereval.executeDeferred(
            lambda node=cop_node, d=data: store_vgl_from_response(node, d)
        )

        hdefereval.executeDeferred(
            lambda node=cop_node, path=save_path, total=total_time: apply_result_to_ui(
                node,
                path,
                f"Bria FIBO Edit Complete ({total:.2f}s) \u2192 {path}",
            )
        )

    except (BriaConfigError, BriaRequestError) as e:
        error_msg = f"Bria FIBO Edit Recipes Error: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )
    except Exception as e:
        error_msg = f"Bria FIBO Edit Presets Exception: {_safe_exc_str(e)}"
        _debug_log(error_msg)
        hdefereval.executeDeferred(
            lambda msg=error_msg: hou.ui.setStatusMessage(msg, severity=hou.severityType.Error)
        )


def on_fibo_edit_recipes(kwargs: dict) -> None:
    node = kwargs.get("node")
    if node is None:
        raise ValueError("Missing kwargs['node']")
    fibo_edit_recipes_bria(node)
