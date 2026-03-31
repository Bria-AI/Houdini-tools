# Troubleshooting -- Bria Houdini Tools

## 401 Unauthorized

- Your token is not a valid Bria API key.
- Prefer the Bria Dashboard panel or Installer HDA to write keys into `~/.bria/bria.json`.
- If using env vars, set `BRIA_API_KEY_HOUDINI`.
- The node parameter `api_token` is deprecated.

## macOS TLS error: CERTIFICATE_VERIFY_FAILED

If you see:

- `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`

Houdini's embedded Python may be missing a CA-bundle path.

Current behavior:

- Package env sets `SSL_CERT_FILE=/etc/ssl/cert.pem`.
- Bootstrap also attempts fallback CA discovery on macOS:
  - `/etc/ssl/cert.pem`
  - `/private/etc/ssl/cert.pem`
  - `/opt/homebrew/etc/ca-certificates/cert.pem`

If your machine uses a custom bundle path, set `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` before launching Houdini.

## Bria Dashboard not showing (shelf or panel missing)

Check the package JSON is loaded and these env paths are set:

- `HOUDINI_TOOLBAR_PATH` -> houdini/toolbar
- `HOUDINI_PYTHON_PANEL_PATH` -> houdini/python_panels

After changes, restart Houdini. You can also reload shelves:

- `hou.shelves.reloadShelves()`

## 415 Unsupported Media Type

Usually means Bria rejected the uploaded image/mask encoding, not the HTTP Content-Type.

Checklist:

- Exported files are real PNG bytes
- Files are <= 12MB
- Mask is **RGB/RGBA** (not grayscale / indexed / 16-bit PNG)
  - In COPs, insert a convert/format node to force 3-channel RGB

## API rejects aspect ratio (422 error)

The Bria API requires image aspect ratios between 0.5 and 1.8. Images outside this range are automatically center-cropped to fit within [0.56, 1.78] bounds before upload.

If you see a 422 error about aspect ratio, the auto-crop may have failed (e.g., zero-dimension image). Check that your input image has valid dimensions.

## Houdini Non-Commercial (NC) resolution limits

Bria images display at **full resolution** in Houdini NC because they are loaded from disk files via the internal `loader_result` File node. This bypasses the COP pixel pipeline's 1920x1080 resolution cap.

However, if you merge Bria results with standard Houdini COP nodes (e.g., a Merge COP), the merged result goes through the pixel pipeline and will be capped at NC resolution. To avoid this, keep Bria node chains pure (Bria -> Bria) without intermediate Houdini pixel operations.

## macOS ROP render hangs / deadlocks

On macOS, calling `render()` on internal ROP nodes can deadlock Houdini. The integration automatically skips internal ROP rendering on macOS and falls through to the Tier 0 file passthrough (via `result_path`) or direct COP pixel export.

If you suspect a hang, check the System Console for:

- `[Bria COP Export] internal ROP render skipped on macOS (can deadlock)`

This is expected behavior on macOS.

## Post-restart "no image" on downstream nodes

After restarting Houdini, downstream nodes may report "no image" even though the upstream image is visible in the viewport.

This happens because `result_path` is a runtime parameter that isn't persisted in the .hip file. The internal `loader_result` File node retains the correct filename, so the image shows in the viewport, but downstream nodes can't find it via `result_path`.

Fix: Re-run the upstream node to regenerate the image, or manually set the `result_path` parameter to the image file path.

## "Unsupported Input image file extension '.exr'"

Your COP input is not producing a valid PNG export. Bria runtime does not use upstream traversal fallback.

Fix: Ensure the input branch produces a valid RGB/RGBA image. Insert COP conversion nodes if needed.

## Export path behavior (Copernicus)

Bria runtime export uses a tiered fallback (`houdini/cop_export.py`):

1. Internal ROP export (`rop_save_input` / `rop_save_mask`) when present
2. Direct COP pixel export from connected node
3. Exact-node temporary ROP Image Output export
4. Node-local file-path source (Tier 0: `result_path` passthrough)

Confirm the export path from logs:

- `[Bria COP Export] mode=internal-hda-rop ...`
- `[Bria COP Export] mode=direct-cop ...`
- `[Bria COP Export] mode=temp-rop-exact-node ...`
- `[Bria COP Export] mode=node-source-path-copy ...`

## Proxy behavior (`use_env_proxy`)

- `use_env_proxy=on`: merge environment proxies with node proxy parms
- `use_env_proxy=off`: ignore environment proxies
- `http_proxy` / `https_proxy` parms override environment values when both are set

## Result saved but Houdini shows old image

- Ensure `loader_result` exists inside the HDA and feeds the output
- Ensure `switch_result` flips to the result input (if present)
- Clear caches (`texcache -c`, `glcache -c`) -- the module does this automatically
- Force-cook the `outputs` node if needed

## Temp files saved in unexpected location

Resolution order: `TEMP` -> `TMP` -> `TMPDIR` (Houdini/env), then Python temp dir, then working dir fallback.

- macOS: usually `$TMPDIR` (`/var/folders/.../T/`)
- Windows: usually `%TEMP%` / `%TMP%` (`AppData/Local/Temp`)

## Debugging tips

- Open the System Console: Windows -> Toggle System Console
- Look for lines starting with `[Bria Enhancer]`, `[Bria FIBO Edit]`, `[Bria FIBO Generate]`, `[Bria Upscale]`, `[Bria Erase]`, `[Bria GenFill]`, `[Bria RMBG]`, `[Bria Expand]`, `[Bria FIBO Edit Recipes]`, `[Bria Generate Structured Prompt]`, `[Bria Viewport Render]`, `[Bria Batch]`
- Each node logs: exported temp paths, API time, download time, final saved result path + bytes + content-type
