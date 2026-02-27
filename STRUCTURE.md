# Repository Structure Guide

Updated February 24, 2026

This file is a representative map of key folders/files, not a byte-for-byte exhaustive tree.

## 📁 Current Organization

```
repo-root/
├── .gitignore
├── README.md
├── DEV_NOTES.md
├── STRUCTURE.md
├── bria_core/
│   ├── __init__.py
│   ├── version.py
│   ├── config.py
│   ├── auth.py
│   ├── client.py
│   ├── errors.py
│   ├── logging.py
│   ├── status.py
│   ├── cache.py
│   └── utils.py
│
├── houdini/
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── adapter.py
│   ├── temp_paths.py
│   ├── nodes/
│   │   ├── erase.py
│   │   ├── expand.py
│   │   ├── fibo_edit.py
│   │   ├── fibo_generate.py
│   │   ├── genfill.py
│   │   ├── rmbg.py
│   │   ├── upscale.py
│   │   └── viewport_restyle.py
│   ├── pythonmodules/
│   │   ├── bria_erase.py
│   │   ├── bria_expand.py
│   │   ├── bria_fibo_edit.py
│   │   ├── bria_fibo_generate.py
│   │   ├── bria_genfill.py
│   │   ├── bria_rmbg.py
│   │   ├── bria_upscale.py
│   │   └── bria_viewport_restyle.py
│   ├── hdas/
│   │   ├── bria_erase.hda
│   │   ├── bria_expand.hda
│   │   ├── bria_fibo_edit.hda
│   │   ├── bria_fibo_generate.hda
│   │   ├── bria_genfill.hda
│   │   ├── bria_rmbg.hda
│   │   └── bria_upscale.hda
│   ├── packages/
│   │   └── bria_houdini.json
│   ├── python_panels/
│   │   └── bria_dashboard.pypanel
│   ├── toolbar/
│   │   └── bria_tools.shelf
│   └── ui/
│       └── bria_dashboard.py
│
├── nuke/
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── adapter.py
│
├── toonboom/
│   ├── __init__.py
│   ├── bootstrap.py
│   ├── adapter.py
│
├── tools/
│   ├── bria_setup.py
│   └── dev/
│       ├── 456.py
│       ├── start_houdini.bat
│       └── start_houdini.sh
│
├── examples/
│   └── bria_earse_or_genfill_by_mask.py
│
├── tests/
│   └── test_config.py
│
├── documentation/
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── CONFIG.md
│   ├── UPDATE_CHECKLIST.md
│   ├── bria_houdini/                        ← Houdini-specific docs
│   │   └── hdas/
│   │       ├── cops/
│   │       └── objs/
│   ├── bria_nuke/                           ← Nuke-specific docs
│   ├── about/
│   │   └── Bria/
│   │       └── api/
│   └── ...
│
├── TODOs/
└── graphics/

```

## 📍 Where to Start

- Current HDA documentation: `documentation/bria_houdini/README.md`
- Nuke documentation: `documentation/bria_nuke/README.md`
- API notes: `documentation/about/Bria/api/README.md`
- Reference example: `examples/bria_earse_or_genfill_by_mask.py`

## Notes

- The current integration targets `https://engine.prod.bria-api.com` (host root). The code appends `/v2/image/edit/...`.
- Nuke and Toon Boom are intentionally adapter/bootstrap stubs for now; implementation is planned after Houdini integration hardening.
