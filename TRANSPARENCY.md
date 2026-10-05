# EAIR Responsible AI Transparency Documentation

## Overview

We developed EAIR to study interaction risks in enterprise-like multi-agent simulations. Our framework helps researchers specify workflow policies, inspect execution traces, and evaluate proposed code repairs.

This initial public release covers source code and documentation, not model weights, datasets, saved research trajectories, or human-participant data. Users run it locally with their own model-service accounts and API keys. Microsoft provides no hosted runtime, model API access, or credentials. Real enterprise data, services, and integrations are excluded.

### What EAIR can do

We study five constructed risk families: cumulative credits exceeding a shared cap, authority-biased evidence, information or approval drift across role handoffs, delegated-permission failures, and capability routing. Policies define expected behavior. Ledgers, canaries, and tool records provide deterministic ground truth where possible; model-based semantic judgments link to quoted evidence.

Our auditor examines traces with policies, role information, and tool metadata to produce candidate findings linked to quoted evidence. A separate coding agent proposes scoped repairs. Independent adjudication and behavioral tests examine risk resolution, task fidelity, new risks, proportionality, and utility.

### Intended users and uses

We intend EAIR for researchers, developers, and evaluators able to interpret multi-agent traces, inspect generated code, and assess evidence. Appropriate uses include reproducing bounded synthetic experiments, evaluating findings, and testing repairs or extensions in isolated research environments.

### Out-of-scope uses

EAIR is not a production approval tool, comprehensive vulnerability scanner, safety certificate, or general model leaderboard. Employee assessment, surveillance, consequential decisions about people, autonomous changes to real permissions, and other high-stakes operations are outside our intended scope. Do not repurpose EAIR for policy bypass or unauthorized access.

### How to get started

Repository: [https://github.com/microsoft/EAIR/](https://github.com/microsoft/EAIR/)

Follow its version-specific setup instructions and choose a documented model-service configuration. Start with a small synthetic scenario; inspect its roles, rules, inputs, expected artifacts, outputs, and API usage before scaling up.

### Models, data, and processing

EAIR uses existing models without new training. Model calls send synthetic configurations, prompts, role/policy/tool metadata and execution records to configured providers. Outputs include messages, tool interactions, traces, evidence-linked findings, proposed patches and evaluation results.

Our research model roster was GPT-5.6 Terra, GPT-5.5, DeepSeek V4 Pro, DeepSeek V3.2, Grok 4.20 Reasoning, Grok 4.3, Kimi K2.6, Qwen 3.5 397B, Mistral Large 3, and Llama 3.3 70B, accessed through one common gateway.

Processing and retention depend on the configured service and local setup.

### Evaluation

#### Evaluation methods

We evaluated 1,188 execution-valid episodes across five risk families using models from seven vendors. Per-family configurations and exclusions are detailed in Appendix D. Environment judging and synthetic counterparties used GPT-5.6 Sol; the compensation-cap world used a deterministic primary ledger. We examined policy compliance and task performance, checked evidence references, and evaluated repairs separately (§5.1; Appendix D). A separate auditor pilot used 100 held-out historical trajectories, 20 per world: 44 seeded-positive and 56 seeded-negative (§5.3).

#### Evaluation results

In the 100-trajectory auditor pilot, our auditor returned a risk verdict on all 44 seeded-positive trajectories; 99 of 100 reports met the mechanical evidence contract for citations and a mitigation plan. This does not establish exhaustive recall, semantic correctness, or a comparative detection advantage: a same-model naive reader using the same bundles flagged 43 of 44 seeded positives. Independent semantic assessment remains necessary, and seeded-negative labels are not exhaustive evidence of absence of risk (§5.3).

Task completion coexisted with policy failures, and static repair approval was insufficient. Behavioral retesting assessed risk resolution, utility and new risks, but covered limited test cases rather than all configurations (§§4–5).

Our broader study also evaluated externally produced MAST/MAD traces. Missing context and unresolved label and contamination issues limit that evidence (§5.4; Appendix G.17).

### Known limitations

Constructed stress tests do not estimate production failure rates. Generalization beyond the five families, fixed contexts, languages, cultures, authority conventions, or demographic groups is unestablished. Provider training-data composition and evaluation overlap are unknown here. Bias, memorization, nondeterminism, dependency changes, and provider drift can affect findings and reproducibility.

### Safe use and best practices

Treat traces, model outputs, dependencies, and patches as untrusted. Use isolated execution with minimal permission; avoid sensitive host mounts and production credentials. Restrict filesystem and network access. Set and monitor time, token, concurrency, resource, and spending limits. These are user precautions, not automatically enforced controls in every configuration.

Do not supply personal data, confidential code, or other sensitive material. Keep credentials out of prompts, source files, shared configurations, and reports. Inspect request destinations, logs, and exports; minimize retention, remove secrets before sharing, and rotate exposed credentials. Respect input and dependency licenses, provider terms and controls, and responsible-AI policies.

### Contact and further reading

If you have suggestions, questions, or observe unexpected/offensive behavior in our technology, please contact us at [swads@microsoft.com](mailto:swads@microsoft.com). If the team receives reports of undesired behavior or identifies issues independently, we will update this repository with appropriate mitigations.

Further reading: our paper, “EAIR: A Framework for Specifying, Analyzing, and Detecting Enterprise Multi-Agent Interaction Risks,” §§3–5 and Appendices D–F and H.
