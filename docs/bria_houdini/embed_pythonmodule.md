# Embedding PythonModules into Bria HDAs

Use this guide when you want to wire the internal COP network manually but keep the Bria logic version-controlled.

Note: `build_new_hdas.py` handles PythonModule embedding automatically for all 12 mainstream HDAs. This guide is for manual HDA building or custom modifications.

## What you paste

- Source: `bria_houdini/pythonmodules/bria_<node_name>.py`
- Destination: your HDA Type Properties -> **Scripts** tab -> **PythonModule**

Each PythonModule wrapper is a thin shim that imports from the corresponding `nodes/<node_name>.py` module. For example, `bria_genfill.py` imports and re-exports functions from `nodes/genfill.py`.

## Expected parms (on the HDA)

Common parms expected by all nodes:

- `api_base_url` (string) -- API endpoint override
- `api_token` (string) -- deprecated, prefer config-based auth
- `result_path` (string) -- stores the output image path for node chaining

Node-specific parms vary. See [README.md](readme.md) for the full parameter reference.

## Expected internal nodes

Keep these names for the internal COP network:

- `loader_result` -- File COP that reads the saved result path
- `switch_result` -- Switch COP (optional, for toggling pass-through vs result display)
- `rop_save_input` -- ROP Image Output (type: `rop_image`) for exporting input images
- `rop_save_mask` -- ROP Image Output for mask export (Erase/GenFill only)

Important: `rop_save_input` must be type `rop_image` (not `rop_comp`) and must be created inside the HDA context.

Runtime export is handled by `houdini/cop_export.py`:
- Internal ROPs are tried first when present
- Falls through to direct COP export, then temp ROP, then file-path passthrough
- On macOS, internal ROP `render()` is skipped to avoid deadlocks

## Button callback

Create a button parm and set its callback script (Python) to the appropriate function:

- Enhancer: `hou.phm().on_enhancer(kwargs)`
- Upscale: `hou.phm().on_upscale(kwargs)`
- Erase: `hou.phm().on_erase(kwargs)`
- GenFill: `hou.phm().on_genfill(kwargs)`
- RMBG: `hou.phm().on_rmbg(kwargs)`
- Expand: `hou.phm().on_expand(kwargs)`
- FIBO Edit: `hou.phm().on_fibo_edit(kwargs)`
- FIBO Edit Recipes: `hou.phm().on_fibo_edit_recipes(kwargs)`
- FIBO Generate: `hou.phm().on_fibo_generate(kwargs)`
- Generate Structured Prompt: `hou.phm().on_generate_structured_prompt(kwargs)`

Viewport Render has multiple callbacks (all via `hou.phm()`):
- `render_viewport_callback(kwargs)` -- capture + FIBO Edit render
- `capture_render_viewport_callback(kwargs)` -- capture only
- `create_camera_callback(kwargs)` -- create render camera
- `apply_texture_callback(kwargs)` -- apply result as material
- `upscale_result_callback(kwargs)` -- inline upscale
- `enhance_result_callback(kwargs)` -- inline enhance
- `generate_vgl_callback(kwargs)` -- generate VGL from prompt

Batch (TOP) uses the PDG Python Processor pattern -- work item generation and processing are embedded in the HDA's PythonModule at build time. No `hou.phm()` callbacks.

## Build automation

For production builds, use `build_new_hdas.py` in the Houdini Python Shell:

```python
exec(open("/path/to/build_new_hdas.py").read())
```

This builds all 12 mainstream HDAs with correct internal structure, parameter layouts, PythonModules, and input labels.
