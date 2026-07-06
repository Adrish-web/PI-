"""HTTP client with on-disk caching and exponential backoff for OpenAlex,
ORCID public API, and NCBI E-utilities (PubMed)."""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

MAILTO = "theadrish.ghosh@gmail.com"
UA = f"SupervisorDiscoveryAgent/1.0 (mailto:{MAILTO})"

_stats = {"requests": 0, "cache_hits": 0, "errors": 0}

def cache_stats():
    return dict(_stats)

def _cache_path(key):
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return os.path.join(CACHE_DIR, h + ".json")

def _get(url, headers=None, cache=True, timeout=40, max_retries=5):
    cp = _cache_path(url)
    clean_url = url.split("?")[0].replace("https://", "").replace("api.openalex.org/", "OpenAlex: ").replace("pub.orcid.org/", "ORCID: ").replace("eutils.ncbi.nlm.nih.gov/entrez/eutils/", "PubMed: ")
    
    if cache and os.path.exists(cp):
        _stats["cache_hits"] += 1
        print(f"      [API-CACHE] {clean_url}")
        try:
            with open(cp) as f:
                return json.load(f)
        except Exception:
            pass
            
    print(f"      [API-FETCH] Fetching {clean_url}...")
    delay = 1.0
    last_err = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
            _stats["requests"] += 1
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"_raw": raw}
            if cache:
                with open(cp, "w") as f:
                    json.dump(data, f)
            return data
        except Exception as e:
            last_err = e
            code = getattr(e, "code", None)
            if code in (400, 404):
                _stats["errors"] += 1
                data = {"_error": str(e), "_code": code}
                if cache:
                    with open(cp, "w") as f:
                        json.dump(data, f)
                return data
            print(f"      [API-ERROR] {e}. Retrying in {delay}s...")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    _stats["errors"] += 1
    return {"_error": str(last_err)}

# ---------------- OpenAlex ----------------
OA = "https://api.openalex.org"

def oa_get(path, params):
    params = dict(params)
    params["mailto"] = MAILTO
    url = f"{OA}/{path}?{urllib.parse.urlencode(params)}"
    return _get(url)

def find_institution(name):
    d = oa_get("institutions", {"search": name, "per_page": 1})
    res = d.get("results") or []
    if not res:
        return None
    r = res[0]
    return {"id": r["id"].split("/")[-1], "display_name": r["display_name"],
            "country_code": r.get("country_code"), "ror": r.get("ror")}

def works_for_institution(inst_id, query, per_page=50):
    flt = (f"authorships.institutions.id:{inst_id},"
           f"from_publication_date:2022-01-01,"
           f"title_and_abstract.search:{query}")
    d = oa_get("works", {"filter": flt, "per_page": per_page,
                         "sort": "relevance_score:desc",
                         "select": "id,display_name,publication_year,authorships,primary_location,topics,keywords,doi,cited_by_count"})
    return d.get("results") or []

def author_record(author_id):
    aid = author_id.split("/")[-1]
    return oa_get(f"authors/{aid}", {})

def author_recent_works(author_id, per_page=25):
    aid = author_id.split("/")[-1]
    flt = f"authorships.author.id:{aid},from_publication_date:2022-01-01"
    d = oa_get("works", {"filter": flt, "per_page": per_page, "sort": "publication_date:desc",
                         "select": "id,display_name,publication_year,publication_date,authorships,primary_location,topics,keywords,doi,cited_by_count"})
    return d.get("results") or []

# ---------------- ORCID ----------------
def orcid_record(orcid):
    if not orcid:
        return None
    oid = orcid.split("/")[-1]
    url = f"https://pub.orcid.org/v3.0/{oid}/record"
    return _get(url, headers={"Accept": "application/json", "User-Agent": UA})

def parse_orcid(rec):
    out = {"employment": None, "department": None, "urls": [], "email": None, "current": False}
    if not rec or "_error" in rec: return out
    try:
        act = rec.get("activities-summary", {})
        emps = act.get("employments", {}).get("affiliation-group", [])
        best = None
        for g in emps:
            for s in g.get("summaries", []):
                e = s.get("employment-summary", {})
                end = e.get("end-date")
                org = (e.get("organization") or {}).get("name")
                dept = e.get("department-name")
                if best is None or end is None: best = (org, dept, end is None)
        if best:
            out["employment"], out["department"], out["current"] = best[0], best[1], best[2]
    except Exception: pass
    try:
        urls = rec.get("person", {}).get("researcher-urls", {}).get("researcher-url", [])
        for u in urls:
            val = (u.get("url") or {}).get("value")
            if val: out["urls"].append(val)
    except Exception: pass
    try:
        emails = rec.get("person", {}).get("emails", {}).get("email", [])
        for e in emails:
            if e.get("email"):
                out["email"] = e["email"]
                break
    except Exception: pass
    return out

# ---------------- PubMed E-utilities ----------------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def pubmed_count(author_name, affiliation=None):
    time.sleep(0.35)
    term = f'{author_name}[Author]'
    if affiliation: term += f' AND {affiliation}[Affiliation]'
    term += ' AND 2022:2026[dp]'
    url = f"{EUTILS}/esearch.fcgi?db=pubmed&term={urllib.parse.quote(term)}&retmode=json&retmax=1&email={MAILTO}"
    d = _get(url)
    try: return int(d.get("esearchresult", {}).get("count", 0))
    except Exception: return 0
