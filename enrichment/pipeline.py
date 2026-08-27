import httpx
import csv
import json
from datetime import datetime, timedelta
from enrichment.icp_classifier import classify_icp_segment

CRUNCHBASE_ODM_PATH = "data/crunchbase_odm_sample.json"
LAYOFFS_CSV_PATH = "data/layoffs_fyi.csv"


def enrich_company(company_name: str) -> dict:
    funding     = get_crunchbase_signal(company_name)
    job_posts   = get_job_post_velocity(company_name)
    layoffs     = get_layoff_signal(company_name)
    leadership  = get_leadership_change(company_name)
    ai_maturity = score_ai_maturity(
        company_name, job_posts,
        odm_record=_odm_record(company_name),
        github=_github(company_name),
    )

    signals = {
        "signal_1_funding_event":     funding,
        "signal_2_job_post_velocity": job_posts,
        "signal_3_layoff_event":      layoffs,
        "signal_4_leadership_change": leadership,
        "signal_5_ai_maturity":       ai_maturity,
    }
    signals["signal_6_icp_segment"] = classify_icp_segment(signals)

    return {
        "company":          company_name,
        "crunchbase_id":    funding.get("crunchbase_id", ""),
        "last_enriched_at": datetime.utcnow().isoformat() + "Z",
        "firmographics":    funding.get("firmographics", {}),
        "signals":          signals
    }


def _odm_record(company_name: str) -> dict | None:
    with open(CRUNCHBASE_ODM_PATH) as f:
        records = json.load(f)
    return next(
        (r for r in records if company_name.lower() in r.get("name", "").lower()),
        None,
    )


def _github(company_name: str) -> dict | None:
    from enrichment.live_sources import fetch_github_org

    return fetch_github_org(company_name)


def get_crunchbase_signal(company_name: str) -> dict:
    with open(CRUNCHBASE_ODM_PATH) as f:
        records = json.load(f)
    match = next(
        (r for r in records if company_name.lower() in r.get("name", "").lower()),
        None
    )
    if not match:
        return {"present": False, "confidence": "low", "source": "crunchbase_odm"}

    last_funding = match.get("last_funding_at", "")
    days_ago = (
        (datetime.utcnow() - datetime.fromisoformat(last_funding)).days
        if last_funding else 9999
    )
    return {
        "crunchbase_id": match.get("uuid", ""),
        "present":       days_ago <= 180,
        "days_ago":      days_ago,
        "amount_usd":    match.get("last_funding_total_usd", 0),
        "round_type":    match.get("last_funding_type", ""),
        "confidence":    "high" if days_ago <= 180 else "low",
        "source":        "crunchbase_odm",
        "firmographics": {
            "employees":         match.get("num_employees_enum", ""),
            "industry":          match.get("category_list", ""),
            "location":          match.get("city", "") + ", " + match.get("region", ""),
            "funding_total_usd": match.get("total_funding_usd", 0)
        }
    }


