# Dev Notes

## Houdini dev launcher

- Use [tools/dev/start_houdini.bat](tools/dev/start_houdini.bat) (Windows) or [tools/dev/start_houdini.sh](tools/dev/start_houdini.sh) (macOS/Linux) for local development.
- It sets `HOUDINI_PACKAGE_DIR` to the repo root so Houdini loads [bria_houdini.json](bria_houdini.json).

## 456.py (dev-only)

- [tools/dev/456.py](tools/dev/456.py) is a Houdini startup hook used for testing.
- It only prepares `sys.path`. Bootstrap is now triggered from package-level import in [bria_houdini/houdini/__init__.py](bria_houdini/houdini/__init__.py).

## Notes

- Dev files are currently kept in-repo for active iteration.
- Optional startup ping: set `BRIA_BOOTSTRAP_PING=1` to do a short (3s) best‑effort check on launch.
