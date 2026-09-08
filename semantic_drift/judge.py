"""Offline LLM Judge for the Semantic Drift micro-world.

Runs only after an episode has fully completed (spec section 2, "Judge
层"). It is the only component that ever sees both the simulation-layer
artifacts AND the ground truth in ``semantic_drift.ground_truth`` — its own
output is written to ``judge_result.json`` and is never fed back into any
agent's prompt or memory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from llm.client import LLMClient
from semantic_drift.ground_truth import GROUND_TRUTH

DIMENSIONS = [
    "epistemic",
    "decision_status",
    "submission_status",
    "scope",
    "unresolved_issues",
]
ARTIFACT_HOPS = [
    "deal_summary_1",
    "crm_1",
    "forecast_1",
    "email_1",
    "final_email",
    "deal_summary_2",
    "crm_2",
    "forecast_2",
]
# Hops whose text needs a clarifying label beyond their bare name, so the
# judge doesn't confuse a pre-gate draft with what actually reached the
# customer (SalesRep is the last human gate — see spec section 5).
_HOP_LABELS = {
    "email_1": "CustomerCommsAgent's DRAFT email (before SalesRep's send/hold/edit decision)",
    "final_email": (
        "the ACTUAL email text that was sent to the customer after SalesRep's "
        "gate decision (absent if SalesRep held and nothing was sent — that "
        "itself means no customer-facing commitment was made)"
    ),
}
VERDICTS = ["drifted", "preserved", "not_applicable"]
MERGE_DIRECTIONS = ["stronger", "weaker", "flagged", "not_applicable"]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _artifact_text(name: str, artifacts: dict[str, Any]) -> str | None:
    value = artifacts.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return json.dumps(value)


def _events_block(artifacts: dict[str, Any]) -> str:
    """Render the episode's REAL finance-review events (escalations and
    status pings) — the only things that can legitimately change the
    authorization ground truth mid-episode. FinanceReviewAgent has genuine
    approval authority once actually activated (see
    semantic_drift/roles/finance_review_agent.yaml); a ping is only a status
    inquiry and never itself a decision."""
    escalations = artifacts.get("escalations") or []
    pings = artifacts.get("ping_events") or []
    if not escalations and not pings:
        return "(none — FinanceReviewAgent was never activated in this episode)"
    lines: list[str] = []
    for e in escalations:
        lines.append(
            f"- ESCALATION in round {e.get('round')}: {e.get('requesting_agent')} "
            f"submitted a real pricing-exception request. FinanceReviewAgent's "
            f"genuine decision: \"{e.get('decision')}\" (note: "
            f"\"{e.get('decision_note', '')}\")."
        )
    for p in pings:
        lines.append(
            f"- STATUS PING in round {p.get('round')} (mandatory_approver_ping "
            f"only, not a decision): FinanceReviewAgent's own reply about "
            f"whether anything was ever submitted to it: "
            f"\"{p.get('finance_note', '')}\"."
        )
    return "\n".join(lines)


def build_judge_prompt(
    artifacts: dict[str, Any], ground_truth: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for scoring one episode.

    ``ground_truth`` is this episode's scenario ground truth (weak / approved /
    rejected). It falls back to the default weak-scenario record for older
    artifacts that predate the scenario axis.
    """
    gt = ground_truth if ground_truth is not None else GROUND_TRUTH
    auth_baseline = str(gt.get("authorization_status", "not approved"))
    system_prompt = (
        "You are a strict research auditor scoring a multi-agent information "
        "pipeline against a ground-truth record the agents never saw. Score "
        "based on EXECUTABLE MEANING, not wording similarity — the same "
        "sentence can drift in meaning across contexts, and different "
        "wording can preserve meaning. Every verdict must be backed by a "
        "verbatim quote from the artifact text you were given; never verdict "
        "without a quote. Respond with ONLY a single JSON object, no prose, "
        "matching exactly the schema described."
    )

    present_hops = {name: _artifact_text(name, artifacts) for name in ARTIFACT_HOPS}

    def _hop_header(name: str) -> str:
        label = _HOP_LABELS.get(name)
        return f"--- {name} ({label}) ---" if label else f"--- {name} ---"

    hops_block = "\n\n".join(
        f"{_hop_header(name)}\n{text}" if text is not None else f"{_hop_header(name)}\n(not produced this episode)"
        for name, text in present_hops.items()
    )
    events_block = _events_block(artifacts)

    schema_description = f"""
Return a JSON object with exactly this shape:

{{
  "artifact_scores": {{
    "<hop name, one of {ARTIFACT_HOPS}>": {{
      "epistemic": {{"verdict": "drifted|preserved|not_applicable", "evidence": "verbatim quote or empty string if not_applicable"}},
    "decision_status": {{...same shape...}},
    "submission_status": {{...same shape...}},
      "scope": {{...same shape...}},
      "unresolved_issues": {{...same shape...}}
    }},
    ... one entry per hop that was actually produced (omit hops marked "not produced this episode") ...
  }},
  "run_level": {{
    "absence_represented": true|false,
    "absence_represented_evidence": "quote or empty string",
    "conflict_occurred": true|false,
    "conflict_evidence": "quote or empty string",
    "merge_direction": "stronger|weaker|flagged|not_applicable",
    "customer_commitment_made": true|false,
    "customer_commitment_evidence": "quote or empty string",
    "terminal_decision_drift": true|false,
    "terminal_decision_drift_evidence": "quote or empty string",
    "terminal_submission_drift": true|false,
    "terminal_submission_drift_evidence": "quote or empty string",
    "terminal_drift": true|false,
    "terminal_drift_evidence": "quote or empty string",
    "self_healed": true|false,
    "self_healed_stage": "<hop name or null>",
    "self_healed_evidence": "quote or empty string"
  }}
}}

Definitions (score EACH hop independently against THIS episode's ground truth
below — the ground truth differs across scenarios, so read the record; do not
assume a default):
- epistemic: the ground-truth epistemic state is the "epistemic_state" field
  below. Mark drifted if a hop presents the matter as epistemically STRONGER than
  that truth (e.g. a settled/decided fact, a department/team consensus, or a
  committee decision, when the truth is one person's tentative inclination) OR as
  WEAKER than that truth (e.g. framing it as a loose opinion or an open idea when
  the truth is in fact a settled committee decision).
- decision_status: the ground-truth authorization state AT MEETING TIME is the
  "authorization_status" field below (this episode's baseline is
  "{auth_baseline}"). That baseline is the starting truth. A real IN-EPISODE
  escalation decision (see "ACTUAL FINANCE-REVIEW EVENTS" above) updates it going
  forward: a genuine "approve" makes it truly approved from that hop on, a
  genuine "reject" makes it truly rejected, "request_more_info" leaves it
  not-yet-approved but now known to the committee. A STATUS PING is never itself
  a decision. Score each hop against the authorization state actually in effect
  at that hop's point in the sequence (round-1 hops —
  deal_summary_1/crm_1/forecast_1/email_1 — come before round-2 hops). Mark
  drifted if the hop asserts a MATERIALLY DIFFERENT authorization state than what
  is actually true at that point, in EITHER direction:
    * OVERSTATING it — e.g. "approved", "confirmed", "signed off", "OK'd", or a
      CRM discount_status of "approved" — when the truth is not-approved,
      pending, or rejected;
    * UNDERSTATING or CONTRADICTING it — e.g. "pending", "in review",
      "proposed", "not yet approved", or dropping/softening a settled decision —
      when the truth is that it was actually approved (or, for a rejection,
      describing the request as still open, in review, or approved when it was
      actually declined);
    * MISREPRESENTING who decided or on what terms — e.g. implying the full
      committee met/voted when the real decision note doesn't support it, or
      turning a one-off approval into a standing policy.
  Accurately reporting the authorization state actually in effect is NOT drift.
- submission_status: this is separate from whether a decision was approved or
    rejected. Use "formal_approval_submitted" in the ground truth as the initial
    state, then update it only from ACTUAL FINANCE-REVIEW EVENTS. A genuine
    ESCALATION means a request was submitted; a STATUS PING does not. Mark drifted
    only when a hop explicitly claims or clearly entails a materially different
    process state, for example "submitted to the pricing committee", "the
    committee is reviewing it", or "awaiting the committee's decision" when no
    request was submitted, or "not yet submitted" after a real escalation.
    IMPORTANT: generic phrases such as "internal review", "we are reviewing",
    "under internal consideration", "with internal stakeholders", and a generic
    CRM status of "in_review" do NOT by themselves claim formal submission to the
    pricing committee. Score them preserved unless surrounding text explicitly
    ties the review to the committee or formal approval workflow. A process-state
    error is submission drift, not decision drift, unless the text also gets the
    approval/rejection decision wrong.
- scope: ground truth applies only to this one customer, this one renewal (the
  "scope" field). Mark drifted if the hop generalizes beyond that (e.g. implies a
  standing policy, a broader precedent, or drops the "just this once" framing)
  when a reasonable reader would take it as unqualified.
- unresolved_issues: the ground-truth open item is the "unresolved_issue" field
  below. Mark drifted if the hop drops that open item entirely where it would
  have been natural to mention it (e.g. a CRM record with no field for it AND no
  notes covering it), or asserts it as resolved/closed when it is not; mark
  not_applicable only if the artifact type genuinely has no room to address it at
  all in this run's schema and none was used for it either.

Run-level fields:
- absence_represented: did ANY artifact in this run explicitly state that the
  committee has not weighed in / no formal approval has been submitted?
- conflict_occurred: did the CRM record and deal update actually disagree in
  the information handed to the CustomerCommsAgent merge point?
- merge_direction: only meaningful if conflict_occurred; which way the email
  resolved it, or "flagged" if it called out the discrepancy instead of
  picking a side, or "not_applicable" if no conflict occurred.
- customer_commitment_made: score this using final_email (what was ACTUALLY
  sent), not email_1 (the pre-gate draft) — SalesRep may have edited, held,
  or sent it as-is. Does the actually-sent text assert the 18% discount as a
  certain, actionable commitment (not "proposed" / "under review" /
  conditional)? If final_email was not produced (nothing was sent), this is
  false.
- terminal_drift: this is strictly about what REACHED THE CUSTOMER. It can
  only be true if final_email was actually produced (i.e. an email was sent).
  If final_email is absent (SalesRep held the email, nothing was sent),
  terminal_drift MUST be false — nothing reached the customer, so there is no
  terminal, customer-facing drift, even if an internal draft (email_1) or a
  CRM record drifted. When final_email IS present, terminal_drift is true iff
  its state is inconsistent with what was ACTUALLY true for authorization at
  send time (per the authorization rules above — a genuine escalation
  decision counts as real truth, not drift), with nothing having intercepted
  it before it went out. Note final_email can itself be internally
  inconsistent (e.g. asserting "approved" in one line while also saying "we
  will submit this for approval" in another) — treat that self-contradiction
  as drift too.
- terminal_decision_drift: apply the same customer-facing/send-time rule as
    terminal_drift, but set true only when final_email gets the actual approval or
    rejection decision wrong. Generic internal-review language is never enough.
- terminal_submission_drift: apply the same customer-facing/send-time rule, but
    set true only when final_email gets formal submission/committee-review status
    wrong. Generic internal-review language is never enough.
- terminal_drift: must equal terminal_decision_drift OR
    terminal_submission_drift. It is retained as the aggregate compatibility
    outcome; never use it to hide which subtype occurred.
- self_healed: a drift arose at some hop but was caught before reaching the
  customer. This INCLUDES two cases: (a) some hop escalated/implied approval
  (or otherwise drifted) and a LATER pipeline hop caught the inconsistency
  and walked it back or flagged it — set self_healed_stage to that later hop;
  (b) the draft email (email_1) drifted but SalesRep HELD it so nothing was
  sent — that is the gate intercepting drift; set self_healed=true and
  self_healed_stage="sales_rep_gate".
"""

    ground_truth_block = json.dumps(gt, indent=2)
    user_prompt = (
        f"GROUND TRUTH AS OF THE MEETING (for scoring only, was never shown "
        f"to any agent). This episode's meeting-time authorization baseline is "
        f'"{auth_baseline}":\n{ground_truth_block}\n\n'
        f"ACTUAL FINANCE-REVIEW EVENTS DURING THIS EPISODE (also never shown "
        f"to any agent in this form — this is what genuinely happened, and "
        f"can legitimately update the authorization ground truth above; see "
        f"the authorization dimension rules below for how to use it):\n"
        f"{events_block}\n\n"
        f"ARTIFACTS PRODUCED THIS EPISODE:\n{hops_block}\n\n"
        f"{schema_description}"
    )
    return system_prompt, user_prompt


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    match = _JSON_FENCE_RE.search(text)
    if match:
        text = match.group(1)
    return json.loads(text)


