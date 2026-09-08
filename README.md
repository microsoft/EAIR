# Enterprise Agent Risk (EAIR)

EAIR is a research toolkit for detecting and mitigating enterprise multi-agent
interaction risks. Version **0.3.1** includes five enterprise microworlds, a full
V3 verifier with topology navigation, isolated repair workflows, and templates
for studying additional risks in your own environments.

This repository contains **only the toolkit and its supporting documentation,
tests, and selected configurations**. It does not contain the surrounding
research workspace, experiment outputs, presentations, or the A2/B2 environments.

## Install

Python 3.11 or newer is required. Install directly from this repository:

```console
python -m pip install "git+https://github.com/microsoft/EAIR.git"
eair --version
eair list
```

For development, use a separate virtual environment and install from a checkout:

```console
git clone https://github.com/microsoft/EAIR.git
cd EAIR
python -m pip install ".[dev]"
```

The primary command is `eair`. The Python distribution remains
`enterprise-microworld`, the import package remains `enterprise_toolkit`, and
`enterprise-toolkit` remains a compatibility alias. If the console script is not
on PATH, use `python -m enterprise_toolkit` with the same arguments.

## Documentation Website

```console
eair docs
```

This opens the complete English documentation website included in the package.
Its 15 pages cover installation, the five paper worlds, custom environments,
new-risk research, auditing, reports, isolated mitigation, fresh replay, and CLI
reference. Search and code-copy controls work offline, without a web server.

Export the complete site into a new directory for static hosting:

```console
eair docs --export public-docs --no-open
```

The website files are in [enterprise_toolkit/site](enterprise_toolkit/site).
GitHub displays the HTML source; `eair docs` opens the rendered local website.

## Offline Quick Start

```console
eair demo --out demo-001
```

This creates an editable world, a deterministic mock episode, a sanitized audit
bundle, a private identity manifest, and a discovery-only V3 topology Harbor task.
It does **not** run a semantic auditor or a mitigation agent. The generated
summary explicitly records both as not executed. Existing output directories are
not overwritten.

The base installation needs no API keys, model SDKs, or container runtime for mock
execution, export, graph tools, and task preparation. Real world execution needs
the `live` extra and provider credentials. Real auditors, Coders, and Repair
Auditors also need separately installed Harbor and a supported container runtime.
See the [verifier guide](docs/toolkit/VERIFIER.md).

## Included Worlds

| Paper ID | World | Selected study coverage |
|---|---|---|
| A1 | Authority Bias | Realistic organizational power ABCD study and separate title-by-power factorial |
| B1 | Semantic Drift | Ten-model split-rubric study with the Kimi K2.5 replacement cohort |
| C1 | KPI Gaming | V2 mild/strong report derived from a three-level source configuration |
| D1 | Confused Deputy | Prompt-neutral L6 authorization inquiry across HR, Finance, and Security |
| F1 | Provenance Paradox | Nine-condition study plus matched solo calibration |

The [catalog](enterprise_toolkit/catalog.json) identifies 15 selected smoke,
study, and supplemental configurations. The [provenance guide](docs/toolkit/PROVENANCE.md)
records report dates, runner distinctions, later follow-ups, and snapshot limits.
Historical report paths are research provenance references; the corresponding
reports, raw results, and isolated repaired source trees are not bundled here.

```console
eair run A1 --out runs/a1-smoke
eair info A1
eair study A1 --out runs/a1-study
```

`run` defaults to a packaged offline smoke configuration. `study` previews the
report-selected runner; `--execute` is required to start it and can incur model
charges. A1's title-effect study and F1's calibration/main pipeline are distinct
from their compatibility smoke runs. See [study usage](docs/toolkit/STUDIES.md).

## Custom Worlds and New Risks

```console
eair init my-world --world-id invoice_review
eair run-world my-world/world.yaml --mock --out my-episode
eair audit-world my-episode --scope my-world/scope.md --out my-audit
```

Edit the roles, policies, document ACLs, handoffs, and fixtures in the world
specification. The audit scope can investigate mechanisms beyond the five paper
risk labels. Existing orchestrators can emit the environment-neutral
`WorldEpisode` contract instead of adopting the conversation starter. See
[custom worlds and adapters](docs/toolkit/CUSTOM_WORLDS.md).

## Detection and Isolated Mitigation

1. Export an observed trajectory and its source context into a sanitized bundle.
2. Audit the evidence in an isolated, read-only agent environment.
3. Give a separate Coder an isolated source snapshot, a supported report, and
	explicit smoke and legitimate-work utility checks.
4. Have an independent Repair Auditor compare pristine and modified sources.
5. Execute fresh repaired-world cases and evaluate both risk and legitimate work.

Findings are open-ended and require evidence. Mechanical schema/reference checks
are not semantic proof. Additional discoveries need independent substantive
adjudication, and a reviewed patch is not an automatic deployment approval.
Keep private manifests, reference labels, credentials, and generated task folders
out of public uploads.

## Build and Test

```console
python -m pip install ".[dev]"
python -m pytest tests -q
python -m build
```

Builds use an explicit source/resource allowlist rather than archiving the working
tree. The wheel includes the CLI, runtime code, selected presets, role assets,
starter templates, documentation website, and all three Harbor task templates.
No paid model runs or public uploads are performed by these build commands.

## License and Security

EAIR is distributed under this repository's [MIT License](LICENSE). Bundled
third-party fonts and icons retain their own license files in
[site assets](enterprise_toolkit/site/assets). Report security issues through
[SECURITY.md](SECURITY.md), not by including secrets or sensitive trajectories in
public issues.

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
