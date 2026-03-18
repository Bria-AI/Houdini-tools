# Bria Houdini Tools

AI-powered image generation and editing tools for SideFX Houdini, built on the [Bria API](https://bria.ai). All tools run as native COP (Compositing) nodes, chaining together in standard Houdini networks.

## Requirements

- Houdini 21.0+ (macOS or Windows)
- Bria API key ([get one here](https://platform.bria.ai/console/account/api-keys))
- Python 3.9+ (bundled with Houdini)

## Install

### Option A: HDA Installer (recommended for artists)

1. Download or clone this repo
2. Open Houdini
3. **File > Install Digital Asset Library** > select `bria_installer.hda`
4. Paste your API key and click **Install**
5. Restart Houdini

### Option B: Environment variable (recommended for studios)

```bash
export HOUDINI_PACKAGE_DIR=/path/to/this/repo
```

Launch Houdini. The `bria_houdini.json` package definition handles all paths automatically — no manual configuration needed.

## Nodes

### Bria AI (10 nodes)

| Node | Type | Description |
|------|------|-------------|
| **Generate Image** | Text-to-image | Generate images from text prompts |
| **Generate Structured Prompt** | Utility | Build detailed scene descriptions for consistent generation |
| **FIBO Generate** | Image-to-image | Transform images with prompt guidance |
| **FIBO Edit v2** | Image editing | Prompt-based image editing |
| **FIBO Edit Presets** | Image editing | 82 one-click presets across 10 categories (style, weather, lighting, compositing, cleanup, etc.) |
| **Enhancer** | Enhancement | AI image quality enhancement |
| **Remove BG v2** | Segmentation | Background removal with clean alpha |
| **Erase v2** | Inpainting | Object removal with mask input |
| **GenFill v2** | Inpainting | Generative fill with mask and prompt |
| **Expand v2** | Outpainting | Canvas expansion with AI fill |

### Bria Legacy (7 nodes)

Original implementations retained for backward compatibility.

| Node | Description |
|------|-------------|
| FIBO Edit | Prompt-based editing |
| Remove BG | Background removal |
| Erase | Object erasing |
| GenFill | Generative fill |
| Expand | Canvas expansion |
| Upscale | Image upscaling |
| Viewport Restyle | Viewport capture restyling |

## Architecture

```
bria_houdini/
├── bria_core/          DCC-agnostic API client, auth, config, error handling
└── houdini/
    ├── adapter.py      HTTP client with triple-fallback encoding (JSON → base64 → multipart)
    ├── cop_export.py   COP-to-image export pipeline
    ├── nodes/          Per-node Python logic (callbacks, param extraction, API calls)
    ├── pythonmodules/   HDA PythonModule bindings
    ├── hdas/           Production HDA files (Bria AI)
    ├── hdas_legacy/    Legacy HDA files (Bria Legacy)
    ├── ui/             Dashboard Qt widget
    ├── python_panels/  Houdini panel definition
    └── toolbar/        Shelf tool definition
```

`bria_core` is DCC-agnostic — shared across Houdini, Nuke, and future integrations. All Houdini-specific code lives under `bria_houdini/houdini/`.

## Dashboard

Access via **New Pane Tab > Bria Dashboard**. Provides:
- API key management
- Connection status
- Project folder configuration (where results are saved)

## Building HDAs

HDAs are pre-built and ready to use. To rebuild from source (e.g., after modifying node scripts):

```python
# In Houdini Python Shell:
exec(open("/path/to/repo/scripts/build/build_new_hdas.py").read())
```

See `scripts/build/` for all build utilities:
- `build_new_hdas.py` — Builds all 10 Bria AI HDAs
- `build_installer_hda.py` — Builds the installer HDA
- `categorize_legacy_hdas.py` — Sets TAB menu categories for legacy HDAs
- `package_handoff.sh` — Creates a clean distribution zip

## Documentation

- [Quick Start](documentation/bria_houdini/QUICK_START.md)
- [Configuration](documentation/CONFIG.md)
- [Dashboard](documentation/BRIA_DASHBOARD.md)
- [Troubleshooting](documentation/bria_houdini/TROUBLESHOOTING.md)
- [HDA Details](documentation/bria_houdini/README.md)
- [Repository Structure](STRUCTURE.md)

## License

See [LICENSE](LICENSE).
