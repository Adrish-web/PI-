import csv, json, os, re, time, unicodedata, sys
import apiclient as api
import vectors as V

# Read target directory from terminal argument
run_dir = sys.argv[1] if len(sys.argv) > 1 else "."
out_dir = os.path.join(run_dir, "outputs")
os.makedirs(out_dir, exist_ok=True)

TARGET = 10000
UNIVERSITIES = json.load(open(os.path.join(run_dir, "universities.json")))

QUEUE_CSV = os.path.join(out_dir, "Candidate_Queue.csv")
REJECT_CSV = os.path.join(out_dir, "Rejected_Candidates.csv")
SUMMARY_MD = os.path.join(out_dir, "University_Discovery_Summary.md")
STATE_JSON = os.path.join(out_dir, "discovery_state.json")
CHECKPOINT_JSON = os.path.join(out_dir, "Discovery_Checkpoint.json")

SEARCH_QUERIES = ["glioblastoma", "connexin", "epithelial mesenchymal transition", "tumor microenvironment", "cancer cell signaling", "glioma"]
EXPANSION_QUERIES = ["cancer stem cell", "tumor cell invasion", "gap junction"]

QUEUE_FIELDS = ["Name", "Position", "University", "Department", "Country", "Lab Website", "University Profile", "Email", "Verification Level", "Discovery Score", "Disease", "Mechanism", "Methods", "Model Systems", "Emerging Direction", "ORCID", "OpenAlex", "Google Scholar", "PubMed"]
REJECT_FIELDS = ["Name", "Institution", "Rejection Reason"]

def norm_name(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z ]", " ", n.lower())
    return re.sub(r"\s+", " ", n).strip()

class State:
    def __init__(self):
        self.current_university = None
        self.completed, self.verified, self.rejected = [], [], []
        self.seen_author_ids, self.seen_orcids, self.seen_names = set(), set(), set()
        self.duplicate_count = 0
        self.per_uni = {}
        self.low_yield_streak = 0

    def to_json(self): return {"verified_candidates": len(self.verified)}
    def save(self): json.dump(self.to_json(), open(STATE_JSON, "w"), indent=2)

def is_dup(state, author_id, orcid, name, inst):
    if author_id and author_id in state.seen_author_ids: return True
    if orcid and orcid in state.seen_orcids: return True
    if f"{norm_name(name)}|{norm_name(inst)}" in state.seen_names: return True
    return False

def mark_seen(state, author_id, orcid, name, inst):
    if author_id: state.seen_author_ids.add(author_id)
    if orcid: state.seen_orcids.add(orcid)
    state.seen_names.add(f"{norm_name(name)}|{norm_name(inst)}")

def init_outputs():
    if not os.path.exists(QUEUE_CSV):
        with open(QUEUE_CSV, "w", newline="") as f: csv.DictWriter(f, fieldnames=QUEUE_FIELDS).writeheader()
    if not os.path.exists(REJECT_CSV):
        with open(REJECT_CSV, "w", newline="") as f: csv.writer(f).writerow(REJECT_FIELDS)

def collect_candidate_pis(inst_id, queries):
    pis = {}
    for q in queries:
        print(f"  -> Querying OpenAlex for: '{q}'...")
        works = api.works_for_institution(inst_id, q)
        for w in works:
            for a in w.get("authorships", []):
                inst_ids = [(i.get("id") or "").split("/")[-1] for i in a.get("institutions", [])]
                if inst_id not in inst_ids: continue
                au = a.get("author", {})
                aid = au.get("id")
                if not aid: continue
                aid = aid.split("/")[-1]
                rec = pis.setdefault(aid, {"name": au.get("display_name"), "orcid": au.get("orcid"), "last_author_count": 0, "appearances": 0, "raw_dept": None})
                rec["appearances"] += 1
                if a.get("author_position") == "last": rec["last_author_count"] += 1
                for inst in a.get("institutions", []):
                    if (inst.get("id") or "").split("/")[-1] == inst_id:
                        rec["raw_dept"] = rec["raw_dept"] or inst.get("display_name")
    return pis

