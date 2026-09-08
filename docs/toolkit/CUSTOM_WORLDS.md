# Custom Worlds and Adapters

## Conversation Starter

```console
eair init my-world --world-id invoice_review
eair run-world my-world/world.yaml --mock --out episode-mock
```

`init` creates `world.yaml`, `scope.md`, and a local README in a new directory.
The starter contains three roles and a purchase-review workflow, not a new
hard-coded risk class. Change the domain, workflow, and research question.

The YAML contract is validated by
[`WorldSpec`](../../enterprise_toolkit/custom.py). It contains a world ID, a
common task, environment metadata, document contents, and ordered turns. Each
turn specifies sender, receiver, channel, instruction, and an offline fixture.
The receiver must be another role or a `user:` endpoint. The starter has no tool
executor: record real tool calls through the adapter API instead.

Per-turn model context contains the acting role's prompt, the common task,
its sent/received messages, documents allowed by document ACLs, and applicable
policies. A role does not automatically see another role's private inbox or
documents. Do not put private role-specific information in the common task.
Policies are prompt context, not a substitute for enforced tool authorization.

## Live Execution

Install the `live` optional dependencies and configure the appropriate provider
environment variable outside the source tree. Never place API keys in world
YAML, trajectory data, reports, or templates.

```console
eair run-world my-world/world.yaml --provider openai --model YOUR_MODEL --episode-id live-001 --out episode-live
```

Supported starter providers are `openai`, `anthropic`, `openrouter`, and `trapi`.
They reuse the project's existing model adapters. OpenAI, Anthropic, and
OpenRouter use their respective API-key environment variables. TRAPI is an
optional Microsoft-specific backend requiring an authorized Azure identity; it
is not needed for the public workflow. Provider availability and model IDs are
the caller's responsibility.

Choose either `--mock` or `--provider` explicitly. `--model` is required for a
provider and rejected in mock mode. Offline fixture responses are not sent to
the live model. A supplied backend using the Python API is treated as live
unless `mock=True` was explicitly chosen. Empty responses and unsupported tool
requests fail instead of being recorded as successful actions.

## Adapt an Existing Orchestrator

Keep your scheduler, agents, and tools. Emit the existing verifier types rather
than adding a new risk ID to the five-world registry:

```python
from pathlib import Path

from enterprise_toolkit.custom import WorldEpisode


def save_observed_episode(
    metadata: dict,
    trajectory: dict,
    documents: dict[str, str],
    destination: Path,
) -> Path:
    episode = WorldEpisode.model_validate({
        "metadata": metadata,
        "trajectory": trajectory,
        "documents": documents,
    })
    return episode.write(destination)
```

The schemas are
[`EnvMetadata`](../../verifier/schemas/env_metadata.py) and
[`Trajectory`](../../verifier/schemas/trajectory.py). Metadata inventories roles,
policies, workflow, tools/ACLs, document paths/ACLs, and harness information.
Trajectory steps preserve original messages, actual tool calls/results,
timestamps, agent identities, and stable step IDs. Do not turn an intention in
text into an executed tool result. Preserve failures and missing outputs.

Trajectory agents must exactly match metadata roles. Document contents must
exactly match the inventory, with paths below `documents/` and no traversal.
Use synthetic enterprise data and exclude real customer data and credentials.

```console
eair export-world observed-episode --out exported
eair audit-world observed-episode --scope my-world/scope.md --out audited
```

`export-world` writes only the sanitized bundle and private identity manifest.
`audit-world` also prepares a Harbor task. Neither starts an auditor or performs
semantic judging. The output is JSON containing the exact generated paths.

## Study a New Risk

Define legitimate task completion and enforced authority before choosing risk
labels. Record the hypothesized interaction mechanism, intervention, and outcome
measurement separately. Include risk-present and clean or legitimate-work cases.
Keep held-out cases and private reference labels outside agent inputs.

By default, `audit-world` is discovery-only. The scope asks the auditor to
investigate supported mechanisms without requiring a positive result or a fixed
taxonomy. Optional `--ground-truth reference.json` enables the existing private
reference matcher; extending a risk taxonomy does not automatically create a
valid semantic judge for it.

Separate direct evidence, plausible unobserved risk, and confirmed business
impact in your analysis. Review additional findings independently of the
predefined target judge. Evaluate mitigation on fresh seeds/cases with both
risk and utility metrics. The starter deliberately does not invent a universal
utility oracle or pretend mock fixtures validate a repair.

See [VERIFIER.md](VERIFIER.md) for isolation and repair requirements.