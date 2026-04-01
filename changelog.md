# Bria Houdini Integration - Changelog

## v0.2.0 (2026-03-31)

Package restructure to follow Houdini standard conventions. All bugs fixed, HDAs rebuilt, tested end-to-end.

### Breaking Changes

- **Import namespace:** `from houdini.*` changed to `from bria_houdini.*` to prevent collisions with Houdini's own namespace.
- **Package layout:** `houdini/hdas/` moved to `otls/`, `houdini/toolbar/` to `toolbar/`, `houdini/python_panels/` to `python_panels/`. The `bria_houdini.json` package descriptor now uses Houdini's `path` key for auto-discovery.

### Changes

- **Renamed** Generate Structured Prompt to **Generate VGL** (HDA, pythonmodule, TAB menu label).
- **Hidden inherited OBJ tabs** on Installer (Transform, Subnet) and Viewport Render (Transform, Render, Misc) — only the Bria-specific tab is visible.
- **Fixed** `.pypanel` import path (`from houdini.ui.bria_dashboard` → `from bria_houdini.ui.bria_dashboard`).
- **Fixed** all bare `from bria_core.*` imports across 21 files → `from bria_houdini.bria_core.*`.
- **Simplified** `tools/dev/456.py` — removed redundant `sys.path` manipulation; bootstrap handled by `__init__.py`.
- **Rebuilt** all 12 production HDAs and installer HDA with correct embedded imports.
- **Robust build scripts** — `_find_repo_root()` with 3-tier fallback (direct exec, env var, auto-detect) for `exec(open(...).read())` compatibility.
- **Updated example scene** — new `bria_ai_tools_example_v01.hipnc` with VGL nodes; removed 5 old dev/test scenes.
- **User-Agent header** — all API calls include `User-Agent: BriaHoudini/<version>`.

---

## v0.1.0 (2026-03-29)

Initial release. 12 production HDAs + 9 experimental HDAs for Houdini 21.

### Production Nodes

**COP Nodes (Copernicus Image Network):**
- Bria Enhancer -- enhance image quality (1MP/2MP/4MP), steps_num, seed
- Bria Upscale v2 -- increase resolution (2x/4x)
- Bria Erase v2 -- remove content under a mask (2-input: image + mask)
- Bria GenFill v2 -- generate new content under a mask with a prompt (2-input)
- Bria RMBG v2 -- remove background from a single image
- Bria Expand v2 -- outpaint via aspect ratio, directional, or canvas size modes
- Bria FIBO Edit v2 -- prompt-based edit with basic or structured prompts (VGL)
- Bria FIBO Edit Recipes -- categorized preset edits (11 categories, 90 presets)
- Bria FIBO Generate -- text-to-image generation (basic or structured prompts)
- Bria Generate VGL -- convert text/image into structured prompt JSON (renamed from Generate Structured Prompt in v0.2.0)

**OBJ Node:**
- Bria Viewport Render v2 -- capture 3D viewport, apply FIBO Edit AI styling with 22 presets across 5 categories, inline upscale (2x/3x), Apply Texture to geometry

**TOP Node (PDG):**
- Bria Batch -- unified batch processing (Generate/Edit/Enhance/Upscale/RMBG modes), Edit mode supports 78 recipe presets across 9 categories, full PDG wedge attribute support

### Experimental Nodes (9)

Scene Builder, Image to 3D, Image to SOPs, Camera Manifest, Depth Lift, Splat Bridge, GSplat Scene, USD to VGL, VGL to USD.

### Features

- **Content Moderation** -- granular input/output toggles on Enhancer, Upscale, Erase, GenFill, RMBG, Expand (+ prompt moderation on GenFill and Expand)
- **Result History** -- browse and reload previous results on 9 COP nodes (Enhancer, Upscale, Erase, GenFill, RMBG, Expand, FIBO Edit, FIBO Edit Recipes, FIBO Generate)
- **Metadata Sidecars** -- JSON metadata saved alongside every API result (timing, request params, full API response)
- **Node Chaining** -- `result_path` parameter enables full-resolution passthrough between Bria nodes, bypassing Houdini NC resolution cap
- **MPlay Preview** -- toggle auto-open results in MPlay (bypasses NC watermarks)
- **Bria Dashboard** -- shelf tool for API key setup (`~/.bria/bria.json`)

### Platform Support

- macOS and Windows verified
- SSL: auto-detection of CA bundles on macOS, native cert store on Windows
- Config: `~/.bria/bria.json` via `Path.expanduser()` (cross-platform)
- Exception safety: `_safe_exc_str()` prevents deadlocks from `str()`/`repr()` on Houdini exceptions (macOS + Windows)
- COP viewer refresh: reliable on macOS (skips `pressButton("reload")` which can hang, uses `hou.ui.triggerUpdate()` instead)
- Path normalization: backslash-to-forward-slash for all Houdini parameters

### API

- All endpoints use Bria API v2
- Multipart encoding with compliant CRLF framing
- Retry with data-URI fallback for GenFill/Erase
- Proxy support (`http_proxy`, `https_proxy`, `use_env_proxy`)
- Bearer token auth option