def evaluate_pi(aid, seed, inst_meta):
    inst_name = inst_meta["display_name"]
    print(f"      -> Fetching detailed OpenAlex record & works for {seed['name']}...")
    arec = api.author_record(aid)
    if "_error" in arec: return None, "OpenAlex author record unavailable", None
    
    orcid = arec.get("orcid") or seed.get("orcid")
    display_name = arec.get("display_name") or seed["name"]
    recent = api.author_recent_works(aid)
    if not recent: return None, "No publications after 2022", None

    years = [w.get("publication_year") for w in recent if w.get("publication_year")]
    distinct_recent = len({y for y in years if y and y >= 2022})
    works_last3y = sum(1 for y in years if y and y >= 2023)
    has_2024_plus = any(y and y >= 2024 for y in years)

    la_count = sum(1 for w in recent for a in w.get("authorships", []) if (a.get("author", {}).get("id") or "").split("/")[-1] == aid and a.get("author_position") == "last")
    la_count = max(la_count, seed.get("last_author_count", 0))

    fp = V.build_fingerprint(recent[:5])

    reason = V.reject_field(fp["fp_text"])
    if reason: return None, reason, fp
    sci, cats = V.scientific_match_score(fp["fp_text"])
    if cats["disease"] == 0 and cats["mechanism"] < 0.34: return None, "Research does not overlap cancer/cell biology", fp
    if la_count == 0: return None, "No independent lab (never senior/last author since 2022)", fp

    lab_url, profile_url, email = "Unknown", "Unknown", "Unknown"
    department = seed.get("raw_dept") or "Unknown"
    if department == inst_name: department = "Unknown"
    orcid_conf = False

    if orcid:
        parsed = api.parse_orcid(api.orcid_record(orcid))
        if parsed.get("department"): department = parsed["department"]
        for u in parsed.get("urls", []):
            lu = u.lower()
            if any(k in lu for k in ["lab", "group", "research", "faculty", "profile", "people", "staff", "www"]):
                if lab_url == "Unknown": lab_url = u
                elif profile_url == "Unknown": profile_url = u
        if parsed.get("email"): email = parsed["email"]
        if parsed.get("current") and parsed.get("employment"): orcid_conf = True

    pubmed_n = api.pubmed_count(display_name, inst_name.split()[0] if inst_name else None)

    if orcid_conf and (works_last3y or has_2024_plus): vlevel = "Verified"
    elif pubmed_n > 0 and distinct_recent >= 1: vlevel = "Strong"
    elif distinct_recent >= 1: vlevel = "Moderate"
    else: return None, "Weak evidence (single uncertain source)", fp

    pi_stats = {"last_author_count": la_count, "works_last3y": works_last3y, "distinct_recent_years": distinct_recent, "has_2024_plus": has_2024_plus}
    score, breakdown = V.discovery_score(fp, pi_stats, vlevel)

    gs = f"https://scholar.google.com/scholar?q={display_name.replace(' ', '+')}"
    pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/?term={display_name.replace(' ', '+')}%5BAuthor%5D" if pubmed_n else "Unknown"

    row = {"Name": display_name, "Position": "Principal Investigator" if la_count >= 2 else "Group Leader / Senior Author", "University": inst_name, "Department": department, "Country": inst_meta.get("country_code") or "Unknown", "Lab Website": lab_url, "University Profile": profile_url, "Email": email, "Verification Level": vlevel, "Discovery Score": score, "Disease": fp["disease"], "Mechanism": fp["mechanism"], "Methods": fp["methods"], "Model Systems": fp["model_systems"], "Emerging Direction": fp["emerging_direction"], "ORCID": orcid or "Unknown", "OpenAlex": f"https://openalex.org/{aid}", "Google Scholar": gs, "PubMed": pubmed_url}
    return row, None, fp

