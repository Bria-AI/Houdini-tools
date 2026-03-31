"""Executed by Houdini at startup to initialize Bria integration (dev-only)."""

try:
    import os
    import sys

    package_dir = os.environ.get("HOUDINI_PACKAGE_DIR")
    if not package_dir:
        raise RuntimeError("HOUDINI_PACKAGE_DIR is not set.")

    # package_dir points at the repo root; bria_houdini is a subdirectory.
    bria_pkg = os.path.normpath(os.path.join(package_dir, "bria_houdini"))

    if bria_pkg not in sys.path:
        sys.path.insert(0, bria_pkg)

    # Bootstrap is triggered from bria_houdini package import.
except Exception as exc:
    print(f"[BriaHoudini] Startup failed: {exc}")
