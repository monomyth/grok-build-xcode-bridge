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

2. In Xcode → Settings → Intelligence, add/edit your Grok Build external agent:
   - Executable: `~/bin/xcode-grok-bridge.py`
   - Interpreter: `python3` (or full path from `which python3`)

3. Kill stale processes:

   ```bash
   pkill -f 'grok.*stdio|xcode-grok-bridge'
   ```

4. File → New → Conversation (or the + in the Intelligence panel) and send a prompt.

5. Watch traffic:

   ```bash
   tail -f ~/.grok/logs/xcode-acp.log
   ```

See `ACP_TEST_PROMPT.md` in the repo for a thorough protocol validation prompt.

Current limitations
-------------------
- The `xcode-tools` MCP server injected by Xcode is **not proxied** yet.
- Streaming is basic (single final `agent_message_chunk`).
- In-memory history only (new bridge process per many "New Conversation"s).
- Delegates to the local CLI (no direct Grok API yet).

Roadmap ideas for contributors / hand-off models
------------------------------------------------
- Forward the xcode-tools MCP (or a subset) to the inner agent (stdio or API).
- Parse grok CLI output for tool calls / thoughts and emit proper
  session/update notifications (agent_thought_chunk, tool_call, etc.).
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
from typing import Any, Dict, List


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
    line = json.dumps(obj, separators=(",", ":")) + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    log_to_file(f"OUT: {line.rstrip()}")


def send_result(req_id: Any, result: Dict[str, Any]) -> None:
    """Send a successful JSON-RPC result for a request id."""
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


sessions: Dict[str, Dict[str, Any]] = {}


def get_text_from_prompt(prompt: List[Dict[str, Any]]) -> str:
    parts = []
    for block in prompt:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def find_grok_binary() -> str:
    """Locate the grok CLI binary in a portable way."""
    # 1. Explicit override
    env = os.environ.get("GROK_BIN")
    if env:
        return env
    # 2. Standard user install location
    user_grok = os.path.expanduser("~/.grok/bin/grok")
    if os.path.isfile(user_grok) and os.access(user_grok, os.X_OK):
        return user_grok
    # 3. In PATH
    which = shutil.which("grok")
    if which:
        return which
    # 4. Fallback - will fail later with a clear message
    return "grok"


GROK_BIN = find_grok_binary()


def call_grok(prompt: str, cwd: str) -> str:
    try:
        log_stderr(f"Delegating to {GROK_BIN} (cwd={cwd})")
        result = subprocess.run(
            [
                GROK_BIN,
                "-p", prompt,
                "--cwd", cwd,
                "--always-approve",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=cwd,
        )
        if result.returncode != 0:
            log_stderr(f"grok exited {result.returncode}: {result.stderr[:200] if result.stderr else ''}")
        output = (result.stdout or result.stderr or "").strip()
        return output or "(no output from grok)"
    except FileNotFoundError:
        msg = f"Grok binary not found at {GROK_BIN}. Set GROK_BIN env var or install to ~/.grok/bin/grok or add to PATH."
        log_stderr(msg)
        return msg
    except Exception as e:
        log_stderr(f"Error calling grok: {e}")
        return f"Error calling Grok CLI: {e}"


def handle_initialize(params: Dict[str, Any], req_id: Any) -> None:
    log_stderr("Handling initialize")
    result = {
        "protocolVersion": 1,
        "agentCapabilities": {
            "loadSession": True,
            "promptCapabilities": {"image": False, "audio": False, "embeddedContext": True},
            "mcpCapabilities": {"http": True, "sse": True},
            "_meta": {"x.ai/fs_notify": True},
        },
        "authMethods": [
            {"id": "cached_token", "name": "cached_token", "description": "Cached token from ~/.grok/auth.json"},
            {"id": "grok.com", "name": "Grok", "description": "Sign in with Grok"},
        ],
        "_meta": {
            "grokShell": True,
            "agentVersion": "xcode-bridge-0.1",
            "agentId": "xcode-grok-bridge",
            "modelState": {
                "currentModelId": "grok-build",
                "availableModels": [
                    {"modelId": "grok-build", "name": "Grok Build", "description": "Best for advanced coding tasks"},
                ],
            },
        },
    }
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def handle_session_new(params: Dict[str, Any], req_id: Any) -> None:
    sid = str(uuid.uuid4())
    cwd = params.get("cwd", ".")
    sessions[sid] = {
        "cwd": cwd,
        "history": [],
        "mcp_servers": params.get("mcpServers", []),
    }
    log_stderr(f"session/new -> created {sid} for cwd={cwd}")
    # THIS IS THE KEY FIX: return a proper result with sessionId
    send({"jsonrpc": "2.0", "id": req_id, "result": {"sessionId": sid}})
    # Send the announcement Xcode seems to like (non-blocking notification).
    # Harmless if Xcode ignores it; kept for protocol compatibility.
    send({
        "jsonrpc": "2.0",
        "method": "_x.ai/announcements/update",
        "params": {
            "gen": 1,
            "announcements": [
                {
                    "id": "1",
                    "title": "Grok Build via ACP bridge",
                    "message": "Connected to local grok CLI through xcode-grok-bridge.",
                }
            ],
        },
    })


def handle_session_prompt(params: Dict[str, Any], req_id: Any) -> None:
    sid = params.get("sessionId")
    if sid not in sessions:
        send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "Unknown session"}})
        return

    session = sessions[sid]
    cwd = session["cwd"]
    prompt_text = get_text_from_prompt(params.get("prompt", [])) or "hello"
    log_stderr(f"session/prompt for {sid}: {prompt_text[:100]}")

    history = "\n".join(session["history"][-4:])
    full = (
        f"You are a helpful coding agent (Grok Build) working inside Xcode for the project at {cwd}.\n"
        f"Recent history:\n{history}\n\nUser: {prompt_text}\n\n"
        f"Answer concisely. If you need to use tools on the project, describe the action."
    )

    answer = call_grok(full, cwd)

    # Stream to Xcode UI
    send({
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": sid,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": answer},
            },
        },
    })

    # Close the prompt request
    send({"jsonrpc": "2.0", "id": req_id, "result": {}})

    session["history"].append(f"User: {prompt_text}")
    session["history"].append(f"Assistant: {answer[:200]}")


def main() -> None:
    log_stderr(f"Xcode Grok ACP Bridge starting (grok={GROK_BIN})")
    log_to_file("=== BRIDGE START ===")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        log_to_file(f"IN : {line}")
        try:
            msg = json.loads(line)
        except Exception:
            continue

        method = msg.get("method")
        params = msg.get("params", {}) or {}
        req_id = msg.get("id")

        if method == "initialize":
            handle_initialize(params, req_id)
        elif method == "session/new":
            handle_session_new(params, req_id)
        elif method == "session/prompt":
            handle_session_prompt(params, req_id)
        elif method == "skills-reload":
            log_stderr("Handling skills-reload (stub)")
            if req_id is not None:
                send_result(req_id, {"reloaded": True, "skills": ["list_dir", "read_file", "grep", "run_terminal_command"]})
            # else: notification, nothing to reply
        elif req_id is not None:
            log_stderr(f"Unsupported method {method} - returning empty result to avoid breaking Xcode")
            send_result(req_id, {})  # return success instead of error to keep Xcode happy


if __name__ == "__main__":
    main()