def process_university(state, uni):
    print(f"\n=======================================================")
    print(f" [*] TARGETING UNIVERSITY: {uni}")
    print(f"=======================================================")
    inst_meta = api.find_institution(uni)
    if not inst_meta:
        print(f"  [!] Institution not found: {uni}")
        state.per_uni[uni] = {"screened": 0, "verified": 0, "rejected": 0, "areas": [], "note": "Not found"}
        return
    inst_id = inst_meta["id"]
    
    pis = collect_candidate_pis(inst_id, list(SEARCH_QUERIES))
    ranked = sorted(pis.items(), key=lambda kv: (kv[1]["last_author_count"], kv[1]["appearances"]), reverse=True)

    senior = [k for k, v in ranked if v["last_author_count"] >= 1]
    if len(senior) < 5:
        more = collect_candidate_pis(inst_id, EXPANSION_QUERIES)
        for k, v in more.items():
            if k in pis:
                pis[k]["appearances"] += v["appearances"]
                pis[k]["last_author_count"] = max(pis[k]["last_author_count"], v["last_author_count"])
            else: pis[k] = v
        ranked = sorted(pis.items(), key=lambda kv: (kv[1]["last_author_count"], kv[1]["appearances"]), reverse=True)

    screened = verified_here = rejected_here = 0
    areas = set()
    to_eval = [kv for kv in ranked if kv[1]["last_author_count"] >= 1][:25]
    print(f"  [*] Found {len(to_eval)} Principal Investigators to evaluate.\n")

    for aid, seed in to_eval:
        if len(state.verified) >= TARGET: break
        if is_dup(state, aid, seed.get("orcid"), seed["name"], uni):
            state.duplicate_count += 1
            continue
            
        print(f"    [?] EVALUATING PI: {seed['name']} (Senior Author count: {seed['last_author_count']})")
        mark_seen(state, aid, seed.get("orcid"), seed["name"], uni)
        screened += 1
        try:
            row, reason, fp = evaluate_pi(aid, seed, inst_meta)
        except Exception as e:
            reason, row, fp = f"Error: {e}", None, None
            
        if row:
            with open(QUEUE_CSV, "a", newline="") as f: csv.DictWriter(f, fieldnames=QUEUE_FIELDS).writerow(row)
            state.verified.append(row)
            verified_here += 1
            for t in (fp.get("top_topics") or [])[:2]: areas.add(t)
            print(f"    [$$$] VERIFIED: {row['Name']} | Level: {row['Verification Level']} | Score: {row['Discovery Score']}\n")
            if len(state.verified) % 10 == 0: state.save()
        else:
            with open(REJECT_CSV, "a", newline="") as f: csv.writer(f).writerow([seed["name"], uni, reason or "Unknown"])
            state.rejected.append([seed["name"], uni, reason])
            rejected_here += 1
            print(f"    [x] REJECTED: {seed['name']} | Reason: {reason}\n")

    state.per_uni[uni] = {"screened": screened, "verified": verified_here, "rejected": rejected_here, "areas": sorted(areas)[:6], "yield": verified_here, "note": "" if verified_here else "Low/zero yield"}
    if verified_here < 5: state.low_yield_streak += 1
    else: state.low_yield_streak = 0

def update_summary(state):
    lines = ["# University Discovery Summary", "", f"**Verified supervisors so far:** {len(state.verified)} / {TARGET}", f"**Universities completed:** {len(state.completed)}", ""]
    for uni in state.completed:
        d = state.per_uni.get(uni, {})
        lines += [f"## {uni}", f"- Verified: {d.get('verified', 0)} / Rejected: {d.get('rejected', 0)}", f"- Areas: {', '.join(d.get('areas', [])) or 'Unknown'}", ""]
    open(SUMMARY_MD, "w").write("\n".join(lines))

def main():
    init_outputs()
    state = State()
    start = time.time()
    for uni in UNIVERSITIES:
        if len(state.verified) >= TARGET: break
        state.current_university = uni
        try: process_university(state, uni)
        except Exception as e: print(f"  [!] error on {uni}: {e}")
        state.completed.append(uni)
        state.save()
        update_summary(state)

    elapsed = time.time() - start
    print(f"\n=== DISCOVERY COMPLETE ===\nVerified: {len(state.verified)}\nRejected: {len(state.rejected)}\nUniversities Checked: {len(state.completed)}\nSaved to: {out_dir}")

if __name__ == "__main__":
    main()
