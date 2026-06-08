# grok-build-xcode-bridge

Bridge that lets you use your local **Grok Build** CLI (`grok agent stdio`) as an external agent inside Xcode's Intelligence / Composer (Xcode 26/27+).

It implements the minimal parts of the Agent Client Protocol (ACP) over stdio that Xcode requires.

## Why this exists

The native `grok agent stdio` does not return a proper JSON-RPC `result` for the `session/new` request — only a notification. Xcode therefore shows the agent as "pending" and never delivers prompts.

This bridge fixes the handshake (always returns `{"sessionId": "..."}`), captures the project `cwd` and any MCP servers Xcode injects, then delegates real work to your local `grok` CLI with the correct working directory.

## Requirements

- macOS + Xcode 26 or later with external agents enabled
- Local `grok` CLI installed and authenticated (the one from `~/.grok/bin/grok` or in your `PATH`)
- Python 3 (the bridge is a single stdlib-only script)

## Quick Start

1. Install the bridge:

   ```bash
   mkdir -p ~/bin
   curl -fsSL https://raw.githubusercontent.com/monomyth/grok-build-xcode-bridge/master/xcode-grok-bridge.py \
     -o ~/bin/xcode-grok-bridge.py
   chmod +x ~/bin/xcode-grok-bridge.py
   ```

   Or just copy `xcode-grok-bridge.py` from this repo.

2. In **Xcode → Settings → Intelligence**, add or edit an external agent:
   - **Executable**: `~/bin/xcode-grok-bridge.py`
   - **Interpreter**: *(optional)* `python3`  
     (most users can leave this blank — Xcode will use the shebang)

3. In Xcode: **File → New → Conversation** (or the + button in the Intelligence panel) and send a prompt.

   It should no longer stay stuck in "pending".

4. (Optional) Watch traffic for debugging:

   ```bash
   tail -f ~/.grok/logs/xcode-acp.log
   ```

> **Note on old agents**: If you previously registered a different Grok agent and it's behaving strangely, you can remove the old entry in Xcode settings or run `pkill -f 'grok.*stdio|xcode-grok-bridge'` to terminate leftover processes.

## How it works

- `initialize` → returns protocol version, capabilities, auth methods, and model info
- `session/new` → **returns a real `result` containing `sessionId`** (the key fix) and stores the `cwd` + injected `mcpServers`
- `session/prompt` → extracts the user message, builds a prompt that includes recent history + project location, runs your local `grok` CLI via subprocess with `--cwd`, streams the answer back via `session/update` (`agent_message_chunk`), then replies with `result {}`
- Unknown methods and `skills-reload` → reply with an empty success result (prevents -32601 errors that can confuse Xcode)

All raw JSON-RPC traffic is logged (prefixed `IN :` / `OUT:`).

The inner `grok` process sees a reconstructed prompt and the real project directory. It currently uses its normal tools (the Xcode-injected `xcode-tools` MCP is not yet proxied through the bridge).

## Slash commands (Grok-specific)

Grok's `/commands` (e.g. `/model`) are **not** part of the ACP protocol — they are features of the Grok TUI/client.

The bridge implements a small useful subset so you can use them from Xcode:

- `/model <name>` or `/m <name>`
  - Switches the model for the rest of the current conversation.
  - Supports shorthands: `composer`, `composer 2.5`, `build`, plus the real IDs (`grok-composer-2.5-fast`, `grok-build`).
  - Example in Xcode: type `/model Composer 2.5` or `/m grok-composer-2.5-fast`

Everything else you type (including other `/` commands) is passed through as normal user text.

## Configuration

| Variable   | Description                                      |
|------------|--------------------------------------------------|
| `GROK_BIN` | Full path to the `grok` binary (overrides discovery) |

The log file is written to `~/.grok/logs/xcode-acp.log` (created automatically).

## Limitations

- The `xcode-tools` MCP server that Xcode injects is **not proxied** yet. The delegated `grok` only has standard tools + direct filesystem access via the project `cwd`.
- Streaming is basic (one final `agent_message_chunk` per prompt). No `agent_thought_chunk` or live `tool_call` updates yet.
- History is kept only in-memory for the lifetime of the bridge process.
- Every "New Conversation" in Xcode often spawns a fresh bridge process.

## Roadmap / Contributions welcome

- Proxy (or selectively forward) the `xcode-tools` MCP so the agent can build, run, and inspect the Xcode workspace directly.
- Parse tool calls and reasoning from grok output (or switch to the Grok API) and emit rich `session/update` notifications.
- Persistent per-session history under `~/.grok/sessions/`.
- Packaging (Homebrew formula, launchd plist, one-click registration, etc.).
- Support for images / embedded context when Xcode sends them.

The entire `xcode-grok-bridge.py` is a single, heavily commented file with no dependencies. You can paste the whole script into Cursor Composer, Claude, another Grok session, etc. and say:

> "Improve this Xcode Grok ACP bridge. Priority: make the xcode-tools MCP actually usable by the inner agent."

See the module docstring at the top of `xcode-grok-bridge.py` for the detailed handoff brief and protocol notes.

## License

MIT License. See [LICENSE](LICENSE) for details.
