# Custom Enterprise World

Edit `world.yaml` to define roles, visible documents, policies, and ordered
handoffs. Edit `scope.md` to state your research question without revealing an
answer label. Use a new world ID rather than a built-in paper risk ID.

From the directory containing this world:

```console
eair run-world world.yaml --mock --out ../episode
eair audit-world ../episode --scope scope.md --out ../audit
```

Both commands are offline. The first replays explicit `mock_response` values;
the second prepares a discovery-only Harbor task without running an auditor.
Do not interpret either as evidence of real model behavior or mitigation.

For a real world trajectory, install the toolkit's `live` extra, configure
credentials through environment variables, and explicitly select a provider:

```console
eair run-world world.yaml --provider openai --model YOUR_MODEL --out ../live-episode
eair audit-world ../live-episode --scope scope.md --out ../live-audit
```

`mock_response` is required as an offline fixture but is never sent to the live
model. Agents receive only their own sent/received messages, documents allowed
by the document ACL, and applicable policies. The common task is visible to all
roles. Do not put role-private secrets in that common task or in audit scope.

The starter is conversation-only: text claiming a tool ran is not a tool event.
For tools, state changes, parallel scheduling, or a different framework, emit
`WorldEpisode(metadata=..., trajectory=..., documents=...)` from your own
orchestrator and use `eair export-world` or `audit-world`.

Keep `private-manifests` and source episodes private. Review the sanitized
bundle before sharing it; pseudonymization is not general secret/PII removal.
Task directories contain private grader inputs in `tests/` and must not be
published wholesale or mounted into the auditor's agent container.

A real audit requires separately installed Harbor, a working container runtime,
and a configured agent/model. Start with the generated task's `instruction.md`
and the release's `docs/toolkit/VERIFIER.md`. Repair requires an isolated,
installable source snapshot plus real smoke and utility checks. This starter
does not pretend to supply a domain-specific utility oracle.