# Toolkit 0.2.0 Release Provenance

Selection date: 2026-09-06. The machine-readable release catalog is
[enterprise_toolkit/catalog.json](../../enterprise_toolkit/catalog.json).
Only A1 `authority_bias`, B1 `semantic_drift`, C1 `kpi_gaming`, D1 `d1`, and
F1 `f1` are in scope. A2 and B2, including archived configurations, are excluded.

## Selection and Runtime Contract

Selections preserve the latest report-derived study coverage and distinguish
later follow-ups from the primary experiments. They do not identify a
statistically best environment, configuration, model, or verifier.

The `package`, `run_module`, `display_name`, and `smoke_config` fields come from
[risk_environments/registry.py](../../risk_environments/registry.py).
The registry entry describes the current runtime and smoke command. A historical
study can require a different runner; `study_runners` records that distinction.
Packaging should include the union of each world's `smoke_config`,
`recommended_configs`, and `supplemental_configs`, not every YAML in the tree.
All catalog file paths are relative to the workspace root. Documentation links
are relative to this document. A null `body_updated` means that no separately
dated body revision was identified, not that the file is an immutable snapshot.

## A1: Authority Bias

The [July 26 ABCD report](../../EXPERIMENT%20RESULTS%20REPORT/authority_deference/EXPERIMENT_RESULTS_2026-07-26_AUTHORITY_REALISTIC_POWER_10MODELS_N3_ABCD_EN.md)
supersedes the earlier 240-episode A/C study with 480 episodes: ten model slots,
four reviewer roles, four conditions, and three seeds. Its reproducible-artifact
section directly links
[configs/authority_title_effect_realistic_power_abcd_n3.yaml](../../configs/authority_title_effect_realistic_power_abcd_n3.yaml).

Retain the distinct 48-episode title-by-power factorial pilot, documented in the
[July 26 factorial report](../../EXPERIMENT%20RESULTS%20REPORT/authority_deference/EXPERIMENT_RESULTS_2026-07-26_AUTHORITY_POWER_FACTORIAL_3MODELS_N2_ZH.md),
using
[configs/authority_organizational_power_factorial_pilot.yaml](../../configs/authority_organizational_power_factorial_pilot.yaml).
The protocols are respectively `realistic_organizational_power_v4` and
`organizational_power_factorial_v5`. Both study YAMLs use
[run_authority_title_effect.py](../../run_authority_title_effect.py), not the
registry's multi-role [run_authority.py](../../run_authority.py).
Each YAML supplies an individual model setting; it does not by itself recreate
the report's entire cross-model matrix.

The most recently updated Authority report is the
[August 4 liveness analysis](../../EXPERIMENT%20RESULTS%20REPORT/authority_deference/AUTHORITY_POST_MITIGATION_LIVENESS_ANALYSIS_2026-08-04_ZH.md),
whose body contains August 18, 19, and **August 20** updates. The August 20
`fresh20` is a named, optional post-mitigation A-E workflow follow-up. It is not
the ABCD experiment, not the EFGH factorial, and not a silent replacement for
either. It reports final root-cause and executive-summary submission in 20/20
episodes, but complete five-section workflows in only 7/20; upstream SRE
finalization remains unresolved.

The named supplemental configuration is
[authority_20.yaml](../../verifier/runs/20260803_v3_fresh_100/authority_liveness_repair_candidate/authority_20.yaml)
inside the isolated liveness candidate. It specifies A-E, four seeds per
condition, and seed start 20042. The
[executed fresh20 matrix](../../verifier/runs/20260803_v3_fresh_100/authority_liveness_repair_candidate/LIVE_ATOMIC_20_REPORT_ZH.md)
uses replacement seeds for D (20042, 20046-20048) and E (20046-20049).
Consequently this YAML records the batch design, not the complete executed
schedule. The [resilient driver](../../verifier/runs/20260803_v3_fresh_100/authority_liveness_repair_candidate/run_live_20_resilient.py)
generates per-episode JSON and runs the workspace Authority entry point with
the candidate as its working directory and `PYTHONPATH`. Including the YAML in
a release does **not** transplant the repaired candidate implementation into
the current root runtime. That isolated-source dependency remains explicit.

## B1: Semantic Drift

The [ten-model split-rubric report](../../EXPERIMENT%20RESULTS%20REPORT/semantic_drift/EXPERIMENT_RESULTS_2026-07-24_SEMANTIC_DRIFT_10MODELS_N3_EN.md)
has a July 24 filename but declares **July 26** in its body and includes the
replacement cohort. Preserve both configurations:

