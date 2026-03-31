# Bria Configuration

## Config file

Default path:

- `~/.bria/bria.json`

Example:

```
{
  "houdini_api_key": "BRIA_HOU_xxxxxxxxx",
  "houdini_api_key_staging": "BRIA_HOU_STG_xxxxxxxxx",
  "houdini_api_key_comfyui": "BRIA_HOU_CFY_xxxxxxxxx",
  "houdini_api_key_mcp": "BRIA_HOU_MCP_xxxxxxxxx",
  "nuke_api_key": "BRIA_NUK_xxxxxxxxx",
  "toonboom_api_key": "BRIA_TB_xxxxxxxxx",
  "api_endpoint": "https://engine.prod.bria-api.com/v2",
  "rmbg_endpoint": "https://engine.prod.bria-api.com/v2/image/edit",
  "default_timeout": 30,
  "cache_enabled": true
}
```

## Bria Dashboard

The Bria Dashboard shelf tool writes keys into `~/.bria/bria.json` using the fields above.

- Production uses `houdini_api_key` by default.
- Staging/ComfyUI/MCP keys are stored for manual use.

## Environment overrides

- `BRIA_API_ENDPOINT`
- `BRIA_RMBG_ENDPOINT`
- `BRIA_API_KEY_HOUDINI`
- `BRIA_API_KEY_NUKE`
- `BRIA_API_KEY_TOONBOOM`
- `BRIA_CONFIG_PATH` (config file path override)
- `BRIA_BOOTSTRAP_PING` (optional: set to `1` to do a short startup ping)

## Precedence rules

1) API key: config file → env var → error
2) Config path: env var → default `~/.bria/bria.json`
3) API endpoint: env var → config file → default `https://engine.prod.bria-api.com/v2`
4) RMBG endpoint: env var → config file → API endpoint
