# V3 Detection and Isolated Mitigation

## Runtime Requirements

Offline export, graph tools, and task materialization use only the base Python
dependencies. Real auditors, Coders, and Repair Auditors require a separately
installed Harbor CLI, a running supported container runtime, and an authorized
agent/model provider. A typical Harbor installation is `uv tool install harbor`.
Use the Harbor documentation for platform-specific installation; container
isolation is part of the workflow, not optional host-side agent execution.

Do not upload real enterprise secrets to a model. Keep provider credentials in
the trusted host environment. Allow only the selected model API host in each
task. Public-provider examples below explicitly select `--profile custom` for
execution: the older bare `enterprise-verifier run` default is the project's
Microsoft-specific TRAPI profile.

## Prepare an Auditor Task

For a custom `WorldEpisode`:

```console
eair audit-world episode --scope my-world/scope.md --out audit
```

For a paper-world episode, export first using its runtime ID:

```console
enterprise-verifier export authority_bias EPISODE_DIRECTORY --bundles-root bundles --manifests-root private-manifests
```

The export prints bundle/manifest paths. Supply those exact paths to:

```console
enterprise-verifier auditor-task BUNDLE_DIRECTORY - MANIFEST_JSON auditor-task --discovery-only --profile v3-topology --scope my-world/scope.md --allowed-host api.openai.com
```

`-` and `--discovery-only` must be paired. Alternatively supply a private
reference-label JSON object and omit the flag. Reference inputs belong to the
grader, not the agent-visible bundle. Review sanitized bundles before sharing:
identifier pseudonymization is not arbitrary secret/PII detection.

The toolkit CLI and `enterprise-verifier auditor-task` select `v3-topology`
explicitly by default. The lower-level `materialize_auditor_task` API retains
`v3-annotated` as its compatibility default; pass `profile="v3-topology"` when
calling it directly. Standalone graph commands support `--profile v3-topology`.
The generated agent and grader images receive the same explicit graph profile.
The historical no-graph ablation is documented, not a selectable release
materializer profile.

## Run and Validate an Audit

```console
enterprise-verifier run auditor-task --profile custom --agent terminus-2 --model openai/YOUR_MODEL --runs-dir audit-runs
```

Use the actual generated task path for custom-world audits, such as
`audit/auditor-task`. Execution can incur model charges. Configure an approved
host matching the provider when materializing each task. Inspect the returned
artifact paths and Harbor job records; do not assume any JSON file is a passing
report.

The auditor uses topology to navigate, then investigates raw evidence with
`get-steps`, `diff-summary`, `check-permission`, `get-policy`, `search-policies`,
`read-doc`, and structural `graph-query`. The full report contract is retained.
Topology is not semantic evidence; annotated graph hints and inferred
provenance are not used in this profile.

The task requires `validate-report` before submission. Validation checks the
schema, bundle identity, references, literal quotes, propagation order, and
mitigation targets. A discovery-only grader records semantic evaluation as
`not_run` and does not invent precision, recall, or detection accuracy. A
reference matcher measures only the supplied narrow target; additional findings
still require independent substantive adjudication.

## Coder: Work Only on a Disposable Copy

Prepare a minimal, clean, installable source snapshot outside the original
workspace. Exclude credentials, `.git`, private manifests, answer labels, run
outputs, and unrelated environments. Keep output task directories outside this
snapshot. Supply actual smoke and legitimate-work utility checks; a constant
success result or a mock fixture is not a domain utility test.

The Python API avoids shell-dependent quoting of JSON command arrays:

```python
from pathlib import Path

from verifier.orchestrator.materialize import materialize_coder_task
from verifier.schemas.sanitize_manifest import SanitizeManifest

manifest = SanitizeManifest.model_validate_json(
    Path("private-manifests/MANIFEST_JSON").read_text(encoding="utf-8")
)
materialize_coder_task(
    risk_id="invoice_review",
    environment_source=Path("clean-source"),
    report_path=Path("auditor-report.json"),
    manifest=manifest,
    output_dir=Path("coder-task"),
    smoke_command=["python", "checks.py", "smoke"],
    utility_command=["python", "checks.py", "utility"],
    agent_allowed_hosts=["api.openai.com"],
    custom_environment=True,
)
```

The custom world ID must exactly match the original environment key in the
private manifest. A2/B2 aliases are rejected. For paper worlds use the registry
risk ID and leave `custom_environment=False`. Reports without findings and
missing smoke/utility commands are rejected.

Coder tasks contain the deanonymized report, a copied environment, validation
commands, feedback, and the mitigation operator library. The generic Coder
image starts from Python and the copied source; **install your environment's
dependencies in its Dockerfile before execution**. A clean-source project can
include the provided toolkit wheel for offline installation. The conversation
starter alone is not a complete installable Coder source snapshot. Pin and
review build dependencies before enabling network access during image builds.

```console
enterprise-verifier run coder-task --profile custom --agent terminus-2 --model openai/YOUR_MODEL --runs-dir coder-runs
```

Do not automatically apply its patch to the original world. Preserve the
pristine snapshot, modified snapshot, structured repair report, diff, and check
results. Resolve findings back to original identities using the Coder task's
report; don't compare anonymized IDs against original source identifiers.

## Independent Repair Review and Fresh Replay

```console
enterprise-verifier repair-auditor-task clean-source modified-source coder-task/environment/report.json repair_report.json repair-auditor-task --allowed-host api.openai.com
enterprise-verifier run repair-auditor-task --profile custom --agent terminus-2 --model openai/YOUR_MODEL --runs-dir repair-runs
```

The Repair Auditor receives pristine/modified sources and the reports. It
checks plan coverage and whether changes preserve legitimate work without
weakening policies, removing roles/tools, or shifting the success criteria.
Prepare the review image dependencies for your environment as well. The
schema/coverage validator does not itself prove a repair is correct.

For iterative repairs the Python materializers accept prior feedback, session
memory, and an iteration number. Preserve these as private experiment records.
There is deliberately no automatic "publish this patch" operation.

After an accepted review, execute fresh repaired-world trajectories on held-out
cases/seeds and export them through the same adapter. Measure risk, utility,
liveness, and unneeded escalation separately. Reaudit those trajectories. A
successful audit or Repair Auditor review alone is not a fresh behavioral
evaluation, and general success cannot be inferred from five historical worlds.

## Trust Boundaries

- Agent-visible auditor input: sanitized bundle, scope, tools, and report schema.
- Grader-only input: private manifest, optional truth, independent bundle copy.
- Coder input: isolated original-identity source/report and explicit checks.
- Repair Auditor input: independent pristine/modified snapshots and reports.
- Public release input: allowlisted framework code/templates/configs only.

Generated task folders contain grader secrets in `tests/`; never publish or
mount the entire task folder into the agent's environment. Treat all trajectory
and document contents as untrusted evidence, including instructions embedded
by the observed agents. Human review is required for sensitive enterprise use.