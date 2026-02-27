# Bria COP HDAs (Houdini 21)

This repo contains seven COP HDAs that talk to Bria’s Image Edit API:

- **Bria Erase**: remove content under a mask (inpainting)
- **Bria GenFill**: generate new content under a mask using a **prompt**
- **Bria RMBG**: remove background from a single image input
- **Bria Upscale**: increase resolution or enhance while upscaling
- **Bria Expand**: outpaint/expand the image canvas
- **Bria FIBO Edit**: prompt-based edit on a single image input
- **Bria FIBO Generate**: text/structured prompt generation (no inputs)

Related tool:

- **Bria Viewport Restyle**: OBJ camera-style HDA for viewport capture/edit/apply workflows

## What’s “special” about this integration

- Works as a **2‑input COP node** (Erase/GenFill)
  - Input 1: image
  - Input 2: mask
- Works as a **1‑input COP node** (RMBG/Upscale)
  - Input 1: image
- Works as a **0‑input COP node** (FIBO Generate)
- All input-based HDAs (Erase/GenFill/RMBG/Upscale/Expand/FIBO Edit) first use internal deterministic ROP exports when present (`rop_save_input` and, where applicable, `rop_save_mask`).
- Runtime export fallback uses `houdini/cop_export.py`: direct COP pixel export, then exact-node temporary ROP, then exact-node file-path source.
- Upstream traversal fallback is disabled to prevent wrong-branch source selection.
- Avoids runtime dependency on internal ROP `execute` button export or `opwrite` fallback paths.
- `loader_result` reloads the downloaded result and `switch_result` can switch display to the result.
- Uses a shared temp-path resolver across all Bria COP nodes:
  - Order: `TEMP` → `TMP` → `TMPDIR` (Houdini/env), then Python temp dir, then working dir fallback.
  - On macOS this typically resolves to `$TMPDIR` (`/var/folders/.../T/`).
  - On Windows this typically resolves to `%TEMP%` / `%TMP%` (`AppData/Local/Temp`).
- Runs the network/API work on a background thread so Houdini stays responsive.

## Bria Dashboard (shelf tool)

The Houdini package includes a **Bria Dashboard** shelf tool that opens a Python Panel for API setup.

The dashboard writes API keys into:

- `~/.bria/bria.json`

Fields supported:

- Production → `houdini_api_key`
- Staging → `houdini_api_key_staging`
- ComfyUI → `houdini_api_key_comfyui`
- MCP → `houdini_api_key_mcp`

Production is used by default; other keys are stored for manual use.

## Files that matter

- HDAs:
  - `houdini/hdas/bria_erase.hda`
  - `houdini/hdas/bria_expand.hda`
  - `houdini/hdas/bria_fibo_edit.hda`
  - `houdini/hdas/bria_genfill.hda`
  - `houdini/hdas/bria_fibo_generate.hda`
  - `houdini/hdas/bria_upscale.hda`
  - `houdini/hdas/bria_rmbg.hda`
  - `houdini/hdas/bria_viewport_restyle.hda`
- External PythonModule wrapper files used by those HDAs:
  - `houdini/pythonmodules/bria_erase.py`
  - `houdini/pythonmodules/bria_expand.py`
  - `houdini/pythonmodules/bria_fibo_edit.py`
  - `houdini/pythonmodules/bria_genfill.py`
  - `houdini/pythonmodules/bria_fibo_generate.py`
  - `houdini/pythonmodules/bria_upscale.py`
  - `houdini/pythonmodules/bria_rmbg.py`
- Related Viewport Restyle files:
  - `houdini/nodes/viewport_restyle.py`
  - `houdini/pythonmodules/bria_viewport_restyle.py`

## Parameters (current usage)

For basic use, configure auth via Dashboard (`~/.bria/bria.json`) or env vars and run nodes with their main action buttons.

Common parameters used across Bria COP nodes:

- `preserve_alpha` (toggle)
- `result_path` (optional output override)

Node-specific primary controls:

- GenFill: `prompt`
- Upscale: `mode`, `desired_increase` or `resolution`
- FIBO Edit: `prompt` / `structured_prompt`, optional negative prompt and guidance/seed/steps
- FIBO Generate: `pipeline`, `prompt` / `structured_prompt`, plus generation controls

Advanced auth/endpoint/proxy parms may exist depending on the HDA shell version.
`api_token` is deprecated. Prefer config/env-based auth (`BRIA_API_KEY_HOUDINI` or `~/.bria/bria.json`).

## Version display (HDA UI)

You can display the integration version in the HDA UI using:

```
hou.phm().integration_version()
```

## Status display (HDA UI)

You can query a unified status dict via:

```
hou.phm().integration_status()
```

Fields include: `ok`, `reason`, `message`, `resolved_endpoint`, `using_env_override`.

Optional (if present on the node UI):

- `use_bearer_auth` (toggle)
- `allow_multipart_fallback` (toggle)
- `use_env_proxy` (toggle)
  - `on`: merge environment proxies with explicit proxy parms
  - `off`: ignore environment proxies
- `http_proxy` / `https_proxy` (string)
  - explicit values override environment values when both exist

## Internal node names (recommended)

If you’re wiring an HDA manually, keep these internal node names for output display wiring:

- `loader_result` (File/Loader COP)
- `switch_result` (Switch COP, optional)

## Image/mask requirements (important)

Bria will reject unsupported formats and some PNG encodings.

- Supported file formats: `PNG`, `JPG/JPEG`, `WEBP`
- Max file size: 12 MB
- Supported color modes: `RGB`, `RGBA`, `CMYK`

Common Houdini pitfall: masks exported as **grayscale PNG** → Bria can return `415`.
Make sure your mask COP is converted to **RGB/RGBA (8‑bit)** before export.

Recommended fix inside the HDA: insert a convert/format COP between input 2 and the Bria node input.

## Next

- Setup + usage: [QUICK_START.md](QUICK_START.md)
- Troubleshooting: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Embedding the PythonModule: [EMBED_PYTHONMODULE.md](EMBED_PYTHONMODULE.md)
- Viewport Restyle: uses a separate OBJ camera-style HDA (see QUICK_START.md for usage notes)
