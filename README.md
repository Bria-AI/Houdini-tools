
# Bria DCC Integrations

## Quick Start

```
1. Clone or download this repo
2. export HOUDINI_PACKAGE_DIR=/path/to/this/repo
3. Launch Houdini
```

That's it. No editing, no manual path setup. See [documentation/bria_houdini/QUICK_START.md](documentation/bria_houdini/QUICK_START.md) for full details.

## Quick Links

- Setup guide: [documentation/bria_houdini/QUICK_START.md](documentation/bria_houdini/QUICK_START.md)
- Documentation: [documentation/README.md](documentation/README.md)
- Config: [documentation/CONFIG.md](documentation/CONFIG.md)

## Current Status

- `bria_core` provides API client, config, auth, logging, and errors (DCC-agnostic).
- Houdini adapters and HDAs are in `bria_houdini/houdini/`.
- Package definition (`bria_houdini.json`) at repo root uses relative paths — no user editing required.
