from __future__ import annotations

"""The pilot prototype, vendored into the site.

One state's synthetic sample records, deterministic truth checks,
entity tracing, and the validation gate, as demonstrated standalone
in the cms-pilot-demo project (which stays the offline laptop
version; keep the check logic in sync). Nothing here touches the
real payer corpus: the sample is invented, bannered as invented on
every page, and exists to show what the method does when CMS hands
it one state's records under a pilot.

Checks are rules a reviewer can state in one sentence. No models.
Flags are review signals, not findings.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data" / "demo"

# slug -> (state name, data file). Minnesota is the original sample and
# stays the default everywhere. Every state file is synthetic and is
# bannered as invented; the check logic does not change per state.
STATES = {
    "minnesota": ("Minnesota", "sample.json"),
    "new-york": ("New York", "new_york.json"),
    "florida": ("Florida", "florida.json"),
}
DEFAULT_STATE = "minnesota"

FLAG_TYPES = {
    "duplicative_billing": "Duplicative billing",
    "outside_scope": "Outside scope of practice",
    "rate_mismatch": "Specialist vs GP rate mismatch",
    "cash_also_billed": "Cash-pay service also billed",
    "ghost_enrollee": "Enrollee with no record history",
    "billed_after_death": "Billed after death",
    "stacked_prescribing": "Stacked or off-record prescribing",
}

# The glass box: every check stated in the open. rule is what the code
# compares, fires is the exact condition, clears is what a reviewer
# would need to see for the flag to go away. If a fact cannot clear a
# flag, the flag is wrong and the code is the thing to fix.
CHECK_GUIDE = {
    "duplicative_billing": {
        "rule": "Group claims by enrollee, code, and date, then look at who billed.",
        "fires": "The same enrollee, code, and date were billed by more than one billing entity.",
        "clears": "Evidence the entities delivered genuinely separate services that day, or one bill is a corrected void of the other.",
    },
    "outside_scope": {
        "rule": "Compare each claim's code against the billing provider's specialty scope map.",
        "fires": "The code is not in the scope list for that provider's specialty.",
        "clears": "A corrected specialty on the provider record, or documentation that the service sits inside that specialty's practice.",
    },
    "rate_mismatch": {
        "rule": "Compare what family medicine was paid for 99213 against the cardiology median for 99213 in the same sample, and against Medicare's national rate.",
        "fires": "A family medicine claim was paid at least twice the cardiology median for the same code.",
        "clears": "A corrected paid amount, or documentation that the higher payment prices a different service than the code states.",
    },
    "cash_also_billed": {
        "rule": "Match each enrollee's cash-pay record against their claims by code and date.",
        "fires": "The same code on the same date appears as paid in cash and as billed to a payer.",
        "clears": "Evidence the two records describe different services, or a refund of one of the two payments.",
    },
    "ghost_enrollee": {
        "rule": "Check whether an enrollee who was billed has any record at all: visits, immunizations, diagnoses.",
        "fires": "Claims exist in the enrollee's name and the record holds no visits, no immunizations, and no diagnoses.",
        "clears": "The person's actual record history, from any source the program trusts. If the person is real, the record joins and the flag dies.",
    },
    "billed_after_death": {
        "rule": "Compare each claim date against the enrollee's death date in the record.",
        "fires": "A claim is dated after the recorded date of death.",
        "clears": "A corrected death date, or evidence the service was delivered before death and only billed late with the right date of service.",
    },
    "stacked_prescribing": {
        "rule": "List each enrollee's overlapping GLP-1 prescriptions and who wrote and supplied them.",
        "fires": "More than one GLP-1 is active, from more than one prescriber, or with a cash, off-record source.",
        "clears": "One prescriber's reconciled medication list showing the overlap was deliberate, sequential, or already stopped.",
    },
}


def state_list() -> list[tuple[str, str]]:
    """(slug, state name) for every loaded state sample, in menu order."""
    return [(slug, name) for slug, (name, _f) in STATES.items()]


def load_sample(state: str = DEFAULT_STATE) -> dict:
    if state not in STATES:
        raise KeyError(f"unknown state sample: {state}")
    return json.loads((_DATA_DIR / STATES[state][1]).read_text())


def compute_flags(sample: dict) -> list[dict]:
    providers = {p["npi"]: p for p in sample["providers"]}
    scope = sample["scope"]
    claims = sample["claims"]
    flags: list[dict] = []

    def add(kind, severity, enrollee, npi, entity, dollars, evidence):
        flags.append({
            "id": f"F{len(flags) + 1:03d}", "type": kind, "label": FLAG_TYPES[kind],
            "severity": severity, "enrollee": enrollee, "npi": npi, "entity": entity,
            "dollars": round(dollars, 2), "evidence": evidence,
            "provider_name": providers.get(npi, {}).get("name", "unknown"),
            "specialty": providers.get(npi, {}).get("specialty", "unknown"),
        })

    by_key: dict[tuple, list] = defaultdict(list)
    for c in claims:
        by_key[(c["enrollee"], c["code"], c["date"])].append(c)
    for (pid, code, dt), group in sorted(by_key.items()):
        entities = {c["entity"] for c in group}
        if len(group) > 1 and len(entities) > 1:
            first = group[0]
            add("duplicative_billing", "high", pid, first["npi"], first["entity"],
                sum(c["paid"] for c in group),
                [f"{pid} was billed for {code} on {dt} by {len(entities)} different entities "
                 f"({', '.join(sorted(entities))}), ${sum(c['paid'] for c in group):,.0f} in total. "
                 "One encounter, more than one bill."])

    for c in claims:
        prov = providers.get(c["npi"])
        if prov and c["code"] not in scope.get(prov["specialty"], set()):
            add("outside_scope", "medium", c["enrollee"], c["npi"], c["entity"], c["paid"],
                [f"{prov['name']} ({prov['specialty']}) billed {c['code']} on {c['date']}. "
                 f"In this demo's scope map, {prov['specialty']} bills: "
                 f"{', '.join(sorted(scope.get(prov['specialty'], set())))}."])

    spec_paid = [c["paid"] for c in claims if c["code"] == "99213" and providers[c["npi"]]["specialty"] == "cardiology"]
    if spec_paid:
        spec_med = sorted(spec_paid)[len(spec_paid) // 2]
        for c in claims:
            if (c["code"] == "99213" and providers[c["npi"]]["specialty"] == "family medicine"
                    and c["paid"] >= 2 * spec_med):
                add("rate_mismatch", "medium", c["enrollee"], c["npi"], c["entity"], c["paid"],
                    [f"Family medicine was paid ${c['paid']:,.0f} for 99213 on {c['date']}; "
                     f"the cardiology median for the same code in this sample is ${spec_med:,.0f}, "
                     "and Medicare's national rate is $95.19. Same code, same state, "
                     "over three times the specialist price, from the lower-cost setting."])

    for e in sample["enrollees"]:
        for svc in e.get("cash_services", []):
            for c in claims:
                if c["enrollee"] == e["id"] and c["code"] == svc["code"] and c["date"] == svc["date"]:
                    add("cash_also_billed", "high", e["id"], c["npi"], c["entity"], c["paid"],
                        [f"The record shows {svc['code']} on {svc['date']} was {svc['note']} "
                         f"(${svc['amount']:,.0f} cash). The same service was then billed to "
                         f"{c['payer']} for ${c['paid']:,.0f}. Paid twice for one service."])

    billed_ids = {c["enrollee"] for c in claims}
    for e in sample["enrollees"]:
        total = sum(c["paid"] for c in claims if c["enrollee"] == e["id"])
        if e["id"] in billed_ids and e["visits"] == 0 and e["immunizations"] == 0 and not e["diagnoses"]:
            first_claim = next(c for c in claims if c["enrollee"] == e["id"])
            add("ghost_enrollee", "high", e["id"], first_claim["npi"], first_claim["entity"], total,
                [f"{e['id']} (age {e['age']}) has no visits, no immunizations, and no diagnoses "
                 f"anywhere in the record, yet ${total:,.0f} was billed in their name. "
                 "Either the record is missing a person, or the person is missing entirely."])
        if e.get("death_date"):
            for c in claims:
                if c["enrollee"] == e["id"] and c["date"] > e["death_date"]:
                    add("billed_after_death", "high", e["id"], c["npi"], c["entity"], c["paid"],
                        [f"{e['id']} died on {e['death_date']} in the record. "
                         f"A claim was billed on {c['date']}, after the death, for ${c['paid']:,.0f}."])

    for e in sample["enrollees"]:
        glp1 = [r for r in e.get("prescriptions", []) if "GLP-1" in r["drug"]]
        sources = {r["source"] for r in glp1}
        prescribers = {r["prescriber"] for r in glp1}
        if len(glp1) > 1 and (len(prescribers) > 1 or any("cash" in s for s in sources)):
            add("stacked_prescribing", "medium", e["id"],
                glp1[0]["prescriber"], "E08", 240,
                [f"{e['id']} holds {len(glp1)} overlapping GLP-1 prescriptions from "
                 f"{len(prescribers)} prescribers; sources: {', '.join(sorted(sources))}. "
                 "Stacked incretins raise adverse-event risk and usually mean nobody owns the whole list."])

    rank = {"high": 0, "medium": 1, "low": 2}
    flags.sort(key=lambda f: (rank[f["severity"]], f["type"], f["enrollee"]))
    for i, f in enumerate(flags, 1):
        f["id"] = f"F{i:03d}"
    return flags


def gate_score(enrollee: dict, claims: list[dict]) -> dict:
    """Validation gate, out of 10, scored in the open.

    Housing status is context for outreach and is never scored:
    being displaced or sheltered is a circumstance, not a suspicion.
    """
    mine = [c for c in claims if c["enrollee"] == enrollee["id"]]
    identity = (2 if enrollee["visits"] > 0 else 0) + (1 if enrollee["immunizations"] > 0 else 0) + (1 if enrollee["diagnoses"] else 0)
    billed_codes = {c["code"] for c in mine}
    condition = 3 if (enrollee["diagnoses"] and billed_codes) else (2 if enrollee["diagnoses"] else 0)
    months = {c["date"][:7] for c in mine}
    continuity = 3 if len(months) >= 3 else (2 if len(months) == 2 else (1 if months else 0))
    total = identity + condition + continuity
    return {
        "score": total, "of": 10,
        "identity_evidence": identity, "condition_evidence": condition, "continuity": continuity,
        "flagged": total < 8,
        "housing_context": enrollee.get("housing", "unknown"),
        "note": "Housing status is context for outreach. It is never scored.",
    }


def entity_trace(sample: dict, flags: list[dict], entity_id: str) -> dict:
    entities = {e["id"]: e for e in sample["entities"]}
    ent = entities[entity_id]
    siblings = []
    for other in sample["entities"]:
        if other["id"] == entity_id:
            continue
        ties = []
        if ent.get("parent") and other.get("parent") == ent["parent"]:
            ties.append(f"same parent: {ent['parent']}")
        if other["address"] == ent["address"]:
            ties.append("same address")
        if other["owner"] == ent["owner"]:
            ties.append(f"same owner: {ent['owner']}")
        if other["agent"] == ent["agent"]:
            ties.append(f"same registered agent: {ent['agent']}")
        if ties:
            siblings.append({**other, "ties": ties})
    web_ids = {entity_id} | {s["id"] for s in siblings}
    web_flags = [f for f in flags if f["entity"] in web_ids]
    return {
        "entity": ent,
        "parent": ent.get("parent"),
        "siblings": siblings,
        "providers": [p for p in sample["providers"] if entity_id in p["entities"]],
        "multi_entity_providers": [p for p in sample["providers"] if len(p["entities"]) > 1 and entity_id in p["entities"]],
        "flags_here": [f for f in flags if f["entity"] == entity_id],
        "flags_in_web": web_flags,
        "web_flagged_dollars": round(sum(f["dollars"] for f in web_flags), 2),
    }


def state_summary(sample: dict, flags: list[dict]) -> dict:
    claims = sample["claims"]
    by_type = Counter(f["type"] for f in flags)
    gates = {e["id"]: gate_score(e, claims) for e in sample["enrollees"]}
    return {
        "state": sample["state"],
        "note": sample["note"],
        "enrollees": len(sample["enrollees"]),
        "claims": len(claims),
        "claims_dollars": round(sum(c["paid"] for c in claims), 2),
        "flags": len(flags),
        "flagged_dollars": round(sum(f["dollars"] for f in flags), 2),
        "flags_by_type": {k: by_type.get(k, 0) for k in FLAG_TYPES},
        "gate_flagged": sum(1 for g in gates.values() if g["flagged"]),
        "entities": len(sample["entities"]),
    }
