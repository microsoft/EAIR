# Intervention Operators

- `add_approval_gate(edge, approver_role, condition)`: insert a conditional approval before an edge completes.
- `remove_handoff_edge(edge)`: remove one declared handoff.
- `add_handoff_edge(src, dst)`: add one declared handoff.
- `reroute_information(from_edge, via_role)`: route information through a named role.
- `add_cross_check(stage, checker_role)`: add an independent second opinion.
- `patch_role_prompt(agent_id, patch_type, text)`: append the specified policy, skepticism, authority, or KPI guardrail.
- `rewrite_role_prompt(agent_id, new_prompt)`: replace one role prompt when explicitly required.
- `restrict_tool(agent_id, tool_id)`: remove a tool permission.
- `grant_tool(agent_id, tool_id)`: add a tool permission.
- `enforce_message_schema(channel, schema)`: require structured fields on a channel.
- `set_memory_policy(agent_id, policy)`: configure source/quote retention.
- `set_gate_param(gate_id, key, value)`: change one gate parameter.
