# Embedding the GenFill PythonModule into an HDA

Use this when you want to wire the internal COP network manually but keep the Bria logic version-controlled.

## What you paste

- Source: `houdini/pythonmodules/bria_genfill.py`
- Destination: your HDA Type Properties → **Scripts** tab → **PythonModule**

## Expected parms (on the HDA)

- `api_base_url` (string)
- `api_token` (string)
- `prompt` (string)
- `preserve_alpha` (toggle)
- `result_path` (string, optional)

## Expected internal nodes

Keep these names (recommended):

- Runtime export is handled by `houdini/cop_export.py`.
  - If internal ROPs are present (`rop_save_input` / `rop_save_mask`), they are used first.
  - Otherwise, deterministic exact-node export is used (direct COP → temp ROP → node-local file path).
  - Upstream traversal fallback is disabled.
- `loader_result` (File COP) that reads the saved result path.
- `switch_result` (optional) to display the result.

## Button callback

Create a button parm and set its callback script (Python) to:

- `hou.phm().on_generate(kwargs)`

or

- `hou.phm().generate_bria(kwargs["node"])`
