# grok-build-xcode-bridge

Bridge to use local Grok Build (`grok agent stdio`) as an external agent in Xcode via the Agent Client Protocol (ACP).

## Why

Xcode's external agent support (Intelligence / Composer) speaks a JSON-RPC protocol over stdio (ACP). The native `grok agent stdio` implementation only emits a notification for `session/new` and does not return the required `result` containing `sessionId`. Xcode therefore marks the agent "pending" and never delivers user prompts.

This small Python shim correctly implements the handshake Xcode needs, then delegates the actual work to your real local `grok` CLI (with the right working directory and project context).

## Quick Start

1. Place the bridge somewhere on disk and make it executable:

   ```bash
   mkdir -p ~/bin
   # copy or download xcode-grok-bridge.py
   chmod +x ~/bin/xcode-grok-bridge.py
   ```

2. In Xcode → Settings → Intelligence, add/edit a "Grok Build" external agent:

   - Executable: `~/bin/xcode-grok-bridge.py`
   - Interpreter: `python3` (or the full path from `which python3`)

3. Kill stale processes:

   ```bash
   pkill -f 'grok.*stdio|xcode-grok-bridge'
   ```

4. File → New → Conversation (or the Intelligence panel + button) and send a prompt.

5. Debug traffic:

   ```bash
   tail -f ~/.grok/logs/xcode-acp.log
   ```

See [ACP_TEST_PROMPT.md](ACP_TEST_PROMPT.md) for a prompt that exercises the full protocol (sessionId, cwd, tools, MCP visibility, etc.).

## How it works (minimal ACP)

- `initialize` → returns protocolVersion + capabilities + authMethods + modelState
- `session/new` → **returns a real result** `{ "sessionId": "..." }` (this is the critical fix) + optional announcement notification
- `session/prompt` → extracts text, calls local grok CLI with `--cwd`, emits `session/update` (agent_message_chunk), then `result {}`
- Unknown methods / `skills-reload` → empty success result (avoids -32601 errors that can confuse Xcode)

All raw JSON-RPC lines are logged (IN:/OUT:).

The inner `grok` invocation receives a reconstructed prompt that includes recent history and the project `cwd` captured from `session/new`.

## Configuration

- `GROK_BIN` environment variable: force a specific path to the grok binary.
- Log file: `~/.grok/logs/xcode-acp.log` (created automatically).

## Current Status & Limitations

- Core roundtrip works: handshake, session creation, prompt delivery, delegation to real grok, basic streaming back to Xcode UI.
- The `xcode-tools` MCP server injected by Xcode in `session/new` is **not yet proxied**. The agent inside only has its normal tools + filesystem access via the delegated CLI.
- Streaming is coarse (single final message chunk). Thoughts and incremental tool updates are not forwarded yet.
- Per-conversation process model means in-memory history is limited.

## Roadmap / Good first contributions

- Proxy the xcode-tools MCP (or a useful subset) so the agent can build, run, and inspect the Xcode project context directly.
- Parse tool calls / reasoning from the grok CLI output (or switch to direct API) and emit rich `session/update` events (`agent_thought_chunk`, `tool_call`, etc.).
- Persistent session history under `~/.grok/sessions/`.
- Better packaging (Homebrew, installer, launchd agent, etc.).
- Support for embedded context / images when Xcode sends them.

## Handoff note

The entire `xcode-grok-bridge.py` is deliberately a single commented file so you can paste it into Cursor Composer, Claude Projects, another Grok session, etc. and say:

> "Improve this Xcode Grok ACP bridge. First priority: make the xcode-tools MCP that Xcode injects actually usable by the inner agent."

See the module docstring inside the .py for the detailed handoff brief.

## License

MIT (or whatever you prefer for a tiny bridge script).