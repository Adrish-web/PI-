"""Candidate research vector, keyword taxonomies, scoring, and lab fingerprint.

All scoring is transparent keyword/topic overlap against the candidate research
vector. No fabricated data: everything derives from OpenAlex work titles,
abstracts, topics/keywords and author metadata.
"""
import re

# ---- Candidate research vector (from CV) ----
CANDIDATE_VECTOR = {
    "diseases": ["glioblastoma", "brain tumour", "brain tumor", "cancer", "tumour", "tumor"],
    "mechanisms": ["connexin", "pannexin", "emt", "hybrid emt", "gap junction",
                   "nf-kb", "nf-kappab", "cell signalling", "cell signaling",
                   "tumour microenvironment", "tumor microenvironment"],
    "methods": ["mammalian cell culture", "stable cell line", "flow cytometry",
                "immunofluorescence", "molecular cloning", "confocal", "sted", "tirf"],
    "career_goal": "Independent cancer cell biology lab focused on membrane signalling.",
}

# Category -> keyword list used for semantic-overlap matching against a PI's
# fingerprint text (titles + abstracts + topic/keyword display names).
CATEGORY_KEYWORDS = {
    "disease": [
        "glioblastoma", "glioma", "brain tumor", "brain tumour", "astrocytoma",
        "cancer", "tumor", "tumour", "oncolog", "carcinoma", "neoplas", "malignan",
        "metasta", "leukemia", "leukaemia", "lymphoma", "melanoma", "sarcoma",
    ],
    "mechanism": [
        "connexin", "pannexin", "gap junction", "cx43", "gja1",
        "epithelial-mesenchymal", "epithelial mesenchymal", "emt", "mesenchymal transition",
        "nf-kb", "nf-kappa", "nfkb", "signaling", "signalling", "signal transduction",
        "tumor microenvironment", "tumour microenvironment", "membrane", "cell adhesion",
        "wnt", "notch", "hippo", "yap", "receptor", "kinase", "transcription factor",
        "inflammation", "cytokine", "apoptosis", "autophagy", "migration", "invasion",
    ],
    "methods": [
        "cell culture", "stable cell line", "cell line", "flow cytometry", "facs",
        "immunofluorescence", "immunohistochem", "cloning", "crispr", "knockdown",
        "knockout", "western blot", "rna-seq", "rna sequencing", "qpcr", "pcr",
        "transfection", "electroporation", "apoptosis assay", "proliferation assay",
        "co-culture", "spheroid", "wound healing", "migration assay",
    ],
    "technology": [
        "confocal", "sted", "tirf", "super-resolution", "super resolution",
        "live-cell imaging", "live cell imaging", "microscopy", "fluorescence imaging",
        "flim", "fret", "light sheet", "two-photon",
    ],
    "career": [
        "cell biology", "membrane", "membrane signaling", "membrane signalling",
        "cancer cell biology", "molecular biology", "cell signaling",
    ],
    "model": [
        "mammalian cell", "cell line", "mouse model", "murine", "xenograft",
        "organoid", "patient-derived", "in vivo", "rodent", "zebrafish model",
    ],
}

# Discovery-score weights on scientific-match categories (sum handled in scorer).
MATCH_WEIGHTS = {
    "disease": 0.30,
    "mechanism": 0.30,
    "methods": 0.20,
    "technology": 0.10,
    "career": 0.05,
    "model": 0.05,
}

# Terms that indicate an off-target field -> reject candidates.
REJECT_FIELD_TERMS = {
    "plant biology": ["arabidopsis", "plant ", "chloroplast", "photosynthes", "crop ",
                       "leaf ", "root growth", "rhizosphere", "agronom", "maize", "wheat"],
    "ecology": ["ecosystem", "biodiversity", "ecolog", "wildlife", "conservation biology",
                "habitat", "forest ", "soil microbial"],
    "evolution": ["phylogen", "speciation", "evolutionary biology", "population genetics of species"],
    "marine biology": ["coral", "marine ", "fish population", "ocean ", "coral reef", "algae bloom"],
}

# Pure-computational markers (reject only if NO wet-lab methods present).
COMPUTATIONAL_TERMS = [
    "bioinformatic", "in silico", "machine learning", "deep learning",
    "computational model", "algorithm", "software tool", "database", "genome assembly",
    "statistical method", "sequencing pipeline", "structural bioinformatics",
]
WETLAB_TERMS = [
    "cell culture", "cell line", "flow cytometry", "immunofluorescence", "western blot",
    "transfection", "mouse", "in vivo", "knockout", "knockdown", "crispr", "assay",
    "microscopy", "confocal", "tissue", "protein expression", "antibody", "staining",
]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower())


def _count_hits(text, terms):
    hits = set()
    for t in terms:
        if t in text:
            hits.add(t)
    return hits


def category_match(fp_text):
    """Return dict category -> fraction (0..1) of how strongly the PI's text hits
    that category's keyword set (saturating: >=3 distinct hits -> 1.0)."""
    scores = {}
    for cat, terms in CATEGORY_KEYWORDS.items():
        hits = _count_hits(fp_text, terms)
        scores[cat] = min(1.0, len(hits) / 3.0)
    return scores


