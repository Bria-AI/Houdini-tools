
# Bria DCC Integrations

## Quick Start

```
1. Clone or download this repo
2. export HOUDINI_PACKAGE_DIR=/path/to/this/repo
3. Launch Houdini
```

That's it. No editing, no manual path setup. See [docs/bria_houdini/quick_start.md](docs/bria_houdini/quick_start.md) for full details.

## Project Structure

The `bria_houdini/` package follows Houdini's standard package layout. Setting
`"path"` in `bria_houdini.json` adds the package to `HOUDINI_PATH`, which
auto-discovers these conventional subdirectories:

| Directory | Auto-discovered as | Contents |
|---|---|---|
| `otls/` | `HOUDINI_OTLSCAN_PATH` | Houdini Digital Assets (`.hda`) |
| `toolbar/` | `HOUDINI_TOOLBAR_PATH` | Shelf tools (`.shelf`) |
| `python_panels/` | `HOUDINI_PYTHON_PANEL_PATH` | UI panels (`.pypanel`) |
| `config/Icons/` | Icon search path | Node icons |
| `help/nodes/` | Help search path | Per-node documentation |

No explicit env vars needed for these -- Houdini finds them automatically.

### Full layout

    bria_houdini/
    ├── otls/              # 12 production HDAs
    ├── toolbar/           # "Bria AI" shelf
    ├── python_panels/     # Bria Dashboard panel
    ├── config/Icons/      # Node icons
    ├── help/nodes/        # Node help cards
    ├── examples/          # Sample .hip scenes
    ├── bria_core/         # DCC-agnostic API client (auth, config, HTTP)
    ├── nodes/             # Per-node Python logic
    ├── pythonmodules/     # Thin wrappers embedded in HDAs
    ├── ui/                # Qt dashboard
    ├── builders/          # HDA build scripts (dev only)
    ├── adapter.py         # Bridges Houdini nodes -> bria_core API
    ├── node_utils.py      # Parameter helpers, result wiring
    └── ...

## Quick Links

- Setup guide: [docs/bria_houdini/quick_start.md](docs/bria_houdini/quick_start.md)
- Documentation: [docs/readme.md](docs/readme.md)
- Config: [docs/config.md](docs/config.md)
