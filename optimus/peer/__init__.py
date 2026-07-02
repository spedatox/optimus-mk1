"""
optimus.peer — the SPEDA peering client.

Connects this Optimus instance to a SPEDA Mark VI backend as the external
"optimus" agent over the agents WebSocket (`/agents/ws/optimus`). SPEDA then
routes two kinds of work here:

- task_dispatch:  another agent delegated a (coding) task; we run one headless
  query-loop pass and answer with a single task_result frame.
- chat_request:   the owner is chatting with Optimus in the SPEDA UI; we run
  the query loop and stream chat_event frames (chunk/tool/tool_result/done/
  error) back, correlated by chat_id.

Run:  python -m optimus.peer
Env:  see optimus/peer/config.py (SPEDA_WS_URL, SPEDA_API_KEY,
      OPTIMUS_WORKSPACE, OPTIMUS_ALLOWED_DIRS, OPTIMUS_DEFAULT_MODEL,
      OPTIMUS_PERMISSION_MODE) plus the provider keys optimus/api.py reads
      (ANTHROPIC_API_KEY et al.).
"""
from optimus.peer.config import PeerConfig
from optimus.peer.client import PeerClient

__all__ = ["PeerConfig", "PeerClient"]
