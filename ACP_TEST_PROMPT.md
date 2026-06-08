# ACP Protocol Test Prompt for Xcode + Grok Bridge

Copy and paste the following **exactly** as the first message in a fresh "New Conversation" with your Grok Build agent in Xcode.

This prompt is designed to:
- Force a `session/prompt` over ACP (so we can see if Xcode actually delivers user messages to the external agent).
- Exercise tool calls visibly (list_dir, read_file, run_terminal_command) — these should appear in the wrapper log as the agent uses them, and ideally show in Xcode UI if it supports tool updates.
- Ask the agent to self-report protocol details it received (sessionId from session/new, capabilities from initialize, mcpServers especially the xcode-tools one, cwd).
- Test streaming/updates (agent_thought_chunk or message chunks).
- Verify project context (correct CWD, ability to access files).
- Include a safe "build-like" test without actually building yet.
- Be self-contained so the agent's response gives us clear pass/fail signals on the full ACP flow.

---

**ACP Full Protocol Validation Test**

You are participating in a test of the Agent Client Protocol (ACP) between Xcode and this external agent.

Please perform the following steps **in order**, using the ACP mechanisms, and be **extremely explicit** in your final response about what you observed from the protocol:

1. Confirm the `sessionId` you received in the `session/new` request from the client. Also confirm the exact `cwd` that was provided in that request, and list any `mcpServers` that were injected (pay special attention to anything named "xcode-tools" or using `xcrun mcpbridge`).

2. Confirm the `clientInfo` and `clientCapabilities` that were sent in the `initialize` request, and briefly note what you returned in your `initialize` result (especially capabilities around fs, terminal, mcp, and any `_meta`).

3. Use your `list_dir` tool on the current directory ('.'). Explicitly state the exact tool call parameters you used and the full result you received. List every file and folder visible.

4. Use your `read_file` tool to read the file `test-grok/ContentView.swift`. Quote the **exact** string inside the `Text(...)` view. Again, state the tool call and result.

5. Use your `run_terminal_command` tool to execute the following safe command and capture its output:  
   `echo "ACP protocol test from Xcode external agent at $(date)"`  
   Report the exact command executed and the stdout/stderr.

6. If the `xcode-tools` MCP server (or any other MCP servers provided in session/new) is connected and usable from your side, list the tools it exposes and attempt **one safe, read-only** operation with it (e.g., something that inspects the project without modifying files or building). If you cannot access or use the injected MCP servers, explicitly say so and explain what you see in the protocol for them.

7. If your ACP implementation supports streaming thoughts or intermediate steps, send at least one `agent_thought_chunk` (or equivalent `session/update`) during your reasoning before giving the final answer.

After completing the above, give a clear **Protocol Test Summary** with:
- Pass/fail for each step.
- The `sessionId` and `cwd` you actually used.
- Any discrepancies you noticed between what Xcode sent and what a standard ACP client would expect.
- Whether you received a proper `result` for `session/new` containing a `sessionId` (this is critical for Xcode to consider the session live and deliver prompts).
- Overall assessment: "Full ACP roundtrip working from Xcode's perspective" or specific blockers.

Be concise in the summary but include the raw evidence (tool call details, protocol observations) so we can verify the integration end-to-end.

This test will tell us exactly which parts of the ACP flow (initialize, session/new result, prompt delivery, tool execution via updates, MCP injection, streaming) are functional with Xcode's current implementation.
