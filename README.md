# Enterprise Agent Risk (EAIR)

EAIR is a toolkit for studying interaction risks in enterprise agent workflows.
It combines configurable multi-agent environments with an evidence-based
verifier and an iterative mitigation workflow.

Use the built-in microworlds or define your own agents, tools, policies, and
workflows to investigate how risks emerge across agent interactions.

## Installation

Requires **Python 3.11 or newer**.

```console
python -m pip install "git+https://github.com/microsoft/EAIR.git"
eair --help
```

## Quick Start

```console
eair demo --out demo-001
eair docs
```

The demo runs a small workflow with mock responses and prepares an audit task,
without making model API calls. `eair docs` opens the documentation website,
which includes setup guides, examples, and a searchable CLI reference.

## Built-in Worlds

| ID | World | Focus |
|---|---|---|
| A1 | Authority Bias | How organizational authority influences agent judgments |
| B1 | Semantic Drift | How information changes across handoffs and summaries |
| C1 | KPI Gaming | How performance incentives affect policy compliance |
| D1 | Confused Deputy | How delegated requests cross authorization boundaries |
| F1 | Provenance Paradox | How reviewer qualifications and evidence provenance affect decisions |

```console
eair list
eair run A1 --out runs/a1-smoke
eair info A1
eair study A1 --out runs/a1-study
```

`run` uses an offline smoke configuration by default. `study` previews a study
run; add `--execute` to start it. Live studies require model access and may incur
API charges. See the [study guide](docs/toolkit/STUDIES.md) for configurations and
experiment details.

## Custom Workflows

```console
eair init my-world --world-id invoice_review
eair run-world my-world/world.yaml --mock --out my-episode
eair audit-world my-episode --scope my-world/scope.md --out my-audit
```

Edit `world.yaml` to define roles, policies, document access, and handoffs. Use
`scope.md` to describe the risks you want to investigate. Existing orchestrators
can connect through the `WorldEpisode` adapter.

See [custom worlds and adapters](docs/toolkit/CUSTOM_WORLDS.md) for the full
specification and live-model examples.

## Verification and Mitigation

EAIR's V3 verifier uses interaction topology to navigate trajectories and inspect
the underlying messages, tool events, policies, and documents. Findings include
supporting evidence and targeted mitigation plans, and can describe risks beyond
those represented by the built-in worlds.

1. **Auditor:** examine the trajectory and produce an evidence-backed report.
2. **Coder:** apply the mitigation plan to an isolated copy of the environment.
3. **Repair Auditor:** independently review the changes and provide feedback.
4. **Fresh replay:** evaluate the repaired workflow on new cases, measuring both
   risk and legitimate task completion.

Live world execution requires the `live` extra and model credentials. Auditing
and repair tasks run through Harbor with a supported container runtime. See the
[verifier guide](docs/toolkit/VERIFIER.md) for setup and commands.

## Development

```console
git clone https://github.com/microsoft/EAIR.git
cd EAIR
python -m pip install ".[dev]"
python -m pytest tests -q
python -m build
```

## Responsible AI

Before using EAIR, read our [Responsible AI Transparency documentation](TRANSPARENCY.md) for intended uses, limitations, evaluation details, safe-use guidance, and instructions for reporting unexpected or unsafe behavior.

## License and Security

EAIR is licensed under the [MIT License](LICENSE). Third-party asset licenses are
included in [site assets](enterprise_toolkit/site/assets). For security reporting,
see [SECURITY.md](SECURITY.md).

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