- Original cohort: [configs/drift_paper_priority_10models_n3.yaml](../../configs/drift_paper_priority_10models_n3.yaml).
- Reported replacement: [configs/drift_kimi_k25_replacement_n3.yaml](../../configs/drift_kimi_k25_replacement_n3.yaml).

The report's 150 valid episodes comprise ten models, five conditions, and three
episodes per cell in the weak scenario. Kimi K2.5 **replaces DeepSeek V4 Pro**;
it is not an eleventh model. The original YAML still contains DeepSeek V4 Pro,
so running it alone does not reconstruct the final reported cohort. The failed
Grok fallback is excluded from the report's valid sample. Reconstruction must
select the valid original-model rows and merge the replacement, not concatenate
two complete cohorts. The split rubric separates decision-status and
submission-status drift; terminal drift is assessed in a final email actually
sent to the customer.

## C1: KPI Gaming

The latest [July 21 mild/strong report](../../EXPERIMENT%20RESULTS%20REPORT/kpi_gaming/EXPERIMENT_RESULTS_2026-07-21_KPI_V2_MILD_VS_STRONG_ZH.md)
analyzes July 20 data: eleven models, two pressure levels, and three episodes,
totaling **66**, with None excluded. The exact adjacent source-study config is
[configs/kpi_v2_all11_kpi_levels_n3.yaml](../../configs/kpi_v2_all11_kpi_levels_n3.yaml).
It contains all three levels (`none`, `mild`, `strong`) and plans 99 episodes;
it is not a newly invented mild/strong-only config or the earlier n5 study.

The trace is the report's linked
[mild/strong analyzer](../../analyze_kpi_v2_mild_strong.py), its
[99-row input](../../figures/kpi_v2_all11_20260720/results_merged_first_success_99.json),
and the adjacent [source-run analyzer](../../analyze_kpi_v2_all11.py).
The source analyzer keeps the first successful result for each model, pressure
level, and seed across the source runs; the latest analysis filters to mild and
strong and produces the
[66-row report dataset](../../figures/kpi_v2_mild_strong_20260721/results_mild_strong_66.json).
Reproduction must retain that filtering and deduplication distinction.

The YAML matches the report's `risk_v2` contacts, `multi_agent` mode,
`on_demand` visibility, zero initial compensation, six-minute history-check
cost, seed 142, and `global_policy_in_prompt: false`. Strong is a bundled
prompt/dashboard/warning treatment, not a pure pressure-dose manipulation.
The report's Mild dashboard and SLA-feedback inconsistencies and Llama
tool-call limitation are retained as caveats, not silently reinterpreted as
evidence of safety or a best configuration.

## D1: Confused Deputy

The [July 27 L6 three-domain report](../../EXPERIMENT%20RESULTS%20REPORT/d1_confused_deputy/EXPERIMENT_RESULTS_2026-07-27_D1_L6_AUTHORIZATION_INQUIRY_10MODELS_3DOMAINS_N3_EN.md)
explicitly pools two runs with the same ten models and three seeds:

- HR: [configs/d1_l6_10models_hr_n3_rerun.yaml](../../configs/d1_l6_10models_hr_n3_rerun.yaml), 30 episodes.
- Finance and Security: [configs/d1_l6_10models_finance_security_n3.yaml](../../configs/d1_l6_10models_finance_security_n3.yaml), 60 episodes.

Both are recommended. Together they cover the complete 90-episode L6 study;
neither the HR-only report nor an older non-L6 cross-domain YAML is an adequate
substitute. The optional inquiry tool is prompt-neutral, with authorization
propagation and tool field ACL disabled. Its presence is not an enforced
authorization boundary. The reported association between inquiry use and
outcomes is not a causal treatment estimate or a basis for ranking domains.

## F1: Provenance Paradox

The [July 26 experiment report](../../EXPERIMENT%20RESULTS%20REPORT/f1_provenance_paradox/EXPERIMENT_RESULTS_2026-07-26_F1_PROVENANCE_PARADOX_10MODELS_N3_EN.md)
directly links
[configs/f1_paper_priority_10models_n3.yaml](../../configs/f1_paper_priority_10models_n3.yaml):
ten models, nine conditions, and three episodes per cell, totaling 270. Keep
all nine conditions, including the configuration-equivalent `F_hedge_H1`
replication of `main`; do not reduce the selection to a favorable ablation.

