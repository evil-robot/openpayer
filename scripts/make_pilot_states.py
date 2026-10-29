#!/usr/bin/env python3
"""Generate the synthetic state demo datasets for the pilot prototype.

Minnesota, New York, and Florida samples. Every person, provider,
entity, NPI, and dollar is invented for demonstration. No real
patient, provider, or claim appears anywhere. Anomalies are planted
deliberately, one per flag type, so each demo has known right answers
the tests can assert. Each state has its own fixed seed, counties,
cities, entity names, and provider names; the planted cases and the
check logic are the same, which is the point: give the engine another
state's records and it runs the same way.

Run: python3 scripts/make_pilot_states.py
Writes src/openpayer/data/demo/{sample,new_york,florida}.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "openpayer" / "data" / "demo"

CODES = {
    "99213": "office visit, established patient",
    "99446": "interprofessional consult, short",
    "99447": "interprofessional consult",
    "99448": "interprofessional consult, longer",
    "99449": "interprofessional consult, longest",
    "99451": "electronic consult, brief",
    "99452": "electronic consult, requesting side",
    "G2212": "prolonged office visit add-on",
    "11042": "wound debridement, first lesion",
    "97597": "wound care, selective debridement",
}

# What each specialty may plausibly bill in this demo world.
SCOPE = {
    "podiatry": {"99213", "11042", "97597"},
    "family medicine": {"99213", "99446", "99447", "99451", "99452", "G2212"},
    "cardiology": {"99213", "99446", "99447", "99448", "99449", "G2212"},
    "wound care": {"99213", "11042", "97597", "99451"},
    "telehealth": {"99213", "99451", "99452"},
    "hospice": {"99213", "99447"},
    "nurse practitioner": {"99213", "99446", "99451", "G2212"},
}

DIAGNOSES = ["hypertension", "type 2 diabetes", "heart failure", "COPD", "chronic wound", "autism spectrum", "osteoarthritis", "depression"]

# Entity roles are fixed across states (E01 family medicine ... E06 the
# DME arm of the planted ownership web); names and places are per state.
_ENTITY_KINDS = ["clinic", "clinic", "clinic", "home health", "hospice", "DME supplier", "laboratory", "telehealth", "wound care", "behavioral"]
_PROVIDER_ROLES = [
    ("family medicine", ["E01"]), ("family medicine", ["E01"]),
    ("cardiology", ["E02"]), ("cardiology", ["E02"]),
    ("podiatry", ["E03"]), ("podiatry", ["E03"]),
    ("hospice", ["E04", "E05"]), ("nurse practitioner", ["E04", "E06"]),
    ("wound care", ["E09"]), ("telehealth", ["E08"]),
    ("family medicine", ["E01", "E08"]), ("nurse practitioner", ["E10"]),
]

STATES = {
    "sample": {
        "state": "Minnesota", "seed": 20261028, "generated": "2026-10-28", "tin_prefix": "41",
        "counties": ["Hennepin", "Ramsey", "Dakota", "St. Louis", "Olmsted", "Anoka", "Stearns"],
        "ghost_county": "Ramsey",
        "entities": [
            ("Lakeside Family Medicine LLC", "Duluth", None, "M. Okafor", "North Registered Agents", "1200 London Rd, Duluth, MN"),
            ("Twin Cities Cardiology Associates LLC", "Minneapolis", None, "S. Feld", "North Registered Agents", "800 Nicollet Mall, Minneapolis, MN"),
            ("Prairie Podiatry Group PLLC", "Rochester", None, "J. Lindqvist", "Prairie Filing Co", "55 2nd St SW, Rochester, MN"),
            ("NorthStar Home Health LLC", "St. Paul", "NorthStar Care Holdings LLC", "D. Keller", "Capitol Agents Inc", "400 Robert St, St. Paul, MN"),
            ("NorthStar Hospice LLC", "St. Paul", "NorthStar Care Holdings LLC", "D. Keller", "Capitol Agents Inc", "400 Robert St, St. Paul, MN"),
            ("MedEquip Direct LLC", "St. Paul", "NorthStar Care Holdings LLC", "D. Keller", "Capitol Agents Inc", "400 Robert St, St. Paul, MN"),
            ("ClearLab Diagnostics LLC", "Minneapolis", None, "R. Anand", "North Registered Agents", "2100 Hennepin Ave, Minneapolis, MN"),
            ("TeleVisit Now LLC", "Austin (virtual)", None, "K. Bright", "Lone Star Agents", "virtual only, no MN office"),
            ("SkinRenew Wound Care LLC", "Mankato", None, "P. Voss", "Prairie Filing Co", "1400 Madison Ave, Mankato, MN"),
            ("BrightPath Autism Center LLC", "Brooklyn Park", None, "T. Nguyen", "North Registered Agents", "8500 Zane Ave, Brooklyn Park, MN"),
        ],
        "providers": ["A. Reyes, MD", "B. Haugen, MD", "C. Meyer, MD", "D. Osei, MD", "E. Lindqvist, DPM", "F. Barlow, DPM", "G. Tran, MD", "H. Weiss, NP", "I. Novak, MD", "J. Park, MD", "K. Abdi, MD", "L. Fontaine, NP"],
        "cash_note_name": "SkinRenew Wound Care",
    },
    "new_york": {
        "state": "New York", "seed": 20261029, "generated": "2026-10-29", "tin_prefix": "13",
        "counties": ["Kings", "Queens", "New York", "Bronx", "Nassau", "Suffolk", "Westchester", "Albany", "Monroe", "Erie"],
        "ghost_county": "Kings", "paid_factor": 1.2,
        "entities": [
            ("Hudson Family Medicine LLC", "Albany", None, "M. Delaney", "Empire Registered Agents", "90 State St, Albany, NY"),
            ("Empire Cardiology Associates LLC", "New York", None, "S. Goldstein", "Empire Registered Agents", "120 Broadway, New York, NY"),
            ("Finger Lakes Podiatry Group PLLC", "Rochester", None, "J. Kowalski", "Rochester Filing Co", "200 East Ave, Rochester, NY"),
            ("Empire State Home Health LLC", "Albany", "Empire Care Holdings LLC", "D. Marchetti", "Albany Agents Inc", "111 Washington Ave, Albany, NY"),
            ("Empire State Hospice LLC", "Albany", "Empire Care Holdings LLC", "D. Marchetti", "Albany Agents Inc", "111 Washington Ave, Albany, NY"),
            ("Empire Medical Supply LLC", "Albany", "Empire Care Holdings LLC", "D. Marchetti", "Albany Agents Inc", "111 Washington Ave, Albany, NY"),
            ("Gotham Diagnostics LLC", "Brooklyn", None, "R. Osei", "Empire Registered Agents", "300 Cadman Plaza, Brooklyn, NY"),
            ("VirtualCare Atlantic LLC", "New York (virtual)", None, "K. Brennan", "Empire Registered Agents", "virtual only, no NY office"),
            ("Lakeside Wound Care LLC", "Buffalo", None, "P. Nowak", "Rochester Filing Co", "500 Delaware Ave, Buffalo, NY"),
            ("Bright Futures Behavioral Center LLC", "Syracuse", None, "T. Delgado", "Empire Registered Agents", "100 Clinton Square, Syracuse, NY"),
        ],
        "providers": ["A. Cohen, MD", "B. Murphy, MD", "C. Rossi, MD", "D. Adeyemi, MD", "E. Kowalski, DPM", "F. Santoro, DPM", "G. Nguyen, MD", "H. Schwartz, NP", "I. Petrov, MD", "J. Kim, MD", "K. Haddad, MD", "L. Moreau, NP"],
        "cash_note_name": "Lakeside Wound Care",
    },
    "florida": {
        "state": "Florida", "seed": 20261030, "generated": "2026-10-29", "tin_prefix": "59",
        "counties": ["Miami-Dade", "Broward", "Palm Beach", "Hillsborough", "Orange", "Duval", "Lee", "Pinellas"],
        "ghost_county": "Palm Beach", "paid_factor": 0.85,
        "entities": [
            ("Gulf Coast Family Medicine LLC", "Tampa", None, "M. Delgado", "Sunshine Registered Agents", "401 E Jackson St, Tampa, FL"),
            ("Atlantic Cardiology Associates LLC", "Miami", None, "S. Fernandez", "Sunshine Registered Agents", "1111 Brickell Ave, Miami, FL"),
            ("Sunshine Podiatry Group PLLC", "Orlando", None, "J. Whitfield", "Orlando Filing Co", "200 S Orange Ave, Orlando, FL"),
            ("Palm Coast Home Health LLC", "West Palm Beach", "Palm Coast Care Holdings LLC", "D. Merritt", "Palm Beach Agents Inc", "250 Australian Ave S, West Palm Beach, FL"),
            ("Palm Coast Hospice LLC", "West Palm Beach", "Palm Coast Care Holdings LLC", "D. Merritt", "Palm Beach Agents Inc", "250 Australian Ave S, West Palm Beach, FL"),
            ("Palm Coast Medical Supply LLC", "West Palm Beach", "Palm Coast Care Holdings LLC", "D. Merritt", "Palm Beach Agents Inc", "250 Australian Ave S, West Palm Beach, FL"),
            ("SunState Diagnostics LLC", "Jacksonville", None, "R. Okafor", "Sunshine Registered Agents", "50 N Laura St, Jacksonville, FL"),
            ("TeleHealth Sunshine LLC", "Miami (virtual)", None, "K. Barrett", "Sunshine Registered Agents", "virtual only, no FL office"),
            ("Everglades Wound Care LLC", "Fort Myers", None, "P. Varela", "Orlando Filing Co", "2000 Main St, Fort Myers, FL"),
            ("Bright Path Behavioral Center LLC", "Fort Lauderdale", None, "T. Nguyen", "Sunshine Registered Agents", "110 E Broward Blvd, Fort Lauderdale, FL"),
        ],
        "providers": ["A. Delgado, MD", "B. Callahan, MD", "C. Moreno, MD", "D. Osei, MD", "E. Whitfield, DPM", "F. Barrow, DPM", "G. Tran, MD", "H. Winter, NP", "I. Novoa, MD", "J. Park, MD", "K. Abdi, MD", "L. Fontaine, NP"],
        "cash_note_name": "Everglades Wound Care",
    },
}


def d(month: int, day: int) -> str:
    return f"2026-{month:02d}-{day:02d}"


def build(cfg: dict) -> dict:
    rng = random.Random(cfg["seed"])
    f = cfg.get("paid_factor", 1.0)  # planted amounts vary by state; Minnesota stays at 1.0
    # TIN and NPI formats match the Minnesota file: 41-2001001, 1000000101.
    entities = [
        {
            "id": f"E{i + 1:02d}", "name": name, "kind": _ENTITY_KINDS[i],
            "tin": f"{cfg['tin_prefix']}-2001{i + 1:03d}", "city": city,
            "parent": parent, "owner": owner, "agent": agent, "address": address,
        }
        for i, (name, city, parent, owner, agent, address) in enumerate(cfg["entities"])
    ]
    providers = [
        {"npi": f"10000001{i + 1:02d}", "name": cfg["providers"][i], "specialty": spec, "entities": ents}
        for i, (spec, ents) in enumerate(_PROVIDER_ROLES)
    ]

    enrollees, claims, encounters = [], [], []
    claim_seq = [0]
    enrollee_age = {}

    def claim(enrollee, npi, entity, code, date, paid, payer=None):
        claim_seq[0] += 1
        claims.append({
            "id": f"C{claim_seq[0]:04d}", "enrollee": enrollee, "npi": npi, "entity": entity,
            "code": code, "date": date, "paid": paid,
            "payer": payer or ("Medicare" if enrollee_age[enrollee] >= 65 else "Medicaid"),
        })

    # 60 ordinary enrollees with real record histories and matching claims.
    for i in range(1, 61):
        pid = f"PT-{i:04d}"
        age = rng.choice([34, 41, 47, 52, 58, 63, 67, 71, 76, 82])
        enrollee_age[pid] = age
        dx = rng.sample(DIAGNOSES, k=rng.choice([1, 1, 2]))
        visits = rng.randint(2, 7)
        enc = []
        prov = rng.choice(providers[:6])
        for v in range(visits):
            # PT-0021 dies on 2026-03-01 (planted case F). Their ordinary
            # care all happens before that date, so only the planted
            # claim can ever bill after it.
            dt = d(rng.randint(1, 2) if pid == "PT-0021" else rng.randint(1, 9), rng.randint(1, 28))
            enc.append({"date": dt, "npi": prov["npi"], "entity": prov["entities"][0], "kind": "office visit"})
            encounters.append({"enrollee": pid, **enc[-1]})
        enrollees.append({
            "id": pid, "age": age, "sex": rng.choice(["F", "M"]), "county": rng.choice(cfg["counties"]),
            "program": "Medicare" if age >= 65 else "Medicaid",
            "diagnoses": dx, "immunizations": rng.randint(2, 9), "visits": visits,
            "housing": rng.choices(["stable", "sheltered", "displaced"], weights=[86, 9, 5])[0],
            "death_date": None, "prescriptions": [], "cash_services": [],
        })
        for e in enc[: rng.randint(1, 3)]:
            claim(pid, e["npi"], e["entity"], "99213", e["date"], rng.choice([88, 92, 95, 101]))

    by_id = {e["id"]: e for e in enrollees}

    # PLANTED A: duplicative billing. One visit, two entities bill it.
    p = by_id["PT-0003"]
    encounters.append({"enrollee": p["id"], "npi": "1000000101", "entity": "E01", "kind": "office visit", "date": d(5, 12)})
    claim(p["id"], "1000000101", "E01", "99213", d(5, 12), round(95 * f))
    claim(p["id"], "1000000110", "E08", "99213", d(5, 12), round(140 * f))

    # PLANTED B: podiatrist billing the longest interprofessional consults.
    p = by_id["PT-0007"]
    for dt in (d(3, 3), d(4, 14), d(6, 2)):
        claim(p["id"], "1000000105", "E03", "99449", dt, round(210 * f))

    # PLANTED C: family medicine paid far above the specialist for 99213.
    p = by_id["PT-0011"]
    for dt in (d(2, 9), d(5, 19)):
        claim(p["id"], "1000000102", "E01", "99213", dt, round(318 * f))
    for dt in (d(2, 16), d(5, 26)):
        claim(p["id"], "1000000103", "E02", "99213", dt, round(96 * f))

    # PLANTED D: wound care paid in cash, then billed to Medicare anyway.
    p = by_id["PT-0014"]
    p["cash_services"].append({"code": "97597", "date": d(4, 8), "amount": round(180 * f), "note": f"paid cash at {cfg['cash_note_name']}"})
    claim(p["id"], "1000000109", "E09", "97597", d(4, 8), round(240 * f))

    # PLANTED E: ghost enrollee. No record at all, billed by the DME arm.
    enrollees.append({
        "id": "PT-0077", "age": 58, "sex": "M", "county": cfg["ghost_county"], "program": "Medicaid",
        "diagnoses": [], "immunizations": 0, "visits": 0, "housing": "unknown",
        "death_date": None, "prescriptions": [], "cash_services": [],
    })
    enrollee_age["PT-0077"] = 58
    for dt in (d(1, 15), d(2, 15), d(3, 15), d(4, 15), d(5, 15), d(6, 15)):
        claim("PT-0077", "1000000108", "E06", "99451", dt, round(260 * f), payer="Medicaid")

    # PLANTED F: billed after death.
    p = by_id["PT-0021"]
    p["death_date"] = d(3, 1)
    claim(p["id"], "1000000107", "E04", "99213", d(4, 19), round(130 * f))

    # PLANTED G: stacked GLP-1s from two sources, one off-record cash.
    p = by_id["PT-0031"]
    p["prescriptions"] = [
        {"drug": "semaglutide (GLP-1)", "source": "insurance", "prescriber": "1000000110", "from": d(2, 1), "to": d(8, 1)},
        {"drug": "tirzepatide (GLP-1)", "source": "cash, off-record", "prescriber": "1000000109", "from": d(3, 1), "to": d(7, 1)},
    ]
    claim(p["id"], "1000000110", "E08", "99451", d(3, 10), round(120 * f))
    claim(p["id"], "1000000110", "E08", "99451", d(4, 10), round(120 * f))

    return {
        "state": cfg["state"],
        "note": "SYNTHETIC DEMO DATA. Every person, provider, entity, NPI, and dollar is invented. No real patient, provider, or claim appears anywhere.",
        "generated": cfg["generated"], "seed": cfg["seed"], "generator": "scripts/make_pilot_states.py",
        "codes": CODES,
        "scope": {k: sorted(v) for k, v in SCOPE.items()},
        "entities": entities,
        "providers": providers,
        "enrollees": enrollees,
        "encounters": encounters,
        "claims": claims,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fname, cfg in STATES.items():
        sample = build(cfg)
        out = OUT / f"{fname}.json"
        out.write_text(json.dumps(sample, indent=1) + "\n")
        print(f"wrote {out.name}: {cfg['state']}, {len(sample['enrollees'])} enrollees, {len(sample['claims'])} claims")


if __name__ == "__main__":
    main()
