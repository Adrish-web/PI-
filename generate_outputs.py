#!/usr/bin/env python3
import csv, json, os, sys, statistics as st
from collections import defaultdict
from datetime import datetime, timezone

run_dir = sys.argv[1] if len(sys.argv) > 1 else "."
out_dir = os.path.join(run_dir, "outputs")
PROFILES_JSON = os.path.join(out_dir, "profiles.json")

P = json.load(open(PROFILES_JSON))
N = len(P)
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
COMPONENT_COLS = ["Research Match (35)", "Mechanistic Overlap (20)", "Technical Complement (15)", "Publication Profile (10)", "Innovation (7)", "Scientific Impact (5)", "Career Development (5)", "Collaboration Network (3)"]

def write_profile_csv():
    cols = (["Rank", "Name", "Position", "University", "Department", "Country", "Email", "Cluster", "Confidence", "Discovery Score"] + COMPONENT_COLS + ["Scientific Score", "Disease", "Mechanism", "Methods", "Model Systems", "Emerging Direction", "ORCID"])
    with open(os.path.join(out_dir, "Scientific_Profile.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in P: w.writerow(p)

def write_top40_csv():
    cols = ["Rank", "Name", "University", "Department", "Country", "Cluster", "Scientific Score", "Confidence", "Email", "ORCID"]
    with open(os.path.join(out_dir, "Top40_Candidates.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in P[:40]: w.writerow(p)

def write_cluster_report():
    by = defaultdict(list)
    for p in P: by[p["Cluster"]].append(p)
    order = sorted(by, key=lambda c: (-st.mean([x["Scientific Score"] for x in by[c]]), -len(by[c])))
    lines = ["# Cluster Report - Pass 2", "", f"_Generated: {NOW}_", "", "| Cluster | n | Mean score | Top representative (rank) |", "|---|---|---|---|"]
    for c in order:
        members = sorted(by[c], key=lambda x: x["Rank"])
        lines.append(f"| {c} | {len(members)} | {round(st.mean([x['Scientific Score'] for x in members]), 2)} | {members[0]['Name']} (#{members[0]['Rank']}) |")
    open(os.path.join(out_dir, "Cluster_Report.md"), "w").write("\n".join(lines) + "\n")

def write_rankings():
    lines = ["# Scientific Rankings - Pass 2", "", f"_Generated: {NOW}_", "", "| Rank | Name | University | Department | Cluster | Score | Conf |", "|---|---|---|---|---|---|---|"]
    for p in P: lines.append(f"| {p['Rank']} | {p['Name']} | {p['University']} | {p['Department'] if p['Department'] not in ('Unknown', '') else '-'} | {p['Cluster']} | {p['Scientific Score']} | {p['Confidence']} |")
    open(os.path.join(out_dir, "Scientific_Rankings.md"), "w").write("\n".join(lines) + "\n")

write_profile_csv()
write_top40_csv()
write_cluster_report()
write_rankings()
print(f"[*] All Markdown and CSV reports generated inside {out_dir}/")
