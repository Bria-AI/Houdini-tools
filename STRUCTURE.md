# Repository Structure Guide

Updated March 2026

This file is a representative map of key folders/files, not a byte-for-byte exhaustive tree.

## Current Organization

```
repo-root/
├── bria_houdini.json                   ← Package definition (Houdini finds this via HOUDINI_PACKAGE_DIR)
├── bria_houdini/                       ← All runtime content
│   ├── bria_core/                      ← DCC-agnostic shared core
│   │   ├── __init__.py
│   │   ├── version.py
│   │   ├── config.py
│   │   ├── auth.py
│   │   ├── client.py
│   │   ├── dashboard.py
│   │   ├── dcc.py
│   │   ├── errors.py
│   │   ├── logging.py
│   │   ├── status.py
│   │   ├── cache.py
│   │   └── utils.py
│   │
│   └── houdini/                        ← Houdini-specific integration
│       ├── __init__.py
│       ├── bootstrap.py
│       ├── adapter.py
│       ├── cop_export.py
│       ├── node_utils.py
│       ├── temp_paths.py
│       ├── nodes/
│       │   ├── erase.py
│       │   ├── expand.py
│       │   ├── fibo_edit.py
│       │   ├── fibo_generate.py
│       │   ├── genfill.py
│       │   ├── rmbg.py
│       │   ├── upscale.py
│       │   └── viewport_restyle.py
│       ├── pythonmodules/
│       │   ├── bria_erase.py
│       │   ├── bria_expand.py
│       │   ├── bria_fibo_edit.py
│       │   ├── bria_fibo_generate.py
│       │   ├── bria_genfill.py
│       │   ├── bria_rmbg.py
│       │   ├── bria_upscale.py
│       │   └── bria_viewport_restyle.py
│       ├── hdas/
│       │   ├── bria_erase.hda
│       │   ├── bria_expand.hda
│       │   ├── bria_fibo_edit.hda
│       │   ├── bria_fibo_generate.hda
│       │   ├── bria_genfill.hda
│       │   ├── bria_rmbg.hda
│       │   ├── bria_upscale.hda
│       │   └── bria_viewport_restyle.hda
│       ├── python_panels/
│       │   └── bria_dashboard.pypanel
│       ├── toolbar/
│       │   └── bria_tools.shelf
│       ├── ui/
│       │   └── bria_dashboard.py
│       └── examples/
│           └── hip/
│
├── documentation/
│   ├── README.md
│   ├── CONFIG.md
│   ├── BRIA_DASHBOARD.md
│   └── bria_houdini/
│       ├── README.md
│       ├── QUICK_START.md
│       ├── TROUBLESHOOTING.md
│       └── EMBED_PYTHONMODULE.md
│
├── tools/
│   ├── bria_setup.py
│   └── dev/
│       ├── 456.py
│       ├── start_houdini.bat
│       └── start_houdini.sh
│
├── README.md
├── STRUCTURE.md
├── changelog.md
└── DEV_NOTES.md
```

## Where to Start

- Setup: `documentation/bria_houdini/QUICK_START.md`
- HDA documentation: `documentation/bria_houdini/README.md`
- Config reference: `documentation/CONFIG.md`

## Install

```
1. Clone or download this repo
2. export HOUDINI_PACKAGE_DIR=/path/to/this/repo
3. Launch Houdini
```

`bria_houdini.json` at the repo root uses `$HOUDINI_PACKAGE_PATH` to resolve all paths relative to itself. No manual editing required.

## Notes

- The current integration targets `https://engine.prod.bria-api.com` (host root). The code appends `/v2/image/edit/...`.
- `bria_core` is DCC-agnostic and shared across Houdini, Nuke, and future DCC integrations.
