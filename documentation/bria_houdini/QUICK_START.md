# Bria COP HDAs – Quick Start

## 1) Install / auto-load the HDAs

Recommended (simplest): use the Houdini package JSON.

1. Copy `houdini/packages/bria_houdini.json` into your Houdini prefs `packages` folder.
2. Set `BRIA_HOUDINI_ROOT` (under `env`) using one of these two supported modes:
	- **Launcher/env mode (recommended for studios):** export `BRIA_HOUDINI_ROOT` before launching Houdini and keep JSON as-is.
	- **Copied-JSON mode (single-user/manual):** replace `$BRIA_HOUDINI_ROOT` in the copied JSON with an absolute path to your delivery's `houdini` folder.
3. Restart Houdini.

Important:
- If `BRIA_HOUDINI_ROOT` is not set by launcher env and not manually replaced in the copied JSON, package paths resolve to empty and the integration will not load.

Optional/manual alternative (HDAs only): add `houdini/hdas` to `HOUDINI_PATH` in `houdini.env`.
This manual route does not automatically wire shelf/panel paths like the package JSON does.

## 2) Create the nodes

In a COP network, press Tab and search:

- `Bria Erase`
- `Bria GenFill`
- `Bria RMBG`
- `Bria Upscale`
- `Bria Expand`
- `Bria FIBO Edit`
- `Bria FIBO Generate`

## 3) Wire inputs

- Input 1: image
- Input 2: mask (white = edit area, black = keep)

RMBG/Upscale only use Input 1.

Expand/FIBO Edit only use Input 1.

FIBO Generate uses no inputs.

Important: Bria commonly rejects grayscale/indexed/16-bit PNG masks.
If your mask is a single channel COP, convert it to **RGB/RGBA (8-bit)** before it reaches the Bria node.

## 4) Configure API keys (recommended)

Use the **Bria Dashboard** shelf tool to open the panel, then paste your API key(s). The dashboard writes to:

- `~/.bria/bria.json`

Production keys are used by default. Staging/ComfyUI/MCP keys are stored for manual use.

Optional (if present on the node):

- `use_bearer_auth`: use `Authorization: Bearer ...` instead of `api_token: ...`
- `allow_multipart_fallback`: allow multipart retries when a gateway returns `415`
- `http_proxy` / `https_proxy` + `use_env_proxy`: for proxy/firewall environments
	- `use_env_proxy=on`: environment proxy + explicit node proxy merge
	- `use_env_proxy=off`: environment proxies disabled for this request

All nodes:
- `preserve_alpha`

GenFill only:
- `prompt`: what to generate

Upscale only:
- `mode` (`increase_resolution` or `enhance`)
- `desired_increase` (2 or 4, for `increase_resolution`)
- `resolution` (`1MP`, `2MP`, `4MP`, for `enhance`)

FIBO Generate only:
- `pipeline` (`standard`, `lite`, `tailored`)
- `prompt` and/or `structured_prompt`
- `tailored_model_id` (required for `tailored`)

## 5) Click the button

- Erase: click `Erase`
- GenFill: click `Generate`
- RMBG: click `Remove Background`
- Upscale: click `Upscale`
- Expand: click `Expand`
- FIBO Edit: click `Edit`
- FIBO Generate: click `Generate`

Watch Houdini’s status bar + the System Console for logs.

## Notes

- `api_token` is deprecated. Prefer config/env-based auth (`BRIA_API_KEY_HOUDINI` or `~/.bria/bria.json`).
- Runtime export now uses the shared `houdini/cop_export.py` path:
	- for input-based HDAs, first try internal deterministic ROPs (`rop_save_input` / `rop_save_mask`) when present
	- otherwise use deterministic exact-node export (`direct-cop` → `temp-rop-exact-node` → node-local file path)
	- never walk arbitrary upstream branches
- If the result downloads as JPEG/WEBP, the module saves it with the correct extension and updates `loader_result` accordingly.
- The Viewport Restyle tool is a separate OBJ camera-style HDA.
