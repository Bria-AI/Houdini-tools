# Bria Viewport Render

Capture the Houdini 3D viewport and apply AI-powered styling using Bria's FIBO Edit API.

## Overview

Bria Viewport Render is an OBJ-level node that:

1. Creates or uses an existing camera
2. Captures the 3D viewport as a screenshot
3. Sends the capture to Bria's FIBO Edit API with a text prompt or preset
4. Optionally upscales the result (2x or 3x)
5. Can apply the result as a texture (basecolor) to selected geometry

## Camera Modes

- **Create New** -- creates a dedicated render camera at the current viewport position
- **Use Existing** -- uses a camera you select from a dropdown; validates it exists before rendering

## Supported Resolutions

The node matches your viewport aspect ratio to the closest supported FIBO Edit resolution:

| Resolution | Aspect Ratio |
|-----------|-------------|
| 1024x1024 | 1:1 Square |
| 1152x768 | 3:2 Landscape |
| 768x1152 | 2:3 Portrait |
| 1024x768 | 4:3 Landscape |
| 768x1024 | 3:4 Portrait |
| 960x768 | 5:4 Landscape |
| 768x960 | 4:5 Portrait |
| 1024x576 | 16:9 Wide |
| 576x1024 | 9:16 Tall |

## Preset Categories

Select a category and preset, or use Custom to write your own prompt.

### Custom
Write any text prompt describing the desired look.

### VFX Simulations (5 presets)
- Destruction & Debris
- Water & Ocean
- Fire & Explosions
- Smoke & Clouds
- Particles & Sparks

### Environments (6 presets)
- Mountain Landscape
- Forest & Vegetation
- Desert & Arid
- Coastal & Beach
- Building Exterior
- Building Interior

### Lighting & Mood (6 presets)
- Golden Hour
- Night Scene
- Studio Lighting
- Overcast & Soft
- Dramatic & High Contrast
- Neon & Urban Night

### Stylized (5 presets)
- Motion Graphics
- Abstract Procedural Art
- Concept Art
- Architectural Visualization
- Product Render

All presets include anti-artifact instructions to prevent repeating patterns and grid-aligned placement.

## Inline Upscale

After rendering, optionally upscale the result:
- **None** -- use FIBO Edit output as-is
- **2x** -- double the resolution via Bria Upscale API
- **3x** -- triple the resolution via Bria Upscale API

## Apply Texture

Click "Apply Texture" to apply the rendered result as the `baseColorMap` on selected geometry objects. The node:
1. Reads the result image path from `result_path`
2. Creates or updates a Principled Shader on the target geometry
3. Sets the base color texture to the result image

## Parameters

| Parameter | Description |
|-----------|------------|
| `camera_mode` | create_new or use_existing |
| `resolution` | Target resolution (9 options) |
| `category` | Preset category |
| `preset` | Preset within selected category |
| `prompt` | Text prompt (Custom mode or editable after preset selection) |
| `guidance_scale` | FIBO Edit guidance (1-5) |
| `seed` | Random seed |
| `steps_num` | Inference steps (25-50) |
| `upscale_mode` | none, 2x, or 3x |

## VGL Support

The node supports Visual Generation Language (VGL) structured prompts:
- **Generate VGL** button converts the current prompt into structured JSON
- **Parse VGL** imports VGL JSON into the structured parameter fields
- **Sync to JSON** exports structured fields back to raw JSON

## Callbacks

All callbacks are accessed via `hou.phm()`:

- `render_viewport_callback(kwargs)` -- full pipeline: capture + FIBO Edit
- `capture_render_viewport_callback(kwargs)` -- capture viewport only
- `create_camera_callback(kwargs)` -- create render camera
- `validate_existing_camera_callback(kwargs)` -- validate selected camera
- `apply_texture_callback(kwargs)` -- apply result to geometry
- `apply_result_callback(kwargs)` -- load result into viewer
- `upscale_result_callback(kwargs)` -- upscale current result
- `enhance_result_callback(kwargs)` -- enhance current result
- `generate_vgl_callback(kwargs)` -- generate VGL from prompt
- `refresh_image_list_callback(kwargs)` -- refresh result image list
- `on_category_changed(kwargs)` -- handle category menu change
- `on_preset_changed(kwargs)` -- handle preset menu change
- `on_parse_vgl(kwargs)` -- parse VGL JSON into fields
- `sync_vgl_to_json(kwargs)` -- sync fields back to JSON
