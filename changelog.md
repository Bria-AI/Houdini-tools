# Bria Houdini Integration - Changelog

## v0.3.0 (2026-04-14)

### New Features

- **Bria Sequence Output** -- new COP HDA for batch rendering COP chains with Bria AI nodes across a frame range. Discovers upstream Bria nodes via DAG traversal, topologically sorts them, and cooks each per frame.
- **VGL per-frame generation** -- Generate VGL nodes are now supported in Sequence Output. New **Lock VGL** toggle (default off) controls whether VGL regenerates per frame or stays constant.
- **Batch TOP confirmation** -- popup warning before cooking that shows number of API calls, with Continue/Cancel. Warning label also added to node parameters.
- **Default output path** -- results save to `~/Desktop/bria_houdini_tool_output/` when no project folder is set, with `XDG_DESKTOP_DIR` support for Linux. Falls back to temp directory only if Desktop is unavailable.

### Bug Fixes

- **VGL `objects` field** -- auto-inject empty `objects` array into structured prompts missing it, preventing 422 API errors when the VLM uses non-standard field names (e.g. `text_render`).
- **Sequence Output: generate node support** -- FIBO Generate and Generate VGL nodes no longer require an input image connection.
- **Sequence Output: compositing support** -- final frame export uses 3-tier strategy (internal ROP → COP pixels → upstream result_path) to support Houdini composite nodes (over, screen, etc.).
- **Sequence Output: toggle parm respect** -- `use_basic_prompt` / `use_structured_prompt` toggles are now honored, preventing stale structured prompts from overriding basic prompts.

### Documentation

- Updated all references from 12 to 13 HDAs
- Removed experimental tools section from all docs
- Renamed Generate Structured Prompt to Generate VGL throughout
- Added Sequence Output to all node lists, input tables, and action button tables
- Copernicus naming consistency

## v0.1.0 (2026-03-29)

Initial release. 13 production HDAs for Houdini 21.

### Production Nodes

**COP Nodes (Copernicus):**
- Bria Enhancer -- enhance image quality (1MP/2MP/4MP), steps_num, seed
- Bria Upscale v2 -- increase resolution (2x/4x)
- Bria Erase v2 -- remove content under a mask (2-input: image + mask)
- Bria GenFill v2 -- generate new content under a mask with a prompt (2-input)
- Bria RMBG v2 -- remove background from a single image
- Bria Expand v2 -- outpaint via aspect ratio, directional, or canvas size modes
- Bria FIBO Edit v2 -- prompt-based edit with basic or structured prompts (VGL)
- Bria FIBO Edit Recipes -- categorized preset edits (11 categories, 90 presets)
- Bria FIBO Generate -- text-to-image generation (basic or structured prompts)
- Bria Generate VGL -- convert text/image into structured prompt JSON
- Bria Sequence Output -- batch render a COP chain with Bria AI nodes across a frame range

**OBJ Node:**
- Bria Viewport Render v2 -- capture 3D viewport, apply FIBO Edit AI styling with 22 presets across 5 categories, inline upscale (2x/3x), Apply Texture to geometry

**TOP Node (PDG):**
- Bria Batch -- unified batch processing (Generate/Edit/Enhance/Upscale/RMBG modes), Edit mode supports 78 recipe presets across 9 categories, full PDG wedge attribute support

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
