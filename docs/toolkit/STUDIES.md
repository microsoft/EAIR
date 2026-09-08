# Run the Five Paper Worlds

## Presets and Smoke Runs

```console
eair list
eair info A1
eair config A1 --kind recommended --index 1 --out study.yaml
```

`config` prints an installed resource path when `--out` is omitted. When copying,
it preserves original bytes and never overwrites a file. Indices are one-based;
`info` shows ordered `recommended_configs` and `supplemental_configs`. Smoke
configurations test runtime compatibility, not historical study reproduction.

```console
enterprise-risk authority_bias --runs-dir runs/a1-smoke
enterprise-risk semantic_drift --runs-dir runs/b1-smoke
enterprise-risk kpi_gaming --runs-dir runs/c1-smoke
enterprise-risk d1 --runs-dir runs/d1-smoke
enterprise-risk f1 --runs-dir runs/f1-smoke
```

The `enterprise-risk` wrapper retains the five original runtime implementations
and forwards additional flags. Its default is the world's smoke config. Use an
explicit copied `--config` to avoid a same-named local configuration taking
precedence. Inspect a runner's `--help` before starting paid model runs.
All five shipped smoke configurations set `use_mock: true`. This is not a
universal `--dry-run` flag: individual historical runners accept different flags.

## A1: Authority Bias

The primary selected protocol is `realistic_organizational_power_v4`, with
ABCD conditions. The second recommended config is the distinct
`organizational_power_factorial_v5` EFGH pilot. Both use the title-effect runner:

```console
eair config A1 --index 1 --out authority-abcd.yaml
python -m run_authority_title_effect --config authority-abcd.yaml --dry-run --out runs/a1-study-smoke
```

Remove `--dry-run` only after reviewing model/provider configuration and budget.
Each selected YAML supplies individual model settings; historical cross-model
coverage needs explicit model overrides/orchestration. The ordinary
`enterprise-risk authority_bias` entry point is not a replacement for this
study runner.

The supplemental August 20 fresh20 YAML records a post-mitigation batch design.
Its isolated repaired source and replacement-seed execution schedule are not
reproduced by merely running that YAML against the unmodified toolkit. It is
retained as provenance, not advertised as an independently reproducible repair.

## B1: Semantic Drift

Export both recommended configs. The second contains Kimi K2.5, which replaces
DeepSeek V4 Pro in the reported ten-model cohort. Do not treat it as an eleventh
model. Use the existing `run_drift` runtime and `judge_drift` split-rubric judge.

```console
eair config B1 --index 1 --out drift-original.yaml
eair config B1 --index 2 --out drift-replacement.yaml
python -m run_drift --help
python -m judge_drift --help
```

The report's 150 valid episodes select valid original-model runs plus the
replacement cohort. Concatenating all original and replacement results changes
the reported study. Distinguish decision-status drift, submission-status drift,
and the final email actually sent.

## C1: KPI Gaming

The selected V2 configuration contains none/mild/strong, planning 99 episodes.
The latest report uses only mild/strong after first-success deduplication by
model, pressure level, and seed: 66 episodes. Preserve the none rows if running
the original source design; do not present all 99 as the reported comparison.

```console
eair config C1 --out kpi-v2.yaml
python -m run --help
python -m judge_kpi --help
```

Strong changes multiple runtime elements, not just prompt wording. Failed tool
execution is not evidence of a safe policy. Historical analysis scripts and
raw result datasets are provenance references, not bundled experiment outputs.

## D1: Confused Deputy

Both configs are needed for the latest L6 three-domain coverage:

```console
eair config D1 --index 1 --out d1-hr.yaml
eair config D1 --index 2 --out d1-finance-security.yaml
python -m run_d1 --help
python -m judge_d1 --help
```

HR contributes 30 episodes and Finance/Security 60. This is the prompt-neutral
L6 inquiry setup, not the older non-L6 cross-domain protocol. Having an inquiry
tool does not enforce authorization propagation or field-level access control.

## F1: Provenance Paradox

The complete historical workflow binds 90 solo-calibration reviews to 270 main
episodes. The main config requires compatible solo capability data.

```console
eair config F1 --out f1-main.yaml
eair config F1 --kind supplemental --out f1-calibration.yaml
python -m run_f1_paper_study --help
```

After reviewing cost and credentials, the full paid study command is:

```console
python -m run_f1_paper_study --main-config f1-main.yaml --calibration-config f1-calibration.yaml --run-root runs/f1-study --max-workers 1
```

This runs calibration, main trajectories, judging, and analysis. Status is
written to `runs/f1-study/RUN_STATUS.md`, not the Python installation directory.
The ordinary F1 smoke does not reproduce calibration-dependent regret metrics.

The August 21 mitigation analysis is a separate high-risk-contract follow-up.
All 20 episodes escalated and produced a final verdict; no safe-to-sign positive
control was evaluated. It does not establish automatic-signing utility or a
complete replay of the four original failing cases.

Full report references and snapshot limits are in [PROVENANCE.md](PROVENANCE.md).