def scientific_match_score(fp_text):
    """Weighted 0..1 scientific compatibility using MATCH_WEIGHTS."""
    cats = category_match(fp_text)
    return sum(cats[c] * w for c, w in MATCH_WEIGHTS.items()), cats


def reject_field(fp_text):
    """Return a rejection reason string if the fingerprint is clearly off-field,
    else None."""
    for field, terms in REJECT_FIELD_TERMS.items():
        hits = _count_hits(fp_text, terms)
        # require multiple distinct hits and essentially no cancer signal
        if len(hits) >= 2 and not _count_hits(fp_text, CATEGORY_KEYWORDS["disease"]):
            return f"Off-field: {field}"
    comp = _count_hits(fp_text, COMPUTATIONAL_TERMS)
    wet = _count_hits(fp_text, WETLAB_TERMS)
    if len(comp) >= 2 and len(wet) == 0:
        return "Pure computational biology (no wet-lab evidence)"
    return None


def build_fingerprint(works):
    """From up to 5 works, produce a lab fingerprint dict. `works` is a list of
    OpenAlex work dicts."""
    texts = []
    topics = {}
    years = []
    venues = set()
    for w in works:
        texts.append(_norm(w.get("display_name")))
        # reconstruct abstract from inverted index if present
        abst = w.get("abstract_inverted_index")
        if abst:
            try:
                positions = {}
                for word, idxs in abst.items():
                    for i in idxs:
                        positions[i] = word
                texts.append(_norm(" ".join(positions[i] for i in sorted(positions))))
            except Exception:
                pass
        for t in (w.get("topics") or []):
            name = t.get("display_name")
            if name:
                topics[name] = topics.get(name, 0) + 1
            texts.append(_norm(name))
        for kw in (w.get("keywords") or []):
            texts.append(_norm(kw.get("display_name")))
        if w.get("publication_year"):
            years.append(w["publication_year"])
        loc = (w.get("primary_location") or {}).get("source") or {}
        if loc.get("display_name"):
            venues.add(loc["display_name"])
    fp_text = " ".join(texts)
    _, cats = scientific_match_score(fp_text)

    def top_terms(cat, limit=6):
        return sorted(_count_hits(fp_text, CATEGORY_KEYWORDS[cat]))[:limit]

    top_topics = sorted(topics.items(), key=lambda x: -x[1])[:5]
    emerging = top_topics[0][0] if top_topics else "Unknown"
    return {
        "fp_text": fp_text,
        "categories": cats,
        "disease": ", ".join(top_terms("disease")) or "Unknown",
        "mechanism": ", ".join(top_terms("mechanism")) or "Unknown",
        "methods": ", ".join(top_terms("methods")) or "Unknown",
        "technology": ", ".join(top_terms("technology")) or "Unknown",
        "model_systems": ", ".join(top_terms("model")) or "Unknown",
        "emerging_direction": emerging,
        "top_topics": [t for t, _ in top_topics],
        "years": years,
        "venues": sorted(venues)[:5],
        "n_papers": len(works),
    }


def discovery_score(fp, pi_stats, verification_level):
    """Compute discovery score out of 100.
    pi_stats: dict with keys last_author_count, recent_works, works_last3y,
              years_active_recent, distinct_recent_years.
    """
    sci, cats = scientific_match_score(fp["fp_text"])
    sci_pts = 40.0 * sci

    # Research activity (20): recent output volume (last-author + total recent)
    recent = pi_stats.get("works_last3y", 0)
    la = pi_stats.get("last_author_count", 0)
    activity = min(1.0, (recent / 8.0) * 0.6 + (la / 4.0) * 0.4)
    act_pts = 20.0 * activity

    # Publication activity (15): recency + consistency + venues
    distinct_years = pi_stats.get("distinct_recent_years", 0)  # of last 3-4 yrs
    consistency = min(1.0, distinct_years / 3.0)
    recency = 1.0 if pi_stats.get("has_2024_plus") else (0.6 if recent else 0.0)
    venue_score = min(1.0, len(fp.get("venues", [])) / 3.0)
    pub_pts = 15.0 * (0.4 * recency + 0.4 * consistency + 0.2 * venue_score)

    # Independent lab (10): last-author signal
    lab_pts = 10.0 * min(1.0, la / 2.0)

    # Technique match (10): methods + technology categories
    tech_pts = 10.0 * (0.6 * cats["methods"] + 0.4 * cats["technology"])

    # Verification confidence (5)
    vconf = {"Verified": 1.0, "Strong": 0.8, "Moderate": 0.5, "Weak": 0.2}.get(verification_level, 0.3)
    ver_pts = 5.0 * vconf

    total = sci_pts + act_pts + pub_pts + lab_pts + tech_pts + ver_pts
    return round(total, 1), {
        "scientific_match": round(sci_pts, 1),
        "research_activity": round(act_pts, 1),
        "publication_activity": round(pub_pts, 1),
        "independent_lab": round(lab_pts, 1),
        "technique_match": round(tech_pts, 1),
        "verification": round(ver_pts, 1),
    }
