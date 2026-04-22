import httpx
import csv
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from enrichment.icp_classifier import classify_icp_segment

CRUNCHBASE_ODM_PATH = "data/crunchbase_odm_sample.json"
LAYOFFS_CSV_PATH = "data/layoffs_fyi.csv"


def enrich_company(company_name: str) -> dict:
    funding     = get_crunchbase_signal(company_name)
    job_posts   = get_job_post_velocity(company_name)
    layoffs     = get_layoff_signal(company_name)
    leadership  = get_leadership_change(company_name)
    ai_maturity = score_ai_maturity(company_name, job_posts)

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
    cutoff = datetime.utcnow() - timedelta(days=120)
    with open(LAYOFFS_CSV_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if company_name.lower() in row.get("Company", "").lower():
                try:
                    date = datetime.strptime(row["Date"], "%Y-%m-%d")
                    if date >= cutoff:
                        days_ago = (datetime.utcnow() - date).days
                        return {
                            "present":       True,
                            "days_ago":      days_ago,
                            "headcount_cut": row.get("Laid_Off_Count", ""),
                            "confidence":    "high",
                            "source":        "layoffs_fyi"
                        }
                except ValueError:
                    continue
    return {"present": False, "confidence": "high", "source": "layoffs_fyi"}


def get_job_post_velocity(company_name: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            url = (
                f"https://wellfound.com/company/"
                f"{company_name.lower().replace(' ', '-')}/jobs"
            )
            page.goto(url, timeout=15000)
            page.wait_for_selector(".job-listing", timeout=5000)
            jobs = page.query_selector_all(".job-listing")
            eng_jobs = [
                j for j in jobs
                if any(
                    kw in j.inner_text().lower()
                    for kw in ["engineer", "developer", "ml", "data"]
                )
            ]
            return {
                "open_roles_total":  len(jobs),
                "engineering_roles": len(eng_jobs),
                "delta_60d":         "unknown",
                "confidence":        "medium",
                "source":            "wellfound_scrape"
            }
        except Exception:
            return {
                "open_roles_total":  0,
                "engineering_roles": 0,
                "delta_60d":         "unknown",
                "confidence":        "low",
                "source":            "wellfound_scrape_failed"
            }
        finally:
            browser.close()


def get_leadership_change(company_name: str) -> dict:
    with open(CRUNCHBASE_ODM_PATH) as f:
        records = json.load(f)
    match = next(
        (r for r in records if company_name.lower() in r.get("name", "").lower()),
        None
    )
    if match:
        for person in match.get("people", []):
            if any(
                title in person.get("title", "")
                for title in ["CTO", "VP Engineering", "VP Eng"]
            ):
                start = person.get("started_on", "")
                if start:
                    try:
                        days_ago = (
                            datetime.utcnow() - datetime.fromisoformat(start)
                        ).days
                        if days_ago <= 90:
                            return {
                                "present":    True,
                                "role":       person["title"],
                                "days_ago":   days_ago,
                                "confidence": "medium",
                                "source":     "crunchbase_odm"
                            }
                    except ValueError:
                        pass
    return {"present": False, "confidence": "medium", "source": "crunchbase_odm"}


def score_ai_maturity(company_name: str, job_posts: dict) -> dict:
    score = 0
    justification = []
    eng_roles   = job_posts.get("engineering_roles", 0)
    total_roles = job_posts.get("open_roles_total", 1)

    ai_role_fraction = eng_roles / max(total_roles, 1)
    if ai_role_fraction >= 0.3:
        score += 2
        justification.append({
            "signal": "ai_adjacent_open_roles",
            "weight": "high",
            "detail": f"{eng_roles} of {total_roles} roles are engineering/ML"
        })
    elif ai_role_fraction >= 0.1:
        score += 1
        justification.append({
            "signal": "ai_adjacent_open_roles",
            "weight": "high",
            "detail": f"{eng_roles} engineering/ML roles (moderate fraction)"
        })

    confidence = "high" if score >= 2 else "medium" if score == 1 else "low"
    return {
        "score":         min(score, 3),
        "justification": justification,
        "confidence":    confidence
    }
