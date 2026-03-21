# Bria Houdini Integration - Repository Map

Quick-reference annotated file tree. See `DEVELOPER_GUIDE.md` for architecture details.

## Top Level

```
bria-houdini/
├── bria_houdini.json              # Houdini package config (entrypoint - sets env vars)
├── bria_installer.hda             # Installer HDA for first-time setup
├── README.md                      # Quick start and overview
├── REPO_MAP.md                    # This file
├── DEVELOPER_GUIDE.md             # Architecture walkthrough
├── STRUCTURE.md                   # Legacy structure notes
├── DEV_NOTES.md                   # Developer workflow notes
├── changelog.md                   # Version history
│
├── bria_houdini/                  # Runtime package (ships to users)
│   ├── bria_core/                 #   DCC-agnostic shared core
│   └── houdini/                   #   Houdini-specific integration
│
├── documentation/                 # Extended documentation
│   ├── README.md
│   ├── CONFIG.md                  #   Config file format and env vars
│   ├── BRIA_DASHBOARD.md          #   Dashboard usage guide
│   └── bria_houdini/
│       ├── README.md              #   HDA descriptions and parameters
│       ├── QUICK_START.md         #   Installation guide
│       ├── TROUBLESHOOTING.md     #   Common issues
│       └── EMBED_PYTHONMODULE.md  #   PythonModule embedding guide
│
├── tools/                         # Setup and dev utilities
│   ├── bria_setup.py              #   Config writer stub
│   └── dev/
│       ├── 456.py                 #   Houdini startup hook (dev testing)
│       ├── start_houdini.sh       #   macOS/Linux launcher
│       └── start_houdini.bat      #   Windows launcher
│
├── tests/                         # Test data and scripts
│   ├── test_bria_usd_to_vgl.py   #   USD conversion tests
│   └── usd_test_data/             #   Sample USD files
│
├── examples/                      # Example Houdini scenes (.hip)
│   └── hip/
│
└── backup/                        # Installer HDA backups (dev-only)
```

## bria_houdini/ (Runtime Package)

Everything in this directory ships to users and is added to `PYTHONPATH`.

### bria_core/ - DCC-Agnostic Shared Core

Shared across Houdini, Nuke, and future DCC integrations.

```
bria_core/
├── __init__.py          # Public API exports
├── version.py           # Integration version string
├── config.py            # Config resolution (~/.bria/bria.json + env vars)
├── auth.py              # API key handling, Bearer/api_token headers
├── client.py            # BriaClient HTTP wrapper (retry, fallback encoding)
├── errors.py            # BriaError, BriaAuthError, BriaConfigError, BriaRequestError
├── logging.py           # Logging configuration
├── status.py            # API health check utilities
├── utils.py             # file_to_base64, download_url, resolve_temp_dir, proxy resolution
├── cache.py             # Response caching (optional)
├── dashboard.py         # Dashboard config read/write (cross-DCC)
├── dcc.py               # DCC abstraction interface (DccNodeUtils base class)
├── bria_usd_to_vgl.py   # USD to VGL structured prompt conversion
└── bria_vgl_to_usd.py   # VGL to USD conversion
```

### houdini/ - Houdini-Specific Integration

