# Repository Structure

```
repo-root/
├── bria_houdini.json                   ← Package definition (Houdini finds this via HOUDINI_PACKAGE_DIR)
├── bria_installer.hda                  ← One-click installer HDA
│
├── bria_houdini/                       ← All runtime code
│   ├── bria_core/                      ← DCC-agnostic shared core
│   │   ├── __init__.py
│   │   ├── version.py
│   │   ├── config.py                   ← Config file + env var loading
│   │   ├── auth.py                     ← API key handling, header construction
│   │   ├── client.py                   ← HTTP client with retry, async polling
│   │   ├── dashboard.py                ← Dashboard state management
│   │   ├── dcc.py                      ← DCC abstraction interface
│   │   ├── errors.py                   ← Exception hierarchy (BriaError, BriaAuthError, etc.)
│   │   ├── logging.py                  ← Centralized logger
│   │   ├── status.py                   ← Status bar messaging
│   │   ├── cache.py                    ← Response caching
│   │   └── utils.py                    ← Temp dirs, image validation, file helpers
│   │
│   └── houdini/                        ← Houdini-specific integration
│       ├── __init__.py
│       ├── bootstrap.py                ← SSL cert fixes, macOS compatibility
│       ├── adapter.py                  ← API endpoint routing, triple-fallback encoding
│       ├── cop_export.py               ← COP image export pipeline
│       ├── node_utils.py               ← Shared node utilities
│       ├── result_history.py           ← Scan and reload previous results
│       ├── vgl_parms.py                ← VGL parameter UI read/write
│       ├── vgl_utils.py                ← VGL structured prompt parsing
│       │
│       ├── nodes/                      ← Per-node Python logic
│       │   ├── enhancer.py
│       │   ├── erase.py
│       │   ├── expand.py
│       │   ├── fibo_edit.py
│       │   ├── fibo_edit_presets.py     ← 82 presets across 10 categories
│       │   ├── fibo_generate.py
│       │   ├── generate_image.py
│       │   ├── generate_structured_prompt.py
│       │   ├── genfill.py
│       │   ├── rmbg.py
│       │   ├── upscale.py
│       │   └── viewport_restyle.py
│       │
│       ├── pythonmodules/              ← HDA PythonModule bindings
│       │   ├── bria_enhancer.py
│       │   ├── bria_erase.py
│       │   ├── bria_expand.py
│       │   ├── bria_fibo_edit.py
│       │   ├── bria_fibo_edit_presets.py
│       │   ├── bria_fibo_generate.py
│       │   ├── bria_generate_image.py
│       │   ├── bria_generate_structured_prompt.py
│       │   ├── bria_genfill.py
│       │   ├── bria_rmbg.py
│       │   ├── bria_upscale.py
│       │   └── bria_viewport_restyle.py
│       │
│       ├── hdas/                       ← Production HDAs (Bria AI — 10 nodes)
│       │   ├── bria_enhancer.hda
│       │   ├── bria_erase_v2.hda
│       │   ├── bria_expand_v2.hda
│       │   ├── bria_fibo_edit_v2.hda
│       │   ├── bria_fibo_edit_presets.hda
│       │   ├── bria_fibo_generate.hda
│       │   ├── bria_generate_structured_prompt.hda
│       │   ├── bria_genfill_v2.hda
│       │   ├── bria_rmbg_v2.hda
│       │   └── bria_upscale_v2.hda
│       │
│       ├── hdas_legacy/                ← Legacy HDAs (Bria Legacy — 7 nodes)
│       │   ├── bria_erase.hda
│       │   ├── bria_expand.hda
│       │   ├── bria_fibo_edit.hda
│       │   ├── bria_genfill.hda
│       │   ├── bria_rmbg.hda
│       │   ├── bria_upscale.hda
│       │   └── bria_viewport_restyle.hda
│       │
│       ├── python_panels/
│       │   └── bria_dashboard.pypanel
│       ├── toolbar/
│       │   └── bria_tools.shelf
│       ├── ui/
│       │   └── bria_dashboard.py
│       └── examples/
│           └── hip/
│
├── scripts/
│   ├── installer_pythonmodule.py       ← Reference copy of installer HDA code
│   ├── reset_bria_houdini.sh           ← Reset environment for testing
│   └── build/
│       ├── build_new_hdas.py           ← Builds all 10 Bria AI HDAs
│       ├── build_installer_hda.py      ← Builds the installer HDA
│       ├── categorize_legacy_hdas.py   ← Sets TAB menu categories for legacy HDAs
│       └── package_handoff.sh          ← Creates distribution zip
│
├── documentation/
│   ├── README.md                       ← Documentation index
│   ├── CONFIG.md                       ← Configuration reference
│   ├── BRIA_DASHBOARD.md              ← Dashboard guide
│   └── bria_houdini/
│       ├── README.md                   ← HDA feature details
│       ├── QUICK_START.md              ← Installation guide
│       ├── TROUBLESHOOTING.md          ← Common issues and fixes
│       └── EMBED_PYTHONMODULE.md       ← PythonModule embedding guide
│
└── tools/
    ├── bria_setup.py                   ← Setup utility
    └── dev/
        ├── start_houdini.bat           ← Windows dev launcher
        └── start_houdini.sh            ← macOS/Linux dev launcher
```

## Key Concepts

- **bria_core** is DCC-agnostic — shared across Houdini, Nuke, and future integrations
- **nodes/** contain the runtime logic; **pythonmodules/** are thin wrappers that HDAs call
- **hdas/** are pre-built binaries; rebuild with `scripts/build/build_new_hdas.py`
- **bria_houdini.json** uses `$HOUDINI_PACKAGE_PATH` for all paths — no manual editing needed
