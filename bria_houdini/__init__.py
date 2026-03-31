"""Bria Houdini integration package."""

try:
    from .bootstrap import init as _bria_init

    _bria_init()
except Exception:
    # Avoid hard failures when imported outside Houdini or during partial setup.
    pass