```
houdini/
├── __init__.py          # Package init (imports bootstrap on load)
├── bootstrap.py         # Startup: validate config, SSL certs, log status
├── adapter.py           # API bridge: endpoint normalization + file-to-API calls
├── cop_export.py        # COP/ROP image export helpers
├── node_utils.py        # Safe parameter access (opt_parm_*), result paths
├── vgl_parms.py         # VGL structured prompt parameter read/write
├── vgl_utils.py         # VGL field definitions and conversion
├── result_history.py    # Result history tracking and menu population
│
├── nodes/               # Node logic (real implementation)
│   ├── erase.py                       # Bria Erase (inpainting)
│   ├── expand.py                      # Bria Expand (outpainting)
│   ├── fibo_edit.py                   # FIBO Edit (prompt-based editing)
│   ├── fibo_edit_recipes.py           # FIBO Edit Recipes (preset workflows)
│   ├── fibo_generate.py               # FIBO Generate (text-to-image)
│   ├── genfill.py                     # GenFill (mask + prompt generation)
│   ├── rmbg.py                        # Remove Background
│   ├── upscale.py                     # Upscale / Enhance
│   ├── enhancer.py                    # Enhancer (quality improvement)
│   ├── viewport_render.py             # Viewport Render (3D → photo)
│   ├── viewport_restyle.py            # Viewport Restyle (3D → styled)
│   ├── generate_structured_prompt.py  # Generate Structured Prompt (VLM)
│   ├── generate_image.py              # Direct image generation utility
│   ├── bria_usd_to_vgl.py            # USD to VGL node
│   └── bria_vgl_to_usd.py            # VGL to USD node
│
├── pythonmodules/       # Thin wrappers embedded in HDAs at build time
│   ├── bria_erase.py                       # → nodes/erase.py
│   ├── bria_expand.py                      # → nodes/expand.py
│   ├── bria_fibo_edit.py                   # → nodes/fibo_edit.py
│   ├── bria_fibo_edit_recipes.py           # → nodes/fibo_edit_recipes.py
│   ├── bria_fibo_generate.py               # → nodes/fibo_generate.py
│   ├── bria_genfill.py                     # → nodes/genfill.py
│   ├── bria_rmbg.py                        # → nodes/rmbg.py
│   ├── bria_upscale.py                     # → nodes/upscale.py
│   ├── bria_enhancer.py                    # → nodes/enhancer.py (inferred)
│   ├── bria_viewport_render.py             # → nodes/viewport_render.py
│   ├── bria_viewport_restyle.py            # → nodes/viewport_restyle.py
│   ├── bria_generate_structured_prompt.py  # → nodes/generate_structured_prompt.py
│   ├── bria_generate_image.py              # → nodes/generate_image.py
│   ├── bria_usd_to_vgl.py                 # → nodes/bria_usd_to_vgl.py
│   └── bria_vgl_to_usd.py                 # → nodes/bria_vgl_to_usd.py
│
├── hdas/                # Compiled HDA files (production)
│   ├── bria_erase_v2.hda
│   ├── bria_expand_v2.hda
│   ├── bria_fibo_edit_v2.hda
│   ├── bria_fibo_edit_recipes.hda
│   ├── bria_fibo_generate.hda
│   ├── bria_genfill_v2.hda
│   ├── bria_rmbg_v2.hda
│   ├── bria_upscale_v2.hda
│   ├── bria_enhancer.hda
│   ├── bria_viewport_render_v2.hda
│   ├── bria_generate_structured_prompt.hda
│   ├── bria_usd_to_vgl.hda
│   ├── bria_vgl_to_usd.hda
│   └── backup/              # Incremental build backups (dev-only)
│
├── hdas_legacy/         # Deprecated v1 HDAs (kept for compatibility)
│   ├── bria_erase.hda
│   ├── bria_expand.hda
│   ├── bria_fibo_edit.hda
│   ├── bria_genfill.hda
│   ├── bria_rmbg.hda
│   ├── bria_upscale.hda
│   └── bria_viewport_restyle.hda
│
├── toolbar/             # Shelf tools
│   └── bria_tools.shelf     # "Bria AI" shelf with Dashboard tool
│
├── python_panels/       # Python Panel UI definitions
│   └── bria_dashboard.pypanel   # Dashboard panel config
│
├── ui/                  # UI implementation
│   └── bria_dashboard.py    # Dashboard widget (PySide2/6, API key management)
│
└── examples/            # Example scenes
    └── hip/
```

## Environment Variables (set by bria_houdini.json)

| Variable | Value | Purpose |
|----------|-------|---------|
| `BRIA_HOUDINI_ROOT` | `.../bria_houdini/houdini` | Root path for Houdini integration |
| `PYTHONPATH` | `.../bria_houdini` (prepend) | Enables `from bria_core import ...` and `from houdini import ...` |
| `HOUDINI_OTLSCAN_PATH` | `.../hdas` + `.../hdas_legacy` (prepend) | HDA discovery |
| `HOUDINI_TOOLBAR_PATH` | `.../toolbar` (prepend) | Shelf tool discovery |
| `HOUDINI_PYTHON_PANEL_PATH` | `.../python_panels` (prepend) | Python Panel discovery |
| `SSL_CERT_FILE` | `/etc/ssl/cert.pem` | macOS CA bundle for HTTPS |

## Dev-Only Files (not shipped)

These live at the `Bria_Dev/` root (one level above `bria-houdini/`):

| File | Purpose |
|------|---------|
| `build_new_hdas.py` | Master HDA build script (run inside Houdini Python shell) |
| `build_hda.py` | Generic HDA builder template |
| `build_upscale_hda.py` | Upscale-specific builder |
| `build_viewport_restyle_hda.py` | Viewport Restyle builder |
| `build_installer_hda.py` | Installer HDA builder |
| `test_api.py` | API endpoint testing |
| `set_token.py` | API token configuration utility |
