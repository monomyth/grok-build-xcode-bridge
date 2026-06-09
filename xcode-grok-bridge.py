#!/usr/bin/env python3
"""
Xcode Grok ACP Bridge

Single-file Python ACP (Agent Client Protocol) stdio server that lets you use
your local "grok" CLI (Grok Build) as an external agent inside Xcode's
Intelligence / Composer features (Xcode 26/27+).

Why this exists
---------------
The built-in `grok agent stdio` does not return a proper JSON-RPC "result"
for the "session/new" request (only sends a notification). Xcode treats the
session as not ready ("pending" state, "JSON-RPC request failed to produce
a response").

This bridge:
- Speaks the minimal ACP subset Xcode requires.
- Always returns {"sessionId": "..."} for session/new.
- Forwards prompts to your real local grok CLI (with correct --cwd).
- Emits session/update notifications so Xcode can stream output.

This file is intentionally self-contained (zero Python deps beyond stdlib) so
you can hand the entire script to another model (Cursor Composer, Claude,
Grok, etc.) and say "improve the Xcode ACP bridge, add MCP proxy for xcode-tools,
add proper streaming of thoughts/tool calls, etc."

Quick start
-----------
1. Install the bridge:

   ```bash
   mkdir -p ~/bin
   curl -fsSL https://raw.githubusercontent.com/monomyth/grok-build-xcode-bridge/master/xcode-grok-bridge.py \
     -o ~/bin/xcode-grok-bridge.py
   chmod +x ~/bin/xcode-grok-bridge.py
   ```

   Or simply copy `xcode-grok-bridge.py` from the repo.

2. In Xcode → Settings → Intelligence, add or edit your Grok Build external agent:
   - Executable: `~/bin/xcode-grok-bridge.py`
   - Interpreter: *(optional)* `python3`
     (you can usually leave this blank — Xcode will honor the shebang)

3. File → New → Conversation (or the + in the Intelligence panel) and send a prompt.

4. (Optional) Watch traffic:

   ```bash
   tail -f ~/.grok/logs/xcode-acp.log
   ```

> If a previously registered Grok agent is stuck or you want to clean up old processes,
> you can remove the old agent in Xcode settings or run:
>   pkill -f 'grok.*stdio|xcode-grok-bridge'

See `ACP_TEST_PROMPT.md` in the repo for a thorough protocol validation prompt.

Current limitations
-------------------
- The `xcode-tools` MCP server injected by Xcode is **not proxied** yet.
- In-memory history only (new bridge process per many "New Conversation"s).
- Delegates to the local CLI (no direct Grok API yet).

Rich feedback (Option 2)
------------------------
The bridge now invokes the inner grok with `--output-format streaming-json`.
As the CLI streams events we forward them live to Xcode:

- `thought` events → `agent_thought_chunk` (live step-by-step reasoning / "thinking" while the agent works)
- `text` events are accumulated internally; the complete answer is delivered as one `agent_message_chunk` after the inner call finishes.

Tool cards are synthesized by scanning the thought stream for tool usage narration (list_dir, read_file, etc.) and emitting `tool_call` / `tool_call_update` events. This is heuristic because the single-turn streaming-json path narrates tools inside thoughts rather than emitting dedicated tool events.

Supported Grok slash commands (implemented in the bridge)
---------------------------------------------------------
- `/model <name>` (or `/m <name>`)
  Switches the model used for the current Xcode conversation (this session).
  Examples:
    /model grok-composer-2.5-fast
    /model Composer 2.5
    /m build
  The bridge understands common shorthands and passes `-m` to the inner grok CLI.
  This only affects future prompts in the same conversation; each prompt is otherwise
  a fresh delegation.

Native Grok `/commands` (the full TUI set) are **not** part of the ACP protocol.
The bridge only implements the ones that are useful in this environment.

Roadmap ideas for contributors / hand-off models
------------------------------------------------
- Forward the xcode-tools MCP (or a subset) to the inner agent (stdio or API).
- Make tool card detection more robust or switch to a mode that produces native tool_call events.
- Support image/audio context if Xcode sends it.
- Per-session persistent history in ~/.grok/sessions/...
- Make the bridge itself register as a proper agent with better metadata.
- Direct use of Grok API for lower latency + better control.
- Installer / launchd plist / better Xcode registration UX.

Protocol notes
--------------
Key things Xcode appears to require (discovered via live traffic + black-box
testing):
- initialize → result with protocolVersion, agentCapabilities, authMethods, _meta
- session/new → MUST return result { "sessionId": "<uuid>" } (not just a
  notification). This was the root cause of "pending".
- session/prompt → process, then session/update (agent_message_chunk etc.),
  then result {}
- Unknown methods and skills-reload should still reply with a result (empty
  object is safe) instead of error -32601, otherwise Xcode can get unhappy.

The bridge logs every IN and OUT line (raw JSON-RPC) to the log file for
debugging.

Handoff
-------
This whole file (plus the test prompt and README) is the initial artifact for
the https://github.com/monomyth/grok-build-xcode-bridge repo.

If you are an AI reading this file in isolation: the goal is a robust,
shareable bridge that lets any local "grok build" user drive Xcode's agent
features without waiting for official support.

Start by making the xcode-tools MCP actually reachable from the inner agent.
"""

import sys
import json
import uuid
import subprocess
import os
import shutil
import re
from typing import Any, Dict, List, Optional, Set

LOGFILE_PATH = os.path.expanduser("~/.grok/logs/xcode-acp.log")
os.makedirs(os.path.dirname(LOGFILE_PATH), exist_ok=True)


def log_to_file(msg: str) -> None:
    with open(LOGFILE_PATH, "a") as f:
        f.write(msg + "\n")
        f.flush()


def log_stderr(msg: str) -> None:
    print(f"[xcode-grok-bridge] {msg}", file=sys.stderr, flush=True)
    log_to_file(f"BRIDGE: {msg}")


def send(obj: Dict[str, Any]) -> None:
    line = json.dumps(obj, separators=(