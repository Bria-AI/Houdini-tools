# Troubleshooting – Bria COPs

## 401 Unauthorized

- Your token is not a valid Bria customer token key.
- Prefer the Bria Dashboard panel to write keys into `~/.bria/bria.json`.
- If using env vars, set `BRIA_API_KEY_HOUDINI`.
- The node parameter `api_token` is deprecated.

## macOS TLS error: CERTIFICATE_VERIFY_FAILED

If you see errors like:

- `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`

Houdini's embedded Python may be missing a CA-bundle path.

Current integration behavior:

- Package env sets `SSL_CERT_FILE=/etc/ssl/cert.pem`.
- Bootstrap also attempts fallback CA discovery on macOS:
  - `/etc/ssl/cert.pem`
  - `/private/etc/ssl/cert.pem`
  - `/opt/homebrew/etc/ca-certificates/cert.pem`

If your machine uses a custom bundle path, set one of:

- `SSL_CERT_FILE`
- `REQUESTS_CA_BUNDLE`

to a valid certificate bundle before launching Houdini.

## Bria Dashboard not showing (shelf or panel missing)

Check the package JSON is loaded and these env paths are set:

- `HOUDINI_TOOLBAR_PATH` → houdini/toolbar
- `HOUDINI_PYTHON_PANEL_PATH` → houdini/python_panels

After changes, restart Houdini. You can also reload shelves in the Python Shell:

- `hou.shelves.reloadShelves()`

If the shelf still doesn’t appear, check the System Console for XML parse errors in the shelf file.

## “Python panel 'bria_dashboard' not found”

- Verify houdini/python_panels/bria_dashboard.pypanel exists.
- Confirm `HOUDINI_PYTHON_PANEL_PATH` includes the python_panels folder.
- Restart Houdini after changing the package JSON.

## 415 Unsupported Media Type

Most often this is **not** the HTTP `Content-Type`.
It usually means Bria rejected the *uploaded image/mask* encoding.

Checklist:

- Exported files sent to Bria are real PNG bytes.
- Files are <= 12MB.
- Mask is **RGB/RGBA** (not grayscale / indexed / 16-bit PNG).
  - In COPs, insert a convert/format node to force 3-channel RGB.

If you see an error like:

- `Mask PNG is grayscale (color_type=0)`

That’s exactly this issue — convert the mask to RGB/RGBA (8-bit) before it reaches the Bria node input.

## “Unsupported Input image file extension '.exr'”

Your COP input path is not producing a valid direct COP PNG export, and no valid node-local source file was found.

Bria runtime does not use upstream traversal fallback.
For input-based HDAs, it tries internal deterministic ROPs first (`rop_save_input` / `rop_save_mask` when present), then direct COP export, exact-node temporary ROP export, and finally exact-node file-path source.

Fix options:

- Ensure the intended image/mask input branch is connected and cookable.
- Insert/adjust COP conversion so the branch produces a valid RGB/RGBA image before the Bria node.

## Export path behavior (Copernicus)

Bria runtime export now uses a shared Copernicus-friendly path resolver (`houdini/cop_export.py`).

- It exports direct COP pixels from the connected node (preserves procedural processing).
- For input-based HDAs, it first tries internal deterministic ROP exports when present.
- If direct export is unavailable, it tries an exact-node temporary ROP Image Output export.
- If that is also unavailable, it accepts only that same node's file-path source.
- It writes a validated PNG file for downstream upload.
- It does not rely on runtime internal ROP `execute` button export or `opwrite` fallback.

You can confirm the export path from logs:

- `[Bria COP Export] mode=internal-hda-rop ...`
- `[Bria COP Export] mode=direct-cop ...`
- `[Bria COP Export] mode=temp-rop-exact-node ...`
- `[Bria COP Export] mode=node-source-path-copy ...`
- `[Bria COP Export] mode=node-source-path-direct ...`

## Proxy behavior (`use_env_proxy`)

- `use_env_proxy=on`: merge environment proxies with node proxy parms.
- `use_env_proxy=off`: ignore environment proxies.
- `http_proxy` / `https_proxy` parms override environment values when both are set.

## Result saved but Houdini shows old image

- Ensure `loader_result` exists inside the HDA and is the node that feeds the output.
- Ensure `switch_result` flips to the result input (if present).
- Clear caches (`texcache -c`, `glcache -c`) — the module already tries this.

## Temp files saved in unexpected location

Bria nodes now use a shared temp resolver.

- Resolution order: `TEMP` → `TMP` → `TMPDIR` (Houdini/env), then Python temp dir, then working dir fallback.
- On macOS, this usually means files land under `$TMPDIR` (`/var/folders/.../T/`).
- On Windows, this usually means `%TEMP%` / `%TMP%` (`AppData/Local/Temp`).

If you still see files under project paths (for example, `$HIP`), verify that your Houdini/session environment is not overriding these vars.

## Debugging tips

- Open the System Console: Windows → Toggle System Console
- Look for lines starting with `[Bria GenFill]` / `[Bria Erase]`.
- The GenFill module logs:
  - exported temp paths
  - API time and download time
  - final saved result path + bytes + content-type
