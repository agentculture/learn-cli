"""Single source of truth for the voice bridge's caps and env-var names.

``infra/template.yaml`` declares the same numbers as CloudFormation Parameter
defaults and the same names as Lambda environment keys;
``tests/test_voice_bridge_template.py`` cross-checks both against this module
so the template and the code that reads it cannot silently drift apart —
the exact guard league-of-agents-platform runs between its template and
``league_site.capacity.config``.

Every default below is tuned against the 20 USD/month ceiling (see the
template's Parameters section for the full price math; it is kept in one
place there, not duplicated here):

- ``DEFAULT_MAX_SESSION_SECONDS = 300`` — a 5-minute session is roughly
  0.10 USD of Nova Sonic 2 speech tokens at the ~1-2 cents/minute the spike
  measured, so the ceiling affords ~200 max-length sessions a month.
- ``DEFAULT_MAX_CONCURRENT_VOICE_SESSIONS = 2`` — bounds the worst-case burn
  *rate* (~2.4 USD/hour at continuous max use) so abuse cannot outrun the
  Budgets alarm's daily cost granularity by much.
"""

from __future__ import annotations

DEFAULT_MONTHLY_BUDGET_USD = 20
DEFAULT_MAX_SESSION_SECONDS = 300
DEFAULT_MAX_CONCURRENT_VOICE_SESSIONS = 2

# Confirmed live in the spike (infra/SPIKE.md): Nova Sonic 2's us-east-1 id.
NOVA_SONIC_MODEL_ID = "amazon.nova-2-sonic-v1:0"

# Lambda environment variable names, wired by infra/template.yaml.
VOICE_TOKEN_SECRET_ENV = "VOICE_TOKEN_SECRET"
SESSIONS_TABLE_ENV = "SESSIONS_TABLE_NAME"
MAX_SESSION_SECONDS_ENV = "MAX_SESSION_SECONDS"
MAX_CONCURRENT_SESSIONS_ENV = "MAX_CONCURRENT_VOICE_SESSIONS"
MODEL_ID_ENV = "NOVA_SONIC_MODEL_ID"
SELF_FUNCTION_NAME_ENV = "SELF_FUNCTION_NAME"
CALLBACK_URL_ENV = "WEBSOCKET_CALLBACK_URL"
