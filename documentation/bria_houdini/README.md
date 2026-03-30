# Bria Houdini HDA Reference (Houdini 21)

This repo contains 12 mainstream HDAs and 9 experimental HDAs that talk to Bria's Image API.

## Mainstream Tools (TAB menu: "Bria AI")

### COP Nodes (Copernicus Image Network)

- **Bria Enhancer**: enhance image quality to target resolution (1MP/2MP/4MP)
- **Bria Upscale**: increase resolution via 2x or 4x multiplier
- **Bria Erase**: remove content under a mask (AI inpainting)
- **Bria GenFill**: generate new content under a mask using a prompt
- **Bria RMBG**: remove background from a single image input
- **Bria Expand**: outpaint/expand the image canvas (aspect ratio, directional, or canvas size modes)
- **Bria FIBO Edit**: prompt-based edit using basic or structured prompts (VGL)
- **Bria FIBO Edit Recipes**: categorized preset edits (weather, seasons, lighting, camera effects, etc.)
- **Bria FIBO Generate**: text-to-image generation (basic or structured prompts)
- **Bria Generate Structured Prompt**: convert text/image into structured prompt JSON for downstream nodes

### OBJ Node

- **Bria Viewport Render**: capture 3D viewport and apply FIBO Edit styling with preset categories

### TOP Node (PDG)

- **Bria Batch**: unified batch processing supporting Generate, Edit, Enhance, Upscale, and RMBG modes via PDG work items

## Experimental Tools (TAB menu: "Bria Experimental")

Installed separately via the Bria Experimental Installer. Requires main tools installed first.

Scene Builder, Image to 3D, Image to SOPs, Camera Manifest, Depth Lift, Splat Bridge, GSplat Scene, USD to VGL, VGL to USD.

## Input Configuration

| Node | Input 1 | Input 2 |
|------|---------|---------|
| Erase, GenFill | Image | Mask (white = edit area) |
| Enhancer, Upscale, RMBG, Expand, FIBO Edit, FIBO Edit Recipes | Image | -- |
| FIBO Generate, Generate Structured Prompt | Optional reference image | -- |
| Viewport Render | -- (captures 3D viewport) | -- |
| Batch | -- (PDG work items) | -- |

## What's "special" about this integration

- Works as a **2-input COP node** (Erase/GenFill): Input 1 = image, Input 2 = mask
- Works as a **1-input COP node** (Enhancer/Upscale/RMBG/Expand/FIBO Edit/FIBO Edit Recipes)
- Works as a **0-input COP node** (FIBO Generate, Generate Structured Prompt -- optional reference image input)
- All input-based HDAs use internal deterministic ROP exports (`rop_save_input`, `rop_save_mask`) when present
- Runtime export fallback uses `houdini/cop_export.py`: direct COP pixel export, then exact-node temporary ROP, then exact-node file-path source
- Upstream traversal fallback is disabled to prevent wrong-branch source selection
- `loader_result` reloads the downloaded result and `switch_result` switches display to the result
- Uses a shared temp-path resolver across all nodes
- Runs the network/API work on a background thread so Houdini stays responsive

## Node Chaining

Bria nodes chain together via the `result_path` parameter. Each node stores the path to its output image in `result_path`. When a downstream node needs the upstream image, `cop_export.py` checks `result_path` first (Tier 0: direct file passthrough) before attempting COP pixel export.

This enables **full-resolution passthrough even in Houdini Non-Commercial**, since Bria images are loaded from disk files and bypass the COP pixel pipeline's resolution cap (1920x1080).

Example chains:
- Upscale -> FIBO Edit (edit the upscaled image)
- Generate Structured Prompt -> FIBO Generate (structured generation)
- FIBO Generate -> FIBO Edit (generate then refine)
- Any Bria node -> Enhance (enhance any result)

## Bria Dashboard (shelf tool)

The Houdini package includes a **Bria Dashboard** shelf tool for API setup.

The dashboard writes API keys into `~/.bria/bria.json`:
- Production: `houdini_api_key` (used by default)
- Staging/ComfyUI/MCP: stored for manual use

## HDA Files

### Mainstream (hdas/)

```
bria_enhancer.hda
bria_upscale_v2.hda
bria_erase_v2.hda
bria_genfill_v2.hda
bria_rmbg_v2.hda
bria_expand_v2.hda
bria_fibo_edit_v2.hda
bria_fibo_edit_recipes.hda
bria_fibo_generate.hda
bria_generate_structured_prompt.hda
bria_viewport_render_v2.hda
bria_batch.hda
```

### Experimental (hdas_experimental/)

```
bria_scene_builder.hda
bria_image_to_3d.hda
bria_image_to_sops.hda
bria_camera_manifest.hda
bria_depth_lift.hda
bria_splat_bridge.hda
bria_gsplat_scene.hda
bria_usd_to_vgl.hda
bria_vgl_to_usd.hda
```

## PythonModule Wrappers (pythonmodules/)

Each HDA has a corresponding PythonModule wrapper that imports from `nodes/`:

```
bria_enhancer.py          -> nodes/enhancer.py
bria_upscale.py           -> nodes/upscale.py
bria_erase.py             -> nodes/erase.py
bria_genfill.py           -> nodes/genfill.py
bria_rmbg.py              -> nodes/rmbg.py
bria_expand.py            -> nodes/expand.py
bria_fibo_edit.py         -> nodes/fibo_edit.py
bria_fibo_edit_recipes.py -> nodes/fibo_edit_recipes.py
bria_fibo_generate.py     -> nodes/fibo_generate.py
bria_generate_structured_prompt.py -> nodes/generate_structured_prompt.py
bria_viewport_render.py   -> nodes/viewport_render.py
```

## Parameters

### Common Parameters (all COP nodes)

- `result_path` -- Path to the last API result image (hidden, for node chaining)
- `open_in_mplay` -- Toggle to auto-open results in MPlay (bypasses NC watermarks)

### Authentication (Advanced tab)

- `api_token` -- Deprecated. Prefer config/env-based auth (`BRIA_API_KEY_HOUDINI` or `~/.bria/bria.json`).
- `api_base_url` -- API endpoint override
- `use_bearer_auth` -- Use Bearer token auth
- `use_env_proxy` / `http_proxy` / `https_proxy` -- Proxy configuration

### Node-Specific Parameters

**Enhancer**: `resolution` (1MP/2MP/4MP), `preserve_alpha`, `steps_num`, `seed`, `content_moderation_input`, `content_moderation_output`

**Upscale**: `desired_resolution` (2x/4x), `preserve_alpha`, `seed`, `content_moderation_input`, `content_moderation_output`

**Erase**: `preserve_alpha`, `seed`, `content_moderation_input`, `content_moderation_output`

**GenFill**: `prompt`, `negative_prompt`, `preserve_alpha`, `seed`, `refine_prompt`, `fast`, `content_moderation_input`, `content_moderation_output`, `content_moderation_prompt`

**RMBG**: `preserve_alpha`, `keep_original_size`, `force_bg_detection`, `content_moderation_input`, `content_moderation_output`

**Expand**: `expansion_mode` (aspect_ratio/directional/canvas_size), `prompt`, `negative_prompt`, `seed`, `content_moderation_input`, `content_moderation_output`, `content_moderation_prompt`

**FIBO Edit**: `prompt` or `structured_prompt` (VGL JSON), `negative_prompt`, `guidance_scale` (1-5), `seed`, `steps_num` (25-50)

**FIBO Edit Recipes**: `category` (11 categories: Custom, Style, Weather, Seasons, Time of Day, Camera, Lighting, Compositing, Clean/Artifacts, AI Corrections, Object Edits), preset menus (4-18 presets each), `prompt`, `guidance_scale`, `seed`, `steps_num`

**FIBO Generate**: `prompt` or `structured_prompt`, `negative_prompt`, `guidance_scale`, `seed`, `steps_num`, `aspect_ratio`, `pipeline`, `quality`, `num_images`

**Generate Structured Prompt**: `prompt`, `seed`, `result_json` (output)

**Viewport Render**: `camera_mode` (create_new/use_existing), `resolution` (9 aspect ratios from 1:1 to 16:9), 5 preset categories (Custom, VFX Simulations, Environments, Lighting & Mood, Stylized) with 22 presets, `prompt`, `guidance_scale`, `seed`, `steps_num`, `upscale_mode` (none/2x/3x), Apply Texture (applies result as basecolor to selected geometry)

**Batch (TOP)**: `mode` (Generate/Edit/Enhancer/Upscale/RMBG), Edit mode supports `prompt_mode` (custom/preset) with 9 batch categories and 78 presets, `content_moderation_input`, `content_moderation_output`, supports upstream wedge attributes (`seed`, `prompt`, `guidance_scale`, `steps_num`)

## Image/Mask Requirements

- Supported formats: PNG, JPG/JPEG, WEBP
- Max file size: 12 MB
- Supported color modes: RGB, RGBA, CMYK
- API aspect ratio bounds: 0.5-1.8 (auto-cropped if outside [0.56, 1.78])
- Masks must be **RGB/RGBA (8-bit)** -- grayscale masks will be rejected with 415

## Internal Node Names

If wiring an HDA manually, keep these internal node names:

- `loader_result` -- File COP that reads the saved result path
- `switch_result` -- Switch COP (input 0 = pass-through, input 1 = result)
- `rop_save_input` -- ROP Image Output for exporting input images
- `rop_save_mask` -- ROP Image Output for exporting mask images (Erase/GenFill only)

## Next

- Setup + usage: [QUICK_START.md](QUICK_START.md)
- Viewport Render guide: [VIEWPORT_RENDER.md](VIEWPORT_RENDER.md)
- Batch processing guide: [BATCH_PROCESSING.md](BATCH_PROCESSING.md)
- Troubleshooting: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Embedding PythonModules: [EMBED_PYTHONMODULE.md](EMBED_PYTHONMODULE.md)
- Configuration: [../CONFIG.md](../CONFIG.md)
