# Bria Houdini Tools -- Quick Start

## 1) Install

### Recommended: Installer HDA

1. Open Houdini and load `bria_installer.hda` from the repo root
2. Tab-search **Bria Installer** at OBJ level
3. Click **Get API Key** to open the Bria console in your browser
4. Paste your API key into the field
5. Click **Install**
6. Restart Houdini

The installer writes a package config to your Houdini preferences and saves the API key to `~/.bria/bria.json`.

### Alternative: Manual package setup

Point Houdini at the repo root:

```
export HOUDINI_PACKAGE_DIR=/path/to/bria-houdini
```

Launch Houdini. `bria_houdini.json` at the repo root sets `path` to add `bria_houdini/` to `HOUDINI_PATH`, which auto-discovers `otls/`, `toolbar/`, and `python_panels/`.

**Studio setup:** Add the repo path to your existing `HOUDINI_PACKAGE_DIR` (colon-separated on macOS/Linux, semicolon on Windows).

### Experimental Tools

After the main install, load `bria_experimental_installer.hda` and click **Install Experimental Tools**. Restart Houdini to see the experimental nodes.

## 2) Create the nodes

### COP nodes (Copernicus Image Network)

In a COP network, press Tab and search:

- `Bria Enhancer` -- enhance to target resolution
- `Bria Upscale` -- 2x or 4x resolution increase
- `Bria Erase` -- inpaint/remove under a mask
- `Bria GenFill` -- generative fill under a mask
- `Bria RMBG` -- remove background
- `Bria Expand` -- outpaint/expand canvas
- `Bria FIBO Edit` -- prompt-based edit (basic or structured)
- `Bria FIBO Edit Recipes` -- categorized preset edits
- `Bria FIBO Generate` -- text-to-image generation
- `Bria Generate Structured Prompt` -- convert text/image to structured prompt JSON

### OBJ node

At OBJ level, Tab-search:

- `Bria Viewport Render` -- capture 3D viewport and apply AI styling

### TOP node (PDG)

In a TOP network, Tab-search:

- `Bria Batch` -- batch processing (Generate/Edit/Enhance/Upscale/RMBG)

## 3) Wire inputs

| Node Type | Input 1 | Input 2 |
|-----------|---------|---------|
| Erase, GenFill | Image | Mask (white = edit area, black = keep) |
| Enhancer, Upscale, RMBG, Expand, FIBO Edit, FIBO Edit Recipes | Image | -- |
| FIBO Generate, Generate Structured Prompt | Optional reference image | -- |

Masks must be **RGB/RGBA (8-bit)**. If your mask is a single-channel COP, convert it before the Bria node.

## 4) Configure API keys

If you used the Installer HDA, your key is already configured.

Otherwise, use the **Bria Dashboard** shelf tool to open the panel and paste your API key. The dashboard writes to `~/.bria/bria.json`.

Environment variable override: `BRIA_API_KEY_HOUDINI`

## 5) Click the action button

| Node | Button |
|------|--------|
| Enhancer | Enhance |
| Upscale | Upscale |
| Erase | Erase |
| GenFill | Generate |
| RMBG | Remove Background |
| Expand | Expand |
| FIBO Edit | Edit |
| FIBO Edit Recipes | Edit |
| FIBO Generate | Generate |
| Generate Structured Prompt | Generate |
| Viewport Render | Render and Style |
| Batch | Cook (PDG) |

Watch Houdini's status bar and System Console for progress.

## 6) Workflow examples

### Structured prompt generation

1. Drop a **Bria Generate Structured Prompt** node (optionally connect a reference image)
2. Enter a text prompt and click **Generate**
3. Connect output to a **Bria FIBO Generate** node
4. Enable "Use Structured Prompt" on the Generate node
5. Click **Generate** to produce the image

### Edit chain

1. Generate or load an image upstream
2. Connect to **Bria FIBO Edit** or **Bria FIBO Edit Recipes**
3. Enter a prompt or pick a preset category/preset
4. Click **Edit** to apply

### Batch processing (PDG)

1. Create a **Bria Batch** TOP node
2. Set the mode (Generate/Edit/Enhance/Upscale/RMBG)
3. Optionally connect a Wedge TOP upstream for seed/prompt variations
4. Cook the network to process all work items in parallel

## Notes

- `api_token` parm is deprecated. Prefer config/env-based auth.
- Runtime export uses `bria_houdini/cop_export.py` with tiered fallback:
  1. Internal ROP (`rop_save_input` / `rop_save_mask`) when present
  2. Direct COP pixel export
  3. Exact-node temporary ROP
  4. Node-local file path (Tier 0 passthrough via `result_path`)
- If the result downloads as JPEG/WEBP, the module saves it with the correct extension.
- Bria images display at full resolution in Houdini Non-Commercial because they load from disk files, bypassing the COP pixel pipeline resolution cap.
