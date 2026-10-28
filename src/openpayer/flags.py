from __future__ import annotations

"""Fraud, waste, and abuse review flags over filed rates.

These functions look at rates payers published in their Transparency in
Coverage files, lined up against the Medicare Physician Fee Schedule
(reference.py), and against the other payers in the corpus. They emit
flags for human review.

A flag is not a finding. Filed rates are contracted amounts as
published; they are not claims, and nothing here shows what anyone was
paid. A rate far from Medicare can be a legitimate contract. What a
flag says is narrower: this pattern is unusual enough, against a
federal benchmark or against every other payer in the corpus, that a
reviewer should look at the underlying file first. Every flag carries
its counts and the Medicare rate it was measured against, so the
reviewer can reproduce it from the primary sources.

Signals (thresholds are named constants, changed only in the open):
- placeholder_rates: a large share of a payer's rates for a code are
  $1.00 or less, including $0. Real negotiated schedules rarely price
  a service at a dollar; a block of them reads as filler in the file.
- median_far_above_medicare: the payer's median negotiated rate for a
  code is at least MEDIAN_MULTIPLE times the Medicare rate.
- extreme_rates: individual negotiated rates at least EXTREME_MULTIPLE
  times Medicare, in numbers too large to be one typo.
- single_amount_many_groups: one identical dollar amount covers at
  least FLAT_MIN_GROUPS distinct provider groups and nearly all of a
  payer's rates for a code, which reads as a default, not negotiation.
- code_not_published: a payer publishes nothing for a code that at
  least two other payers publish. Transparency rules require the file;
  a missing code is a compliance gap worth a question.
"""

from collections import Counter, defaultdict

from . import reference

PLACEHOLDER_MAX = 1.00
PLACEHOLDER_MIN_N = 20
PLACEHOLDER_SHARE = 0.20
MEDIAN_MULTIPLE = 4.0
EXTREME_MULTIPLE = 10.0
EXTREME_MIN_N = 3
FLAT_MIN_GROUPS = 50
FLAT_SHARE = 0.90

FLAG_NOTE = (
    "Flag for review only. Filed rates are contracted amounts as published in payer "
    "transparency files, not claims or payments. A flag marks a pattern that is unusual "
    "against the Medicare fee schedule or against peer payers; it is not a finding of "
    "fraud, waste, or abuse."
)

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def compute_flags(rates: list[dict]) -> list[dict]:
    """Compute review flags from rate rows.

    Each rate row needs payer, billing_code, negotiated_type,
    negotiated_rate, tin. Rows without a dollar rate are ignored.
    Returns flags sorted by severity, then payer, then code.
    """
    rows = [
        r
        for r in rates
        if r.get("negotiated_rate") is not None and str(r.get("negotiated_type")) != "percentage"
    ]
    flags: list[dict] = []

    def add(kind: str, severity: str, payer: str, code: str, evidence: dict) -> None:
        flags.append(
            {
                "kind": kind,
                "severity": severity,
                "payer": payer,
                "billing_code": code,
                "evidence": evidence,
                "medicare_rate": reference.medicare_rate(code),
                "note": FLAG_NOTE,
            }
        )

    by_pc: dict[tuple[str, str], list[dict]] = defaultdict(list)
    payers_by_code: dict[str, set] = defaultdict(set)
    all_payers: set[str] = set()
    for r in rows:
        by_pc[(str(r["payer"]), str(r["billing_code"]))].append(r)
        payers_by_code[str(r["billing_code"])].add(str(r["payer"]))
        all_payers.add(str(r["payer"]))

    for (payer, code), group in sorted(by_pc.items()):
        vals = [float(r["negotiated_rate"]) for r in group]
        n = len(vals)
        med_rate = reference.medicare_rate(code)

        cheap = sum(1 for v in vals if v <= PLACEHOLDER_MAX)
        if n >= PLACEHOLDER_MIN_N and cheap / n >= PLACEHOLDER_SHARE:
            add(
                "placeholder_rates",
                "medium",
                payer,
                code,
                {"n_rates": n, "n_at_or_below_1_dollar": cheap, "share": round(cheap / n, 3)},
            )

        negotiated = sorted(float(r["negotiated_rate"]) for r in group if str(r["negotiated_type"]) == "negotiated")
        if med_rate and negotiated:
            median = negotiated[len(negotiated) // 2] if len(negotiated) % 2 else (
                negotiated[len(negotiated) // 2 - 1] + negotiated[len(negotiated) // 2]
            ) / 2
            if median >= MEDIAN_MULTIPLE * med_rate:
                add(
                    "median_far_above_medicare",
                    "high",
                    payer,
                    code,
                    {
                        "n_negotiated": len(negotiated),
                        "median_rate": round(median, 2),
                        "median_percent_of_medicare": round(median / med_rate * 100),
                    },
                )
            extreme = sum(1 for v in negotiated if v >= EXTREME_MULTIPLE * med_rate)
            if extreme >= EXTREME_MIN_N:
                add(
                    "extreme_rates",
                    "high",
                    payer,
                    code,
                    {
                        "n_negotiated": len(negotiated),
                        "n_at_or_above_10x_medicare": extreme,
                        "max_rate": round(max(negotiated), 2),
                        "max_percent_of_medicare": round(max(negotiated) / med_rate * 100),
                    },
                )

        by_amount: dict[float, set] = defaultdict(set)
        counts: Counter = Counter()
        for r in group:
            by_amount[float(r["negotiated_rate"])].add(str(r.get("tin") or ""))
            counts[float(r["negotiated_rate"])] += 1
        top_amount, top_n = counts.most_common(1)[0]
        top_groups = len(by_amount[top_amount] - {""})
        if top_groups >= FLAT_MIN_GROUPS and top_n / n >= FLAT_SHARE:
            add(
                "single_amount_many_groups",
                "medium",
                payer,
                code,
                {
                    "n_rates": n,
                    "amount": top_amount,
                    "provider_groups_at_amount": top_groups,
                    "share": round(top_n / n, 3),
                },
            )

    for code, have in sorted(payers_by_code.items()):
        if len(have) >= 2:
            for payer in sorted(all_payers - have):
                add(
                    "code_not_published",
                    "low",
                    payer,
                    code,
                    {"payers_publishing_code": len(have), "n_rates": 0},
                )

    flags.sort(key=lambda f: (_SEVERITY_RANK[f["severity"]], f["payer"], f["billing_code"], f["kind"]))
    return flags