The separate optional study artifact is
[configs/f1_paper_priority_10models_n3_calibration.yaml](../../configs/f1_paper_priority_10models_n3_calibration.yaml),
not the generic solo-calibration example. It specifies three solo reviews per
delegate and model, totaling 90. The historical main YAML sets
`require_solo_capability: true`; omitting calibration requires existing compatible
solo-capability data, and the report's counterfactual-regret metric depends on
those data. The [paper-study runner](../../run_f1_paper_study.py) names both
configurations as defaults and connects calibration to the main study. The
[calibration runner](../../run_f1_calibration.py) is a distinct entry point from
the registry's main runtime.

The [F1 run-status file](../../EXPERIMENT_RESULTS%20ANALYSIS/f1_provenance_paradox/F1_10MODEL_N3_RUN_STATUS.md),
updated July 26, confirms 270/270 main episodes and 90/90 solo reviews. It is
used only for completion status, not as a substitute for the experiment report.
No other results from the analysis-status directory determine this catalog.

The later [August 21 escalation analysis](../../EXPERIMENT%20RESULTS%20REPORT/f1_provenance_paradox/F1_POST_MITIGATION_ESCALATION_ANALYSIS_2026-08-21_ZH.md)
is recorded as a separate post-mitigation follow-up. All 20 unsafe-contract cases
produced final `ESCALATE` verdicts; none proposed `SIGN` and the legal gate was
not exercised in that live cohort. There was no safe-to-sign positive control,
so this does not establish automatic-signing utility or needless abstention.
The report also distinguishes focused repair-auditor tests from a full live
replay of the four original failing cases. The isolated repaired source is not
silently substituted for the primary nine-condition study implementation.

## Verifier: Full V3 With Topology Navigation

The selected release profile is **`v3-topology`**, with verifier version `V3`,
feedback contract `3.0`, and graph variant `topology-only-1.0`. This selects a
documented contract and navigation design, not a statistically best verifier.
The topology graph payload uses schema version `topology-1.0`.

The [topology experiment report](../../verifier/runs/20260831_v3_fresh_100_topology/EXPERIMENT_REPORT_ZH.md)
retains the deterministic investigation tools, report schema, and validator.
The [preparation source](../../verifier/runs/20260831_v3_fresh_100_topology/prepare_topology.py)
defines `TOPOLOGY_OVERRIDE` and `NEW_PROCEDURE`; the
[audit runner](../../verifier/runs/20260831_v3_fresh_100_topology/run_auditors.py)
records V3, contract 3.0, the topology variant, and task/truth digests.
Topology supplies participants and time/channel/step/edge references, with no
content summaries, inferred provenance, or risk annotations. It is navigation,
not evidence of risk. Raw steps and source material support findings, and
`validate-report` remains mandatory.

The [no-graph experiment report](../../verifier/runs/20260901_v3_fresh_100_no_graph/EXPERIMENT_REPORT_ZH.md),
with an explicit September 3 table correction, supports **no-graph as an
ablation only**. It removes graph access while retaining raw evidence,
non-graph tools, schema, and validator. It does not justify making no-graph the
release default, nor does this catalog turn the reported comparisons into a
general superiority claim. The report does not repeat mitigation experiments.

The latest [September 4 R1/R2 report](../../verifier/runs/20260904_r1_r2_reviewer_response/R1_R2_EXPERIMENT_REPORT_ZH.md)
distinguishes the full contract from R2's naive free-text baseline, which removes
the deterministic toolkit, schema, and pre-submission validator. The
[R1/R2 preparation source](../../verifier/runs/20260904_r1_r2_reviewer_response/pipeline.py)
copies the **August 3 pilot tasks** for R1, not the August 31 topology task tree.
The [R1/R2 runner](../../verifier/runs/20260904_r1_r2_reviewer_response/run_experiments.py)
checks source snapshots. Thus these follow-ups trace the full contract but are
not direct cross-vendor reruns of the topology-only variant.

R1/R2 model execution is reported complete, but substantive human worksheets
remain outstanding; the [generated English companion](../../verifier/runs/20260904_r1_r2_reviewer_response/EXPERIMENT_REPORT.md)
still says `INCOMPLETE`. Do not reinterpret machine-checkable citation
resolvability as substantive recovery or completed adjudication of additional
findings. The auditor is an open-ended risk discoverer. A fixed judge covers
only its preregistered narrow target; additional findings are reviewed separately
as substantively adjacent interaction risk, operational failure, or material
impact not yet confirmed.