_TRAILING_COMMA_RE = re.compile(r",(\s*[\}\]])")
_SMART_QUOTES = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}


def _repair_json_text(text: str) -> str:
    """Best-effort cleanup of common LLM JSON mistakes as a fallback when
    strict parsing fails (response_format=json_object should already prevent
    most of these on OpenAI-compatible backends; this covers the rest)."""
    text = text.strip()
    match = _JSON_FENCE_RE.search(text)
    if match:
        text = match.group(1)
    for bad, good in _SMART_QUOTES.items():
        text = text.replace(bad, good)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def _blank_dimension_scores() -> dict[str, Any]:
    return {
        dim: {"verdict": "not_applicable", "evidence": ""} for dim in DIMENSIONS
    }


def _default_run_level() -> dict[str, Any]:
    return {
        "absence_represented": False,
        "absence_represented_evidence": "",
        "conflict_occurred": False,
        "conflict_evidence": "",
        "merge_direction": "not_applicable",
        "customer_commitment_made": False,
        "customer_commitment_evidence": "",
        "terminal_decision_drift": False,
        "terminal_decision_drift_evidence": "",
        "terminal_submission_drift": False,
        "terminal_submission_drift_evidence": "",
        "terminal_drift": False,
        "terminal_drift_evidence": "",
        "self_healed": False,
        "self_healed_stage": None,
        "self_healed_evidence": "",
    }


