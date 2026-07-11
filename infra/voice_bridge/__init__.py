"""learn-cli's Nova Sonic 2 voice bridge — the Lambda behind the WebSocket API.

Deployed by ``infra/template.yaml`` (AWS SAM, arm64, python3.12). Lives under
``infra/`` — outside the ``learn`` package — because it is deploy
infrastructure, not part of the CLI/MCP/site product: bandit and coverage
scopes stay pinned to ``learn/``, and SAM builds this directory standalone
from its own ``requirements.txt``.

Spec anchor: honesty condition h7 — approval is enforced at the bridge entry;
no valid voice token, no upstream Bedrock connection. See ``infra/SPIKE.md``
for the live spike this design is built on.
"""