The [shared graph source](../../verifier/auditor_toolkit/graph.py) inspected for
this catalog contains the legacy annotated implementation. The topology override
and materialized topology tasks are the profile's behavioral source. The release
extracts this behavior into [topology.py](../../verifier/auditor_toolkit/topology.py)
and selects it with [profiles.py](../../verifier/orchestrator/profiles.py).
The [toolkit CLI](../../enterprise_toolkit/cli.py) and
[verifier auditor-task CLI](../../verifier/cli.py) now select `v3-topology`
explicitly. The lower-level materializer API and graph resolver keep annotated
compatibility defaults; pass an explicit topology profile outside those CLIs.

### Exact Template and Validator Trace

The [generic materializer](../../verifier/orchestrator/materialize.py) copies the
[base instruction](../../verifier/harbor_tasks/auditor_template/instruction.md),
expands the [interaction-scope template](../../verifier/harbor_tasks/auditor_template/interaction_risk_scope.md),
and copies the toolkit and schemas. The base procedure still includes graph
annotations and `trace-provenance`; it is not the topology profile by itself.

The [representative materialized topology instruction](../../verifier/runs/20260831_v3_fresh_100_topology/auditor_tasks_v3/audit_001_kpi_gaming/instruction.md)
contains the actual topology-only procedure. Its
[Dockerfile](../../verifier/runs/20260831_v3_fresh_100_topology/auditor_tasks_v3/audit_001_kpi_gaming/environment/Dockerfile)
wires all nine catalog commands and omits the `trace-provenance` launcher. Its
[materialized graph source](../../verifier/runs/20260831_v3_fresh_100_topology/auditor_tasks_v3/audit_001_kpi_gaming/environment/verifier_pkg/verifier/auditor_toolkit/graph.py)
contains the active override, not merely a differently named profile.

The [report schema](../../verifier/schemas/report.py),
[bundle-context validator](../../verifier/auditor_toolkit/validation.py), and
[command entry points](../../verifier/auditor_toolkit/cli.py) form the current
contract trace. The catalog also names their materialized counterparts for
comparison. Validation checks report/bundle identity, resolvable steps and
edges, quotes present verbatim in cited steps, time-ordered propagation, and
mitigation targets. Passing these mechanical checks does not establish the
substantive validity of a risk claim.

Verifier reports without an explicit report date have `report_date: null`.
Their `run_date` records the experiment directory label, not an inferred report
generation date or filesystem modification time.

## Snapshot Limits

The catalog records existing local files and report-to-configuration links.
Historical reports are evidence for experimental design and reported results;
the presence of a similarly named current source file or YAML does not establish
that its bytes match those originally executed. Model overrides, study drivers,
provider availability, later source edits, and isolated mitigation candidates
must be accounted for separately when attempting historical reproduction.

A release manifest or source hash identifies the **current audited or packaged
snapshot**. It is release provenance, not proof of original historical bytes,
and is not by itself evidence that a historical run used that snapshot. No model
runs or credential inspection are part of this provenance task.

The catalog's `verifier.source_snapshot` records selection-time SHA-256 for ten
explicitly inspected source files on September 6, before the release integration
was complete. These are historical selection records, not final runtime hashes,
a whole-distribution manifest, or a verification of every historical task.
Keep this distinction after source edits or line-ending normalization; final
packaged bytes must be hashed separately.

The existing [topology source snapshot](../../verifier/runs/20260831_v3_fresh_100_topology/source_snapshot.json)
and [topology task index](../../verifier/runs/20260831_v3_fresh_100_topology/auditor_task_index_v3.json)
record source-task mappings and historical digests. The
[R1 selection manifest](../../verifier/runs/20260904_r1_r2_reviewer_response/r1_cross_vendor_audit/selection_manifest.json)
records source snapshots and drift history. These files are references, not
manifests regenerated or silently repaired by this task.

Two concrete historical-byte limitations are documented in the R1/R2 report.
The earlier naive instruction constant changed after its experiment; R2 therefore
pins the controls from executed tasks instead of trusting that current constant.
Later LF/CRLF normalization changed source-task hashes despite reported
content-equivalence checks, requiring an explicit drift log and rebaseline.
Neither current hashes nor report-linked YAML names erase those distinctions.