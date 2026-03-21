# Bria Houdini Integration - Developer Guide

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Architecture Overview](#2-architecture-overview)
3. [Package Loading Flow](#3-package-loading-flow)
4. [The PythonModule Pattern](#4-the-pythonmodule-pattern)
5. [Data Flow: Button Click to API Result](#5-data-flow-button-click-to-api-result)
6. [HDA Build Process](#6-hda-build-process)
7. [API Adapter Layer](#7-api-adapter-layer)
8. [Node Catalog](#8-node-catalog)
9. [Cross-Platform Notes](#9-cross-platform-notes)
10. [Key Modules Reference](#10-key-modules-reference)

---

## 1. Quick Start

### Installation

```bash
# Clone the repo
git clone <repo-url> /path/to/bria-houdini

# Point Houdini's package system at it
export HOUDINI_PACKAGE_DIR=/path/to/bria-houdini

# Launch Houdini
houdini
```

No user editing of config files required. All paths in `bria_houdini.json` are relative using `$HOUDINI_PACKAGE_PATH`.

### API Key Setup

1. Open the **Bria AI** shelf in Houdini
2. Click **Bria Dashboard**
3. Enter your API key and click **Install**
4. Key is saved to `~/.bria/bria.json`

### Using Nodes

- **Copernicus nodes** (COP): TAB menu in a COP network, search "Bria"
- **Viewport Render** (OBJ): TAB menu in `/obj`, search "Bria"

---

## 2. Architecture Overview

The codebase is organized in three layers:

```
┌──────────────────────────────────────────────────────────┐
│  HDAs (User-Facing)                                      │
│  Compiled .hda files with embedded PythonModule wrappers │
│  Users interact with these via Houdini's parameter UI    │
├──────────────────────────────────────────────────────────┤
│  houdini/ (DCC Bridge)                                   │
│  Houdini-specific: node logic, adapter, COP export,     │
│  VGL parms, result history, dashboard UI                 │
├──────────────────────────────────────────────────────────┤
│  bria_core/ (DCC-Agnostic)                               │
│  Shared: HTTP client, config, auth, utils, errors        │
│  Reusable across Houdini, Nuke, ToonBoom, etc.           │
└──────────────────────────────────────────────────────────┘
```

### Why This Layering?

- **`bria_core/`** has zero DCC dependencies. It handles HTTP requests, config files, auth headers, base64 encoding, and image downloads. It can be used by any DCC integration or even a standalone CLI.
- **`houdini/`** bridges Houdini's world (nodes, parameters, COP networks) to `bria_core/`. It reads HDA parameters, exports COP images to disk, calls the API through `bria_core`, and writes results back to Houdini.
- **HDAs** are the user-facing layer. They define the parameter UI and wire button callbacks to the `houdini/` layer via thin PythonModule wrappers.

---

## 3. Package Loading Flow

When Houdini launches with `HOUDINI_PACKAGE_DIR` pointing at the repo:

```
1. Houdini reads bria_houdini.json
   ├── Sets PYTHONPATH → bria_houdini/     (enables Python imports)
   ├── Sets HOUDINI_OTLSCAN_PATH → hdas/   (discovers HDAs)
   ├── Sets HOUDINI_TOOLBAR_PATH → toolbar/ (loads shelf)
   ├── Sets HOUDINI_PYTHON_PANEL_PATH → python_panels/ (loads Dashboard)
   └── Sets SSL_CERT_FILE → /etc/ssl/cert.pem (macOS HTTPS certs)

2. Python package loads (houdini/__init__.py → bootstrap.py)
   ├── Detects SSL CA bundle (macOS auto-detection)
   ├── Loads config from ~/.bria/bria.json
   ├── Resolves API endpoint and key
   ├── Optional: network ping (BRIA_BOOTSTRAP_PING=1)
   └── Logs status to console and Houdini status bar

3. HDAs are registered from hdas/ and hdas_legacy/
   └── Available in TAB menu under "Bria AI"

4. Shelf tool "Bria Dashboard" is available
   └── Opens API key management panel
```

### Environment Variables in bria_houdini.json

| Variable | Method | Purpose |
|----------|--------|---------|
| `BRIA_HOUDINI_ROOT` | replace | Root path reference for the integration |
| `PYTHONPATH` | prepend | Enables `from bria_core import ...` and `from houdini import ...` |
| `HOUDINI_OTLSCAN_PATH` | prepend | Tells Houdini where to find `.hda` files |
| `HOUDINI_TOOLBAR_PATH` | prepend | Tells Houdini where to find shelf definitions |
| `HOUDINI_PYTHON_PANEL_PATH` | prepend | Tells Houdini where to find `.pypanel` files |
| `SSL_CERT_FILE` | replace | macOS CA certificate bundle path |

---

## 4. The PythonModule Pattern

### The Problem

Houdini HDAs embed a **PythonModule** — a single Python code block baked into the `.hda` binary. When a user clicks a button, Houdini calls `hou.phm().function_name()` which executes code from this embedded module.

If we put all our logic directly in the PythonModule, we'd have to rebuild the HDA every time we change a line of code. That's slow and error-prone.

### The Solution: Thin Wrappers

Each HDA's PythonModule is a **thin wrapper** (~30-50 lines) that imports and re-exports functions from the real logic files on disk:

```
HDA (binary .hda file)
└── Embedded PythonModule (baked at build time)
    └── pythonmodules/bria_erase.py (thin wrapper)
        └── imports from: houdini/nodes/erase.py (real logic, on disk)
```

**Example — `pythonmodules/bria_erase.py`** (embedded in HDA):

```python
"""Thin HDA PythonModule wrapper for Bria Erase."""
from houdini.nodes.erase import erase_bria, on_erase
from houdini.result_history import build_history_menu, on_load_result

__all__ = ["erase_bria", "on_erase", "build_history_menu", "on_load_result"]
```

**The real logic** lives in `houdini/nodes/erase.py` (200+ lines) on disk.

### Benefits

1. **Hot-reload during development**: Edit `nodes/erase.py` on disk, re-run the button — no HDA rebuild needed (Python re-imports from disk via `PYTHONPATH`)
2. **Small PythonModule**: Easy to read and maintain
3. **Shared utilities**: Multiple HDAs can import from `adapter.py`, `vgl_parms.py`, etc.

### How Callbacks Resolve

```
User clicks "Run Bria Erase" button in HDA UI
    ↓
HDA button callback: hou.phm().on_erase(kwargs)
    ↓
hou.phm() → PythonModule (pythonmodules/bria_erase.py)
    ↓
on_erase imported from → houdini/nodes/erase.py
    ↓
Real logic executes
```

---

## 5. Data Flow: Button Click to API Result

Here's the complete path when a user clicks "Run Bria Erase":

```
┌─────────────────────────────────────────────────────┐
│ 1. HDA Button Click                                 │
│    callback="hou.phm().on_erase(kwargs)"            │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 2. PythonModule Wrapper                             │
│    pythonmodules/bria_erase.py                      │
│    → imports on_erase from houdini/nodes/erase.py   │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 3. Node Logic (houdini/nodes/erase.py)              │
│    a) Read HDA parameters (mask_type, seed, etc.)   │
│    b) Export COP input images to disk (via          │
│       cop_export.py or internal rop_save_input)     │
│    c) Call adapter: erase_from_files(...)            │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 4. Adapter (houdini/adapter.py)                     │
│    a) Load config (resolve endpoint + API key)      │
│    b) Encode images to base64                       │
│    c) Build JSON payload                            │
│    d) Create BriaClient, call post_image_edit()     │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 5. HTTP Client (bria_core/client.py)                │
│    a) Build auth headers (Bearer or api_token)      │
│    b) POST to API (fallback: json → datauri →       │
│       multipart if earlier formats rejected)        │
│    c) Poll async status if API returns status_url   │
│    d) Return response dict                          │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 6. Bria API Server                                  │
│    POST /v2/image/edit/erase                        │
│    Returns: { "image_url": "https://..." }          │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│ 7. Back in Node Logic                               │
│    a) Extract image_url from response               │
│    b) Download result image (bria_core/utils.py)    │
│    c) Save to disk                                  │
│    d) Update HDA result_path parameter              │
│    e) Load result into internal File node            │
│    f) Update status message                         │
└─────────────────────────────────────────────────────┘
```

---

## 6. HDA Build Process

HDAs are built programmatically by `build_new_hdas.py` (located at the `Bria_Dev/` root, **not shipped to users**). This script runs inside Houdini's Python shell.

### Build Steps

```python
# 1. Create temporary COP network with internal structure
cop_net = hou.node("/obj").createNode("copnet")
subnet = cop_net.createNode("subnet", "bria_proto")

# 2. Add internal nodes (no wiring yet — connections don't survive step 3)
subnet.createNode("file", "loader_result")
subnet.createNode("switch", "switch_result")

# 3. Convert subnet → HDA (binary asset)
hda_node = subnet.createDigitalAsset(
    name="bria::bria_erase::1.0",
    hda_file_name="path/to/bria_erase_v2.hda",
)

# 4. Wire internal nodes (MUST happen AFTER createDigitalAsset)
hda_node.allowEditingOfContents()
# ... wire inputs → switch → outputs, create rop_save_input, etc.

# 5. Add parameter templates (UI tabs, buttons, fields)
ptg = hda_node.parmTemplateGroup()
ptg.append(hou.FolderParmTemplate("main", "Bria Erase", ...))
hda_node.type().definition().setParmTemplateGroup(ptg)

# 6. Embed PythonModule (read wrapper from disk, bake into HDA)
pymod_content = open("pythonmodules/bria_erase.py").read()
hda_def.addSection("PythonModule", pymod_content)

# 7. Save and register
hda_def.save(hda_file, template_node=hda_node)
hou.hda.installFile(hda_file)
```

### Internal Node Structure (Copernicus HDAs)

Every COP-type HDA has this internal layout:

```
HDA
├── inputs            (COP inputs node — receives upstream images)
├── loader_result     (File node — loads API result from disk)
│   └── Config: aovs=1, aov1=C (required for Copernicus image display)
├── switch_result     (Switch node — toggles pass-through vs result)
│   ├── input 0 ← inputs (pass-through)
│   └── input 1 ← loader_result (API result)
├── outputs           (COP outputs — wired from switch_result)
└── rop_save_input    (ROP Image — exports input image to disk for API)
    └── Type: rop_image (NOT rop_comp)
```

### Critical Build Constraints

These are hard-won lessons — violating them produces broken HDAs:

1. **Wire AFTER `createDigitalAsset()`**: Node connections don't survive the subnet-to-HDA conversion. Always call `allowEditingOfContents()` and re-wire after.

2. **Disconnect auto-wire first**: Copernicus auto-wires `inputs → outputs`. You must `outputs.setInput(0, None)` before reconnecting through the switch.

3. **File node AOV config**: `loader_result` requires `aovs=1` and `aov1=C`. Without this, the loaded image shows as a checkerboard.

4. **ROP type must be `rop_image`**: Not `rop_comp`. And it must be created inside the HDA context (after `createDigitalAsset`), not in the plain subnet.

5. **Menu parms**: Use `_opt_parm_menu_str()` to get the menu value (e.g., "manual"). Using `_opt_parm_str()` returns the index ("0").

---

## 7. API Adapter Layer

### adapter.py (DCC Bridge)

Located at `houdini/adapter.py`. Bridges Houdini node logic to `bria_core`.

**Key responsibilities:**

1. **Endpoint normalization**: The API has evolved through v1/v2. Users may have old URLs in config. The adapter normalizes them:
   ```
   User config: "https://api.bria.ai/v1/eraser"
       → Normalized: "https://engine.prod.bria-api.com/v2/image/edit/erase"
   ```

2. **File-to-API calls**: Each Bria operation has a corresponding function:

   | Function | API Endpoint |
   |----------|-------------|
   | `erase_from_files()` | `/v2/image/edit/erase` |
   | `genfill_from_files()` | `/v2/image/edit/gen_fill` |
   | `fibo_edit_from_files()` | `/v2/image/edit` |
   | `remove_background_from_files()` | `/v2/image/edit/remove_background` |
   | `upscale_from_files()` | `/v2/image/edit/increase_resolution` |
   | `expand_from_files()` | `/v2/image/edit/expand` |
   | `fibo_generate_from_payload()` | `/v2/image/generate` |
   | `generate_structured_prompt()` | `/v2/structured_prompt/generate` |

3. **Config/auth resolution**: Each function loads config, resolves API key with proper precedence (env var > config file > error), and builds the `BriaClient`.

### bria_core/client.py (HTTP Client)

The `BriaClient` class handles HTTP communication with fallback strategies:

```
Attempt 1: JSON with base64-encoded image
    ↓ (if 415/460 error)
Attempt 2: JSON with data-URI encoded image
    ↓ (if still failing)
Attempt 3: Multipart form upload
```

This handles edge cases where certain API versions reject specific content encodings.

For long-running operations, the client polls an async `status_url` returned by the API.

### Config Resolution Precedence

```
API Key:      env var (BRIA_API_KEY_HOUDINI) → config file → error
API Endpoint: env var (BRIA_API_ENDPOINT) → config file → default production URL
Proxies:      explicit argument → env vars (HTTP_PROXY, HTTPS_PROXY)
```

---

## 8. Node Catalog

### Active HDAs (13)

| HDA | Type | Node Logic | API Endpoint | Description |
|-----|------|-----------|-------------|-------------|
| `bria_erase_v2` | COP | `erase.py` | `/v2/image/edit/erase` | Inpainting with manual/automatic mask |
| `bria_expand_v2` | COP | `expand.py` | `/v2/image/edit/expand` | Outpainting (aspect ratio, directional, canvas) |
| `bria_fibo_edit_v2` | COP | `fibo_edit.py` | `/v2/image/edit` | Prompt-based image editing |
| `bria_fibo_edit_recipes` | COP | `fibo_edit_recipes.py` | `/v2/image/edit` | Pre-configured edit presets |
| `bria_fibo_generate` | COP | `fibo_generate.py` | `/v2/image/generate` | Text-to-image generation |
| `bria_genfill_v2` | COP | `genfill.py` | `/v2/image/edit/gen_fill` | Mask + prompt content generation |
| `bria_rmbg_v2` | COP | `rmbg.py` | `/v2/image/edit/remove_background` | Background removal |
| `bria_upscale_v2` | COP | `upscale.py` | `/v2/image/edit/increase_resolution` | Resolution increase (2x/4x) |
| `bria_enhancer` | COP | `enhancer.py` | `/v2/image/edit/enhance` | Image quality enhancement |
| `bria_generate_structured_prompt` | COP | `generate_structured_prompt.py` | `/v2/structured_prompt/generate` | Text/image to VGL structured prompt |
| `bria_viewport_render_v2` | OBJ | `viewport_render.py` | `/v2/image/edit` | 3D viewport to photorealistic render |
| `bria_usd_to_vgl` | COP | `bria_usd_to_vgl.py` | (local) | USD scene to VGL prompt conversion |
| `bria_vgl_to_usd` | COP | `bria_vgl_to_usd.py` | (local) | VGL prompt to USD scene conversion |

### Legacy HDAs (7)

Located in `hdas_legacy/`. These are v1 versions kept for backward compatibility:
`bria_erase`, `bria_expand`, `bria_fibo_edit`, `bria_genfill`, `bria_rmbg`, `bria_upscale`, `bria_viewport_restyle`

### Common Parameters (All Nodes)

| Parameter | Purpose |
|-----------|---------|
| `seed` | Randomness control (0 = random) |
| `api_token` | Per-node API key override (deprecated, use Dashboard) |
| `api_base_url` | Custom API endpoint override |
| `use_bearer_auth` | Toggle Bearer token auth mode |
| `content_moderation_input` | Safety moderation on input |
| `content_moderation_output` | Safety moderation on output |
| `use_env_proxy` / `http_proxy` / `https_proxy` | Proxy configuration |
| `result_path` | Path to last API result (hidden, set by node logic) |

---

## 9. Cross-Platform Notes

### macOS

- **Temp ROP deadlock**: `cop_export.py` skips temporary ROP node creation on macOS because it can deadlock Houdini. Falls back to direct COP export or node file-path source.
- **SSL cert auto-detection**: `bootstrap.py` searches for CA bundles at `/etc/ssl/cert.pem`, `/private/etc/ssl/cert.pem`, and `/opt/homebrew/etc/ca-certificates/cert.pem`.
- **Exception handling**: Uses `repr(exc)` instead of `str(exc)` for Houdini exceptions — `str()` can hang on macOS.
- **pressButton fallback**: Disabled by default (can deadlock Qt). Override with `BRIA_ALLOW_PRESSBUTTON_FALLBACK=1`.

### Windows

- **Full ROP support**: Temp ROP creation works without deadlock risk.
- **Subprocess stderr**: Viewport render/restyle tools use Windows-specific subprocess stderr handling.
- **SSL**: `bootstrap.py` clears macOS-specific `SSL_CERT_FILE` paths if they were injected by the package config.

---

## 10. Key Modules Reference

### bria_core/ (DCC-Agnostic)

| Module | Purpose |
|--------|---------|
| `client.py` | `BriaClient` HTTP wrapper — POST with retry/fallback, async polling |
| `config.py` | `load_config()` from `~/.bria/bria.json`, `resolve_api_key()`, `resolve_api_endpoint()` |
| `auth.py` | `build_headers()` — Bearer vs api_token auth modes |
| `utils.py` | `file_to_base64()`, `download_url()`, `resolve_temp_dir()`, `resolve_proxies()` |
| `errors.py` | `BriaError` → `BriaAuthError`, `BriaConfigError`, `BriaRequestError` |
| `status.py` | `get_status()` — health check (config + optional network ping) |
| `version.py` | `__version__` string |
| `logging.py` | `configure_logging()`, `get_logger()` |
| `dashboard.py` | Dashboard config read/write, token management |
| `dcc.py` | `DccNodeUtils` base class (abstract DCC interface) |
| `cache.py` | Optional response caching |

### houdini/ (DCC Bridge)

| Module | Purpose |
|--------|---------|
| `adapter.py` | Endpoint normalization + file-to-API bridge functions (erase, edit, generate, etc.) |
| `cop_export.py` | Export COP images to disk — internal ROP, direct COP export, temp ROP fallback chain |
| `node_utils.py` | Safe parameter readers (`opt_parm_str`, `opt_parm_int`, etc.), result path resolution |
| `vgl_parms.py` | VGL structured prompt: `assemble_from_parms()`, `populate_parms_from_json()` |
| `vgl_utils.py` | VGL field definitions, conversion helpers |
| `result_history.py` | Result history tracking, menu population for result pulldowns |
| `bootstrap.py` | Package startup: SSL cert detection, config validation, status logging |

### houdini/nodes/ (Node Logic)

Each file defines:
- **Main function** (e.g., `erase_bria(cop_node)`) — orchestrates the full operation
- **Callback** (e.g., `on_erase(kwargs)`) — entry point from HDA button
- Parameter reading, image export, API call, result download, UI update

### houdini/pythonmodules/ (HDA Wrappers)

Each file is ~30-50 lines:
- Imports functions from corresponding `nodes/*.py` file
- Adds `integration_version()` and `integration_status()` helpers
- Exports everything via `__all__`
- Gets baked into the HDA binary at build time by `build_new_hdas.py`
