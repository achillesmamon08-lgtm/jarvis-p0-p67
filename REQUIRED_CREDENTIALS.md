# Required Credentials for .env

Status key: ✓ = available, ✗ = unrecoverable (need fresh key), - = not set (optional)

| Credentials Name | Format | Status | Needed For | Source |
|---|---|---|---|---|
| COMPOSIO_API_KEY | ak_... | ✗ UNRECOVERABLE | Direct Composio SDK (ai/integrations.py) | https://composio.dev/dashboard (new key needed) |
| MCP_COMPOSIO_API_KEY | ck_... | ✓ AVAILABLE | MCP endpoint (Hermes config.yaml) | Already in /root/.hermes/.env |
| FISH_API_KEY | sk-fish-... | ✗ UNRECOVERABLE | Voice synthesis (voice.py) | https://fish.audio/dashboard (new key needed) |
| OPENROUTER_API_KEY | sk-or-... | ✓ AVAILABLE | Cloud LLM fallback | In /root/.hermes/auth.json (nous provider) |
| NVIDIA_API_KEY | nvapi-... | - NOT SET | Optional NVIDIA inference | Get from https://build.ngc.nvidia.com (optional) |
| TS_AUTHKEY | tskey-auth-... | ✓ AVAILABLE | Tailscale authentication | Provided in this conversation |

## Unrecoverable Keys (Need Fresh Generation)

1. **COMPOSIO_API_KEY** — Old key `ak_zoWhoekMDO6wlo56x` was marked as compromised.
   New MCP key `ck_5NH7Tl88SLhOFGbkjbgH` works for the MCP endpoint but the
   direct SDK key needs regeneration for full SDK functionality.

2. **FISH_API_KEY** — Old key returned 401 Invalid Token.
   Android TTS fallback works (exit code 0), but native Fish Audio voices are
   unavailable without a new key.

## Template .env

```
# Composio (SDK direct - needs fresh key)
COMPOSIO_API_KEY=

# Composio (MCP endpoint - already configured in Hermes, not needed here)
# MCP_COMPOSIO_API_KEY=ck_5NH7Tl88SLhOFGbkjbgH

# Fish Audio TTS (needs fresh key)
FISH_API_KEY=

# Tailscale (already authenticated)
TS_AUTHKEY=

# OpenRouter (stored in Hermes auth, not needed here)
# OPENROUTER_API_KEY=
```
