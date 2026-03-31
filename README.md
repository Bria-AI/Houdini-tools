
# Bria DCC Integrations

## Quick Start

```
1. Clone or download this repo
2. export HOUDINI_PACKAGE_DIR=/path/to/this/repo
3. Launch Houdini
```

That's it. No editing, no manual path setup. See [documentation/bria_houdini/QUICK_START.md](docs/bria_houdini/quick_start.md) for full details.

## Quick Links

- Setup guide: [documentation/bria_houdini/QUICK_START.md](docs/bria_houdini/quick_start.md)
- Documentation: [documentation/README.md](docs/readme.md)
- Config: [documentation/CONFIG.md](docs/config.md)

## Current Status

- `bria_core` provides API client, config, auth, logging, and errors (DCC-agnostic).
- Houdini adapters and HDAs are in `bria_houdini/houdini/`.
- Package definition (`bria_houdini.json`) at repo root uses relative paths — no user editing required.