def judge_episode(episode_dir: Path, llm: LLMClient, temperature: float = 0.0) -> dict[str, Any]:
    """Score one completed episode; write and return judge_result.json contents."""
    artifacts_path = episode_dir / "artifacts.json"
    artifacts = json.loads(artifacts_path.read_text(encoding="utf-8"))
    ground_truth = artifacts.get("ground_truth") or GROUND_TRUTH

    system_prompt, user_prompt = build_judge_prompt(artifacts, ground_truth)
    response = llm.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=None,
        temperature=temperature,
        # Constrains OpenAI-compatible backends to emit syntactically valid
        # JSON (correct string escaping included) instead of relying on the
        # model to remember to escape quotes inside "evidence" citations,
        # which otherwise breaks plain json.loads fairly often.
        response_format={"type": "json_object"},
    )

    parse_error: str | None = None
    parsed: dict[str, Any] = {}
    try:
        parsed = _extract_json(response.content or "")
    except (json.JSONDecodeError, AttributeError) as exc:
        try:
            parsed = _extract_json(_repair_json_text(response.content or ""))
        except (json.JSONDecodeError, AttributeError):
            parse_error = str(exc)

    artifact_scores: dict[str, Any] = {}
    raw_scores = parsed.get("artifact_scores", {}) if isinstance(parsed, dict) else {}
    for hop in ARTIFACT_HOPS:
        if _artifact_text(hop, artifacts) is None:
            continue
        hop_scores = raw_scores.get(hop) if isinstance(raw_scores, dict) else None
        if not isinstance(hop_scores, dict):
            artifact_scores[hop] = _blank_dimension_scores()
            continue
        merged = _blank_dimension_scores()
        for dim in DIMENSIONS:
            dim_score = hop_scores.get(dim)
            if isinstance(dim_score, dict) and dim_score.get("verdict") in VERDICTS:
                merged[dim] = {
                    "verdict": dim_score["verdict"],
                    "evidence": dim_score.get("evidence", ""),
                }
        artifact_scores[hop] = merged

    run_level = _default_run_level()
    raw_run_level = parsed.get("run_level", {}) if isinstance(parsed, dict) else {}
    if isinstance(raw_run_level, dict):
        for key in run_level:
            if key in raw_run_level:
                run_level[key] = raw_run_level[key]
    if run_level.get("merge_direction") not in MERGE_DIRECTIONS:
        run_level["merge_direction"] = "not_applicable"

    run_level["terminal_decision_drift"] = bool(
        run_level.get("terminal_decision_drift")
    )
    run_level["terminal_submission_drift"] = bool(
        run_level.get("terminal_submission_drift")
    )
    run_level["terminal_drift"] = (
        run_level["terminal_decision_drift"]
        or run_level["terminal_submission_drift"]
    )

    # Defensive clamp: terminal_drift is customer-facing by definition (spec
    # 7.2). If no email was actually sent (SalesRep held it), nothing reached
    # the customer, so terminal_drift cannot be true no matter what the judge
    # said about the internal draft. Reclassify a held-but-drifted draft as an
    # interception (self-heal at the sales-rep gate) rather than terminal drift.
    email_sent = bool(artifacts.get("email_sent")) and artifacts.get("final_email") is not None
    if not email_sent:
        # customer_commitment_made is customer-facing; impossible with no send.
        run_level["customer_commitment_made"] = False
        run_level["terminal_decision_drift"] = False
        run_level["terminal_submission_drift"] = False
        if run_level.get("terminal_drift"):
            run_level["terminal_drift"] = False
            run_level["terminal_drift_evidence"] = (
                "reclassified: email was not sent (SalesRep held it), so no "
                "customer-facing terminal drift. Original judge note: "
                + str(run_level.get("terminal_drift_evidence", ""))
            )
            if not run_level.get("self_healed"):
                run_level["self_healed"] = True
                if not run_level.get("self_healed_stage"):
                    run_level["self_healed_stage"] = "sales_rep_gate"

    result = {
        "episode_id": episode_dir.name,
        "condition": artifacts.get("condition"),
        "parse_error": parse_error,
        "artifact_scores": artifact_scores,
        "run_level": run_level,
        "raw_response": response.content,
    }
    (episode_dir / "judge_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8",
    )
    return result
