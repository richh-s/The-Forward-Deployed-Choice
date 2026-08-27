"""Live public-data lookups for the enrichment pipeline.

Every function here either returns REAL data from a public source or None —
never a fabricated value. Sources used:

- Job boards: Greenhouse, Lever, and Ashby all expose unauthenticated public
  JSON APIs for a company's open roles. A hit is a real posting count with a
  citable board URL; a miss is honestly a miss (many companies use other
  ATSes — absence of a feed is not proof of no hiring).
- GitHub: the public REST API for an org's repositories (unauthenticated,
  60 req/h rate limit — a 403 is reported as "rate limited", not as
  evidence either way).

Set ENRICHMENT_LIVE_LOOKUPS=false to skip all network calls (tests/CI):
every signal then reports "not checked" rather than pretending.
"""
import os
import re

import httpx

TIMEOUT = 6.0
_UA = {"User-Agent": "conversion-engine-enrichment/1.0 (public data lookup)"}

ML_TITLE_RE = re.compile(
    r"machine.?learning|\bml\b|\bai\b|data.(scien|engineer)|llm|deep.?learning"
    r"|applied.?scientist|mlops", re.I,
)
ENG_TITLE_RE = re.compile(
    r"engineer|developer|scientist|architect|devops|sre|data|platform", re.I,
)
# Deliberately strict: generic words like "agent" or "model" match far too
# much ordinary software (datadog-agent…) — a false "does ML" claim is worse
# than a miss.
ML_REPO_RE = re.compile(
    r"machine.?learning|\bllm\b|pytorch|tensorflow|deep.?learning|inference"
    r"|embedding|fine.?tun|\brag\b|\bgenai\b|neural", re.I,
)


def live_lookups_enabled() -> bool:
    return os.environ.get("ENRICHMENT_LIVE_LOOKUPS", "true").lower() not in (
        "0", "false", "no",
    )


def slug_candidates(company_name: str) -> list[str]:
    """Plausible ATS/GitHub slugs for a company name, most specific first."""
    base = re.sub(r"[^a-z0-9 ]", "", company_name.lower()).strip()
    words = base.split()
    stripped = [
        w for w in words
        if w not in ("technologies", "technology", "labs", "inc", "io", "hq",
                     "co", "corp", "company", "ltd", "gmbh")
    ] or words
    cands = [
        "".join(words), "-".join(words),
        "".join(stripped), "-".join(stripped),
    ]
    if stripped:
        cands.append(stripped[0])
    seen: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.append(c)
    return seen


def _get_json(url: str) -> object | None:
    try:
        r = httpx.get(url, timeout=TIMEOUT, headers=_UA, follow_redirects=False)
    except httpx.HTTPError:
        return None
    if r.status_code == 403:
        return {"_rate_limited": True}
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def fetch_job_board(company_name: str) -> dict | None:
    """First public ATS board found for the company: real job titles and a
    citable source URL, or None."""
    if not live_lookups_enabled():
        return None
    for slug in slug_candidates(company_name):
        gh = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if isinstance(gh, dict) and isinstance(gh.get("jobs"), list):
            return {
                "source": "greenhouse_public_api",
                "board_url": f"https://boards.greenhouse.io/{slug}",
                "titles": [str(j.get("title", "")) for j in gh["jobs"]],
            }
        lv = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if isinstance(lv, list) and lv:
            return {
                "source": "lever_public_api",
                "board_url": f"https://jobs.lever.co/{slug}",
                "titles": [str(j.get("text", "")) for j in lv],
            }
        ab = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if isinstance(ab, dict) and isinstance(ab.get("jobs"), list) and ab["jobs"]:
            return {
                "source": "ashby_public_api",
                "board_url": f"https://jobs.ashbyhq.com/{slug}",
                "titles": [str(j.get("title", "")) for j in ab["jobs"]],
            }
    return None


def fetch_github_org(company_name: str) -> dict | None:
    """Public repos of the first matching GitHub org, or a rate-limit marker,
    or None when no org exists under the expected names."""
    if not live_lookups_enabled():
        return None
    for slug in slug_candidates(company_name):
        data = _get_json(
            f"https://api.github.com/orgs/{slug}/repos?per_page=100&sort=pushed"
        )
        if isinstance(data, dict) and data.get("_rate_limited"):
            return {"rate_limited": True}
        if isinstance(data, list):
            return {
                "org_url": f"https://github.com/{slug}",
                "repos": [
                    {
                        "name": str(r.get("name", "")),
                        "description": str(r.get("description") or ""),
                        "language": str(r.get("language") or ""),
                    }
                    for r in data
                    if isinstance(r, dict)
                ],
            }
    return None


def ml_repos(github: dict) -> list[str]:
    return [
        r["name"] for r in github.get("repos", [])
        if ML_REPO_RE.search(f"{r['name']} {r['description']}")
    ]


def count_roles(titles: list[str]) -> tuple[int, int, int]:
    """(total, engineering, AI/ML) role counts from real posting titles."""
    eng = [t for t in titles if ENG_TITLE_RE.search(t)]
    ml = [t for t in titles if ML_TITLE_RE.search(t)]
    return len(titles), len(eng), len(ml)


def has_fabricated_sources(signals: dict) -> bool:
    """True if any signal value came from a mock/proxy rather than a real
    lookup or an honest not-checked entry. After the live-sources rework
    this should always be False — it exists as a tripwire so any future
    reintroduction of fabricated values is flagged to every consumer."""
    def _walk(obj) -> bool:
        if isinstance(obj, dict):
            src = str(obj.get("source", ""))
            if "mock" in src or "proxy" in src:
                return True
            return any(_walk(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_walk(v) for v in obj)
        return False

    return _walk(signals)
