"""Executed by Houdini at startup to initialize Bria integration (dev-only)."""

try:
    import os
    import sys

    root_dir = os.environ.get("BRIA_HOUDINI_ROOT")
    if not root_dir:
        package_dir = os.environ.get("HOUDINI_PACKAGE_DIR")
        if package_dir:
            root_dir = os.path.normpath(os.path.join(package_dir, ".."))
            print("[BriaHoudini] BRIA_HOUDINI_ROOT not set; using HOUDINI_PACKAGE_DIR to resolve paths.")
        else:
            raise RuntimeError("BRIA_HOUDINI_ROOT is not set and HOUDINI_PACKAGE_DIR is unavailable.")

    # root_dir is the houdini/ folder. Repo root is one level up.
    repo_root = os.path.normpath(os.path.join(root_dir, ".."))
    houdini_dir = root_dir
    pythonmodules_dir = os.path.normpath(os.path.join(houdini_dir, "pythonmodules"))
    bria_core_dir = os.path.normpath(os.path.join(repo_root, "bria_core"))

    for entry in (repo_root, houdini_dir, pythonmodules_dir, bria_core_dir):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    # Bootstrap is now triggered from houdini package import.
except Exception as exc:
    print(f"[BriaHoudini] Startup failed: {exc}")