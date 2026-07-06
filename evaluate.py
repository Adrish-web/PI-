#!/usr/bin/env python3
import sys, csv, json, os

run_dir = sys.argv[1] if len(sys.argv) > 1 else "."
out_dir = os.path.join(run_dir, "outputs")
SRC = os.path.join(out_dir, "Candidate_Queue.csv")
PROFILES_JSON = os.path.join(out_dir, "profiles.json")

DISEASE_W = {"glioblastoma": 1.00, "glioma": 0.95, "brain tumor": 1.00, "brain tumour": 1.00, "metasta": 0.70, "carcinoma": 0.55, "cancer": 0.50, "tumor": 0.55, "tumour": 0.55, "tumor microenvironment": 0.80}
MECH_W = {"mesenchymal transition": 1.00, "invasion": 0.95, "migration": 0.90, "gap junction": 1.00, "connexin": 1.00, "cell adhesion": 0.85, "tumor microenvironment": 0.90, "hippo": 0.80, "yap": 0.80, "signal transduction": 0.55, "signaling": 0.50, "membrane": 0.55}
METHOD_W = {"spatial": 1.00, "single-cell": 1.00, "rna sequencing": 0.85, "rna-seq": 0.85, "crispr": 0.90, "organoid": 0.90, "immunofluorescence": 0.65, "flow cytometry": 0.60, "knockout": 0.60}
MODEL_W = {"patient-derived": 1.00, "organoid": 0.95, "in vivo": 0.80, "mouse model": 0.80, "murine": 0.75}
INNOV_W = {"spatial": 1.00, "single-cell": 1.00, "nanoparticle": 0.85, "mechanob": 0.90, "bioinformatic": 0.70, "immunotherap": 0.70, "proteomic": 0.65}
CLUSTER_PROBES = {"Glioblastoma / Neuro-oncology": ["glioblastoma", "glioma", "brain tumor"], "EMT & Invasion": ["mesenchymal transition", "invasion"], "Gap Junction & Membrane": ["gap junction", "connexin"], "Mechanobiology": ["mechanob", "cell adhesion"], "Spatial & Omics": ["spatial", "single-cell", "rna-seq"]}

def norm(s): return (s or "").strip().lower()
def terms(cell): return [t.strip() for t in norm(cell).split(",") if t.strip()]
def best_weight(text_terms, weight_map):
    hits = []
    joined = " | ".join(text_terms)
    for key, w in weight_map.items():
        if any(key in t for t in text_terms) or key in joined: hits.append(w)
    return hits

def load():
    with open(SRC, newline="", encoding="utf-8") as f: return list(csv.DictReader(f))

def score_row(r):
    dt, mt, mdt, mot, em = terms(r["Disease"]), terms(r["Mechanism"]), terms(r["Methods"]), terms(r["Model Systems"]), norm(r["Emerging Direction"])
    allblob = " ".join([norm(r[k]) for k in ("Disease", "Mechanism", "Methods", "Model Systems", "Emerging Direction", "Department", "University")])
    try: disc = float(r["Discovery Score"])
    except ValueError: disc = 55.0
    verif = norm(r["Verification Level"])

    dh = best_weight(dt, DISEASE_W)
    rm = max(dh) * 0.80 + min(0.20, 0.05 * (len(dh) - 1)) if dh else 0.15
    research_match = round(35 * min(rm, 1.0), 2)

    mh = best_weight(mt, MECH_W)
    mo = 0.65 * max(mh) + 0.35 * min(1.0, sum(sorted(mh, reverse=True)[:3]) / 2.0) if mh else 0.10
    mech_overlap = round(20 * min(mo, 1.0), 2)

    th = best_weight(mdt + mot, {**METHOD_W, **MODEL_W})
    tc = 0.55 * max(th) + 0.45 * min(1.0, sum(sorted(th, reverse=True)[:3]) / 2.2) if th else 0.12
    tech_complement = round(15 * min(tc, 1.0), 2)

    pp_base = max(0.0, min(1.0, (disc - 40.0) / 45.0))
    pub_profile = round(10 * min(pp_base * (1.0 + (0.06 if verif == "verified" else 0.0)), 1.0), 2)

    ih = best_weight([em] + mdt + mt, INNOV_W)
    innov = round(7 * (min(1.0, (max(ih) if ih else 0.25) * 0.8 + min(0.2, 0.07 * len(ih)))), 2)

    sci_impact = round(5 * min(pp_base * 0.7 + (0.3 if verif == "verified" else 0.15), 1.0), 2)
    career = round(5 * min((0.34 if mdt else 0.0) + (0.33 if mot else 0.0) + (0.33 if mt else 0.0), 1.0), 2)
    
    inst_signal = 0.4 if norm(r["Department"]) not in ("", "unknown") else 0.15
    collab = round(3 * min(inst_signal + (0.25 if r["Lab Website"] not in ("Unknown", "") else 0.0), 1.0), 2)

    total = round(research_match + mech_overlap + tech_complement + pub_profile + innov + sci_impact + career + collab, 2)
    conf = "High" if len(mot) > 0 and len(dt) > 0 else "Medium"
    
    cl_scores = {name: sum(1 for p in probes if p in allblob) for name, probes in CLUSTER_PROBES.items()}
    cluster = max(cl_scores, key=cl_scores.get) if max(cl_scores.values()) > 0 else "General Cancer Biology"

    return {"components": {"Research Match (35)": research_match, "Mechanistic Overlap (20)": mech_overlap, "Technical Complement (15)": tech_complement, "Publication Profile (10)": pub_profile, "Innovation (7)": innov, "Scientific Impact (5)": sci_impact, "Career Development (5)": career, "Collaboration Network (3)": collab}, "total": total, "confidence": conf, "cluster": cluster}

def main():
    profiles = []
    for r in load():
        s = score_row(r)
        profiles.append({"Name": r["Name"], "Position": r["Position"], "University": r["University"], "Department": r["Department"], "Country": r["Country"], "Email": r["Email"], "Verification Level": r["Verification Level"], "Discovery Score": r["Discovery Score"], "Disease": r["Disease"], "Mechanism": r["Mechanism"], "Methods": r["Methods"], "Model Systems": r["Model Systems"], "Emerging Direction": r["Emerging Direction"], "ORCID": r["ORCID"], **s["components"], "Scientific Score": s["total"], "Confidence": s["confidence"], "Cluster": s["cluster"]})

    profiles.sort(key=lambda p: (-p["Scientific Score"], p["Name"]))
    for i, p in enumerate(profiles, 1): p["Rank"] = i

    with open(PROFILES_JSON, "w") as f: json.dump(profiles, f, indent=2)
    print(f"[*] Successfully scored {len(profiles)} PIs and saved to {PROFILES_JSON}")

if __name__ == "__main__": main()