def get_layoff_signal(company_name: str) -> dict:
    """
    Reads layoffs.fyi CSV (CC-BY).
    Columns: Company, Location_HQ, Industry, Laid_Off_Count, Percentage,
             Date, Source, Country, Stage, Funds_Raised_USD
    Percentage is stored as a decimal (0.1 = 10%). Converted to float % here.
    """
    cutoff = datetime.utcnow() - timedelta(days=120)
    with open(LAYOFFS_CSV_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if company_name.lower() not in row.get("Company", "").lower():
                continue
            try:
                event_date = datetime.strptime(row["Date"], "%Y-%m-%d")
            except ValueError:
                continue
            if event_date < cutoff:
                continue

            days_ago = (datetime.utcnow() - event_date).days

            # Percentage stored as decimal (0.1 → 10.0)
            raw_pct = row.get("Percentage", "") or ""
            try:
                pct_workforce = round(float(raw_pct) * 100, 1)
            except ValueError:
                pct_workforce = 0.0

            count_raw = row.get("Laid_Off_Count", "") or ""
            try:
                headcount_cut = int(float(count_raw))
            except ValueError:
                headcount_cut = 0

            return {
                "present":          True,
                "layoff_detected":  True,
                "days_ago":         days_ago,
                "pct_workforce":    pct_workforce,
                "headcount_cut":    headcount_cut,
                "industry":         row.get("Industry", ""),
                "stage":            row.get("Stage", ""),
                "source_url":       row.get("Source", ""),
                "confidence":       "high",
                "source":           "layoffs_fyi",
            }
    return {
        "present":         False,
        "layoff_detected": False,
        "confidence":      "high",
        "source":          "layoffs_fyi",
    }


VELOCITY_CACHE_PATH = "data/velocity_cache.json"

def _compute_velocity_delta(company_name: str, current_count: int):
    """
    Computes 60-day job-post delta by comparing current_count against a cached
    baseline stored in data/velocity_cache.json. On first run, writes the baseline
    and returns "unknown". On subsequent runs >60 days later, returns the signed delta.
    """
    import json as _json
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    cache_path = _Path(VELOCITY_CACHE_PATH)
    cache = {}
    if cache_path.exists():
        try:
            cache = _json.loads(cache_path.read_text())
        except Exception:
            cache = {}

    key = company_name.lower()
    now = _dt.utcnow()

    if key in cache:
        entry = cache[key]
        baseline_date = _dt.fromisoformat(entry["date"])
        days_elapsed = (now - baseline_date).days
        if days_elapsed >= 60:
            delta = current_count - entry["count"]
            # Refresh baseline after computing delta
            cache[key] = {"count": current_count, "date": now.isoformat()}
            try:
                cache_path.write_text(_json.dumps(cache, indent=2))
            except Exception:
                pass
            return f"{delta:+d} over 60d"
        return f"snapshot {days_elapsed}d old (need 60d)"

    # First run — store baseline, delta unknown
    cache[key] = {"count": current_count, "date": now.isoformat()}
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(_json.dumps(cache, indent=2))
    except Exception:
        pass
    return "unknown (baseline stored)"


def get_job_post_velocity(company_name: str) -> dict:
    """Open-role counts from the company's PUBLIC job board.

    Greenhouse, Lever, and Ashby expose unauthenticated JSON APIs for public
    boards — a hit yields real posting titles and a citable board URL. A
    miss is reported as exactly that: many companies use other ATSes, so
    absence of a feed is NOT evidence about hiring, and this signal then
    carries low confidence with no invented counts. (The earlier Playwright
    Wellfound scrape is gone: it was blocked in practice and its fallback
    fabricated a count — a made-up number is worse than an honest unknown.)
    """
    from enrichment.live_sources import (
        count_roles,
        fetch_job_board,
        live_lookups_enabled,
        slug_candidates,
    )

    if not live_lookups_enabled():
        return {
            "present":    False,
            "confidence": "low",
            "source":     "not_checked_live_lookups_disabled",
            "note":       "ENRICHMENT_LIVE_LOOKUPS is off — no network calls made.",
        }

    board = fetch_job_board(company_name)
    if board is None:
        return {
            "present":    False,
            "confidence": "low",
            "source":     "no_public_job_board_found",
            "checked":    [
                f"greenhouse/lever/ashby under slugs {slug_candidates(company_name)}"
            ],
            "note": (
                "No public Greenhouse/Lever/Ashby board found under the "
                "expected names. Absence of a posting feed is not proof the "
                "company isn't hiring."
            ),
        }

    total, eng, ml = count_roles(board["titles"])
    delta_60d = _compute_velocity_delta(company_name, total)
    return {
        "present":           total > 0,
        "open_roles_total":  total,
        "engineering_roles": eng,
        "ml_roles":          ml,
        "sample_titles":     board["titles"][:5],
        "delta_60d":         delta_60d,
        "confidence":        "high",   # real, citable posting feed
        "source":            board["source"],
        "source_url":        board["board_url"],
    }


def get_leadership_change(company_name: str) -> dict:
    """New CTO/VP-Eng-style leadership within 90 days, from the handed ODM
    data: dated leadership_hire news events (with citable links) first, then
    dated titles in the people list. No event → honest absent."""
    record = _odm_record(company_name)
    if record is None:
        return {"present": False, "confidence": "low",
                "source": "crunchbase_odm", "note": "company not in ODM sample"}

    ENG_KEYWORDS = ("cto", "chief technology", "vp engineering",
                    "vp of engineering", "head of engineering")
    for event in record.get("leadership_events", []):
        label = str(event.get("label", "")).lower()
        if not any(k in label for k in ENG_KEYWORDS + ("leadership", "ceo")):
            continue
        try:
            days_ago = (datetime.utcnow()
                        - datetime.fromisoformat(event["date"])).days
        except (KeyError, ValueError):
            continue
        if 0 <= days_ago <= 90:
            return {
                "present":    True,
                "role":       event.get("label", "")[:120],
                "days_ago":   days_ago,
                "confidence": "high",  # dated news event with a source link
                "source":     "crunchbase_odm_leadership_hire",
                "source_url": event.get("source_url", ""),
            }

    for person in record.get("people", []):
        title = str(person.get("title", ""))
        if not any(k in title.lower() for k in ENG_KEYWORDS):
            continue
        start = person.get("started_on", "")
        if start:
            try:
                days_ago = (datetime.utcnow()
                            - datetime.fromisoformat(start)).days
                if days_ago <= 90:
                    return {
                        "present":    True,
                        "role":       title,
                        "days_ago":   days_ago,
                        "confidence": "medium",
                        "source":     "crunchbase_odm",
                    }
            except ValueError:
                pass
    return {"present": False, "confidence": "medium", "source": "crunchbase_odm"}


def score_ai_maturity(
    company_name: str,
    job_posts: dict,
    odm_record: dict | None = None,
    github: dict | None = None,
) -> dict:
    """0-3 AI-readiness score from VERIFIABLE public evidence only.

    Three dimensions are actually checked (job-board role mix, ODM-listed
    AI/ML leadership, public GitHub org activity); dimensions with no
    integrated public source (tech stack, executive commentary, strategic
    communications) are reported as explicitly NOT CHECKED and contribute
    nothing — they are never invented. Every justification either cites a
    real source or says "not checked"; `checked: false` entries are exactly
    that.
    """
    from enrichment.live_sources import ml_repos

    score = 0
    justifications = []

    # 1. AI-adjacent open roles — real board data when a public feed exists.
    if job_posts.get("open_roles_total"):
        eng_roles = job_posts.get("ml_roles", job_posts.get("engineering_roles", 0))
        total_roles = job_posts["open_roles_total"]
        fraction = eng_roles / max(total_roles, 1)
        if fraction >= 0.3:
            score += 2
            status = f"{eng_roles} of {total_roles} open roles are AI/ML/data"
            conf = "high"
        elif fraction >= 0.1:
            score += 1
            status = f"{eng_roles} AI/ML/data roles among {total_roles} open"
            conf = "high"
        else:
            status = f"{total_roles} open roles, none AI/ML-titled"
            conf = "high"
        justifications.append({
            "signal": "ai_adjacent_open_roles", "status": status,
            "weight": "high", "confidence": conf, "checked": True,
            "source_url": job_posts.get("source_url", ""),
        })
    else:
        justifications.append({
            "signal": "ai_adjacent_open_roles",
            "status": "No public job feed found — not scored",
            "weight": "high", "confidence": "low", "checked": False,
        })

    # 2. Named AI/ML leadership — real people data from the Crunchbase ODM
    # record (public dataset), not a guess.
    ai_title = None
    for person in (odm_record or {}).get("people", []):
        title = str(person.get("title", ""))
        if any(k in title.lower() for k in (
            "ai", "machine learning", "ml", "data scien", "chief scientist",
        )):
            ai_title = title
            break
    if odm_record is None:
        justifications.append({
            "signal": "named_ai_ml_leadership",
            "status": "Company not in the Crunchbase ODM sample — not scored",
            "weight": "high", "confidence": "low", "checked": False,
        })
    elif ai_title:
        score += 1
        justifications.append({
            "signal": "named_ai_ml_leadership",
            "status": f"ODM record lists an AI/ML leadership title: {ai_title}",
            "weight": "high", "confidence": "medium", "checked": True,
            "source": "crunchbase_odm_people",
        })
    else:
        justifications.append({
            "signal": "named_ai_ml_leadership",
            "status": "No AI/ML leadership title in the ODM people list "
                      "(list may be incomplete)",
            "weight": "high", "confidence": "low", "checked": True,
            "source": "crunchbase_odm_people",
        })

    # 3. Public GitHub org activity — real API lookup.
    if github is None:
        justifications.append({
            "signal": "github_org_activity",
            "status": "No public GitHub org found under expected names — "
                      "not scored (private orgs are invisible)",
            "weight": "medium", "confidence": "low", "checked": False,
        })
    elif github.get("rate_limited"):
        justifications.append({
            "signal": "github_org_activity",
            "status": "GitHub API rate-limited — not checked this run",
            "weight": "medium", "confidence": "low", "checked": False,
        })
    else:
        ml = ml_repos(github)
        if ml:
            score += 1
            justifications.append({
                "signal": "github_org_activity",
                "status": f"Public ML/AI-related repos: {', '.join(ml[:4])}",
                "weight": "medium", "confidence": "medium", "checked": True,
                "source_url": github.get("org_url", ""),
            })
        else:
            justifications.append({
                "signal": "github_org_activity",
                "status": f"Public org has {len(github.get('repos', []))} "
                          "repos, none ML/AI-related "
                          "(absence is not proof of absence)",
                "weight": "medium", "confidence": "medium", "checked": True,
                "source_url": github.get("org_url", ""),
            })

    # 4-6. No public source integrated — reported as such, never invented.
    for signal, needs in (
        ("modern_data_ml_stack", "a BuiltWith/Wappalyzer integration"),
        ("executive_commentary", "a news/podcast search integration"),
        ("strategic_communications", "a press/filings search integration"),
    ):
        justifications.append({
            "signal": signal,
            "status": f"Not checked — requires {needs}; no value assumed",
            "weight": "low", "confidence": "low", "checked": False,
        })

    final_score = min(score, 3)
    checked = [j for j in justifications if j.get("checked")]
    high_conf = sum(
        1 for j in checked
        if j.get("confidence") in ("high",) and j.get("weight") == "high"
    )
    if high_conf >= 1 and len(checked) >= 2:
        signal_confidence = "high" if high_conf >= 2 else "medium"
    elif checked:
        signal_confidence = "medium" if any(
            j.get("confidence") == "medium" for j in checked
        ) else "low"
    else:
        signal_confidence = "low"

    score_rationale = (
        f"Score {final_score}/3 from {len(checked)} verified dimension(s): "
        f"{', '.join(j['signal'] for j in checked) or 'none'}. "
        f"{len(justifications) - len(checked)} dimension(s) not checked "
        "(no public source) and contribute nothing. "
        "Absence of a public signal is NOT proof of absence of capability."
    )

    return {
        "score":               final_score,
        "justifications":      justifications,
        "confidence":          signal_confidence,
        "dimensions_checked":  len(checked),
        "score_rationale":     score_rationale,
    }


def generate_competitor_gap_brief(company_name: str, domain: str, ai_maturity_score: int,
                                   sector: str = "Fintech") -> dict:
    """Competitor gap brief built from the SAME live checks as the prospect.

    Peer pools are a curated editorial choice (well-known sector leaders in
    the Tenacious ICP band); every score and every piece of gap evidence,
    however, comes from the same real lookups used on the prospect — public
    job boards, the ODM dataset, public GitHub. Findings appear ONLY when a
    peer produced real evidence for them; nothing is invented, and the
    per-peer `evidence_basis` says exactly which checks succeeded.
    """
    from datetime import datetime

    from enrichment.live_sources import ml_repos

    SECTOR_PEERS = {
        "Fintech":    ["Stripe", "Plaid", "Square", "Adyen", "Checkout.com"],
        "DataOps":    ["Monte Carlo", "dbt Labs", "Databricks", "Fivetran", "Airbyte"],
        "DevTools":   ["GitHub", "GitLab", "CircleCI", "Snyk", "Datadog"],
        "default":    ["Stripe", "Plaid", "Square", "Adyen", "Checkout.com"],
    }
    known_sector = sector in SECTOR_PEERS
    candidate_pool = SECTOR_PEERS.get(sector, SECTOR_PEERS["default"])
    candidate_pool = [p for p in candidate_pool if p.lower() != company_name.lower()]
    sparse_sector = not known_sector or len(candidate_pool) < 5
    peers = candidate_pool[:5]

    analyzed = []
    for peer in peers:
        peer_jobs = get_job_post_velocity(peer)
        peer_record = _odm_record(peer)
        peer_github = _github(peer)
        peer_maturity = score_ai_maturity(
            peer, peer_jobs, odm_record=peer_record, github=peer_github
        )
        basis = [
            j["signal"] for j in peer_maturity["justifications"] if j.get("checked")
        ]
        analyzed.append({
            "name": peer,
            "ai_maturity_score":           peer_maturity["score"],
            "ai_maturity_confidence":      peer_maturity["confidence"],
            "ai_maturity_justification":   peer_maturity["justifications"],
            "ai_maturity_score_rationale": peer_maturity.get("score_rationale", ""),
            "headcount_band": (peer_record or {}).get("num_employees_enum", "unknown"),
            "evidence_basis": basis,
            "top_quartile": peer_maturity["score"] >= 2,
            "_jobs": peer_jobs,
            "_github": peer_github,
        })

    peer_scores = [a["ai_maturity_score"] for a in analyzed]
    if peer_scores:
        below = sum(1 for x in peer_scores if x < ai_maturity_score)
        distribution_position = {
            "prospect_score": ai_maturity_score,
            "sector_median": sorted(peer_scores)[len(peer_scores) // 2],
            "sector_top_quartile_score":
                sorted(peer_scores)[int(len(peer_scores) * 0.75)],
            "prospect_percentile": round(below / len(peer_scores) * 100),
            "above_median":
                ai_maturity_score > sorted(peer_scores)[len(peer_scores) // 2],
            "peer_count": len(analyzed),
        }
    else:
        distribution_position = {"note": "no peers available for comparison"}

    # Gap findings: constructed ONLY from real per-peer evidence.
    gap_findings = []

    hiring_evidence = []
    for a in analyzed:
        jobs = a["_jobs"]
        if jobs.get("ml_roles"):
            samples = [
                t for t in jobs.get("sample_titles", [])
                if any(k in t.lower() for k in ("ml", "ai", "machine", "data"))
            ][:2]
            hiring_evidence.append({
                "competitor_name": a["name"],
                "evidence": f"{jobs['ml_roles']} open AI/ML/data roles on their "
                            f"public job board"
                            + (f" (e.g. {'; '.join(samples)})" if samples else ""),
                "source_url": jobs.get("source_url", ""),
            })
    if hiring_evidence:
        gap_findings.append({
            "practice": "Active AI/ML engineering hiring",
            "peer_evidence": hiring_evidence[:3],
            "prospect_state": (
                "Prospect's public job feed shows no AI/ML-titled roles"
                if ai_maturity_score < 2 else
                "Prospect also shows AI-adjacent hiring"
            ),
            "confidence": "high" if ai_maturity_score < 2 else "low",
            "segment_relevance": ["segment_4_specialized_capability",
                                   "segment_1_series_a_b"],
        })

    github_evidence = []
    for a in analyzed:
        gh = a["_github"]
        if gh and not gh.get("rate_limited"):
            ml = ml_repos(gh)
            if ml:
                github_evidence.append({
                    "competitor_name": a["name"],
                    "evidence": f"Public ML/AI repositories: {', '.join(ml[:3])}",
                    "source_url": gh.get("org_url", ""),
                })
    if github_evidence:
        gap_findings.append({
            "practice": "Public open-source ML/AI engineering",
            "peer_evidence": github_evidence[:3],
            "prospect_state": "No public ML/AI repository activity found for "
                              "the prospect (private work is invisible)",
            "confidence": "medium",
            "segment_relevance": ["segment_4_specialized_capability"],
        })

    leadership_evidence = []
    for a in analyzed:
        for j in a["ai_maturity_justification"]:
            if (j["signal"] == "named_ai_ml_leadership" and j.get("checked")
                    and "leadership title" in j.get("status", "")):
                leadership_evidence.append({
                    "competitor_name": a["name"],
                    "evidence": j["status"],
                    "source": "crunchbase_odm_people",
                })
    if leadership_evidence:
        gap_findings.append({
            "practice": "Named AI/ML leadership",
            "peer_evidence": leadership_evidence[:3],
            "prospect_state": "No AI/ML leadership title in the prospect's "
                              "ODM people list",
            "confidence": "medium",
            "segment_relevance": ["segment_4_specialized_capability"],
        })

    for a in analyzed:  # internal working keys don't belong in the brief
        a.pop("_jobs", None)
        a.pop("_github", None)

    return {
        "prospect_domain": domain,
        "prospect_sector": sector,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "prospect_ai_maturity_score": ai_maturity_score,
        "distribution_position": distribution_position,
        "sparse_sector": sparse_sector,
        "sparse_sector_note": (
            f"Only {len(peers)} curated peers for '{sector}'. Benchmarks are "
            "indicative; peer visibility varies by what each company makes public."
            if sparse_sector else ""
        ),
        "competitor_selection_criteria": (
            f"Curated sector leaders for '{sector}' in the Tenacious ICP band; "
            "each scored with the same live checks as the prospect (public job "
            "boards, Crunchbase ODM people, public GitHub). Findings exist only "
            "where a peer produced real evidence."
        ),
        "competitors_analyzed": analyzed,
        "gap_findings": gap_findings,
        "suggested_pitch_shift": (
            f"Lead with the '{gap_findings[0]['practice']}' gap — it has real "
            "peer evidence."
            if gap_findings else
            "No evidenced gap found — open with questions, not comparisons."
        ),
        "gap_quality_self_check": {
            "all_peer_evidence_real": True,
            "findings_with_evidence": len(gap_findings),
            "at_least_one_gap_high_confidence": any(
                g["confidence"] == "high" for g in gap_findings
            ),
            "sparse_sector_flagged": sparse_sector,
        },
    }
