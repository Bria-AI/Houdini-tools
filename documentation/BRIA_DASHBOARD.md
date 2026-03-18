# Bria Dashboard (Cross-DCC)

The Bria Dashboard is intended to provide a consistent UX across DCCs (Houdini, Nuke, Toon Boom, Etc) for status checks and API-key setup.

## Quick usage flow

1. Open the dashboard panel in your DCC.
2. Open Bria Login / API Keys page.
3. Copy API key(s) from Bria Console.
4. Save key(s) to local config (where supported by current DCC panel).
5. Run status/config/network check from the panel.

This mirrors the same end-user goal across DCCs: configure once, validate quickly, then run nodes/tools.

## How to open the dashboard

- Houdini:
	- Use the Bria Dashboard shelf tool, or
	- Open the Python Panel menu and select Bria Dashboard.

## Shared config location

All DCC integrations read from the same local config file:

- `~/.bria/bria.json`

Primary per-DCC API-key fields used by runtime resolution:

- Houdini → `houdini_api_key`

## Environment variable equivalents

- Houdini → `BRIA_API_KEY_HOUDINI`

Other shared env/config values:

- Endpoint override: `BRIA_API_ENDPOINT`
- Config path override: `BRIA_CONFIG_PATH`

## Current panel behavior by DCC

- Houdini:
	- Full API-key dashboard panel (login links, save/clear, status/config/network checks)
	- Also supports Houdini-specific optional fields such as staging/comfy/mcp keys
	- These non-production Houdini fields are currently stored only (for manual/future workflows) and are not auto-resolved by runtime key selection

## Save/Clear behavior

- Houdini:
  - Save All writes entered keys to `~/.bria/bria.json`.
  - Clear All removes saved Houdini dashboard keys from `~/.bria/bria.json`.

## Login links

- Login: https://platform.bria.ai/login
- API keys: https://platform.bria.ai/console/account/api-keys

## Notes

- Keys are local-only and are not embedded in scene/project files.
- Dashboard backend logic is centralized in `bria_core/dashboard.py`.
- UI layers remain DCC-specific (`houdini/ui/bria_dashboard.py`).
- For implementation details, see:
	- [houdini/ui/bria_dashboard.py](../houdini/ui/bria_dashboard.py)
