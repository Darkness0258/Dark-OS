"""DarkOS Cloud client — accounts, license tier, and cloud AI routing.

Scaffold for build-plan.md's Phase 9, against architecture.md's already-agreed
"DarkOS Cloud (services & data)" section: client always initiates, server
never reaches in; account/license state only; cloud AI use is disclosed,
time-boxed, and scoped to what was actually sent to the assistant.

This module is a STUB, not a working backend: no Supabase project exists
yet (Phase 9's first unchecked item). Every function here fails toward
"free tier, no cloud" rather than raising, matching this project's own
"HUD degrades gracefully" boundary in architecture.md and the same
fallback-chain shape ai_brain.py already uses for its providers. Once a
real Supabase project exists, replace the two bodies marked TODO with real
`postgrest`/`urllib` calls against it -- the public function signatures
below are the actual integration point and shouldn't need to change.
"""

import json
import os
import urllib.request

_SUPABASE_URL = os.environ.get("DARKOS_SUPABASE_URL", "")
_SUPABASE_ANON_KEY = os.environ.get("DARKOS_SUPABASE_ANON_KEY", "")
_CLOUD_AI_URL = os.environ.get("DARKOS_CLOUD_AI_URL", "")

_FREE_TIER = "free"


def cloud_configured() -> bool:
    """True once a real Supabase project is wired up. False today."""
    return bool(_SUPABASE_URL and _SUPABASE_ANON_KEY)


def get_license_tier(timeout: float = 5.0) -> str:
    """Which tier this install is entitled to. Returns "free" whenever the
    real check can't run -- unconfigured, offline, or the request fails --
    never blocks or raises. license check on install/boot, build-plan.md
    Phase 9 item 2."""
    if not cloud_configured():
        return _FREE_TIER
    try:
        # TODO(Phase 9): query the real license/tier table once the
        # Supabase project exists (build-plan.md Phase 9 item 1). Expected
        # shape only -- confirm the actual table/column names against the
        # real schema before wiring this for real:
        #   GET {_SUPABASE_URL}/rest/v1/licenses?select=tier&device_id=eq.<id>
        #   headers: apikey / Authorization: Bearer {_SUPABASE_ANON_KEY}
        return _FREE_TIER
    except Exception:
        return _FREE_TIER


def cloud_ai_available(timeout: float = 5.0) -> bool:
    """True only if both the tier allows it and a cloud AI endpoint is
    actually configured. ai_brain.py's chat() should treat this as just
    another provider to try before falling through to OpenRouter/local,
    never as a hard requirement."""
    if not _CLOUD_AI_URL:
        return False
    return get_license_tier(timeout=timeout) != _FREE_TIER


def call_cloud_ai(messages: list, timeout: float = 30.0) -> str | None:
    """Hosted brain for devices too weak for a good local model
    (architecture.md's stated reason this tier exists). Returns None on
    any failure so callers fall through to the next provider, same
    contract as ai_brain.py's own _try_* helpers. Real request shape is a
    TODO until DARKOS_CLOUD_AI_URL points at something real -- this is
    intentionally not a guess at your API contract."""
    if not cloud_ai_available(timeout=timeout):
        return None
    try:
        # TODO(Phase 9): real request once the endpoint exists. Sketch
        # only, not a contract:
        #   POST {_CLOUD_AI_URL}  {"messages": messages}
        #   Authorization: Bearer {_SUPABASE_ANON_KEY}
        req = urllib.request.Request(
            _CLOUD_AI_URL,
            data=json.dumps({"messages": messages}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_SUPABASE_ANON_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data.get("reply") or None
    except Exception:
        return None
