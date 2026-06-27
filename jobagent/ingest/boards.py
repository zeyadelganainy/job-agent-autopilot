"""Job board ingest via JobSpy. Optional — ToS-grey and can get your IP blocked.
Disabled by default in config.yaml. ATS feeds are the safer primary source.
"""
from ..models import Job


def fetch_all(search_cfg: dict, boards_cfg: dict) -> list[Job]:
    if not boards_cfg.get("enabled"):
        return []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print("[boards] jobspy not installed; skipping")
        return []

    out: list[Job] = []
    term = " ".join(search_cfg.get("keywords", [])[:1]) or "software engineer"
    for location in search_cfg.get("locations", ["Remote"]):
        try:
            df = scrape_jobs(
                site_name=boards_cfg.get("sites", ["indeed"]),
                search_term=term,
                location=location,
                results_wanted=boards_cfg.get("results_per_site", 20),
                is_remote=search_cfg.get("remote_ok", False),
                hours_old=search_cfg.get("max_age_days", 30) * 24,
            )
        except Exception as e:
            print(f"[boards] scrape failed for {location}: {e}")
            continue

        for _, r in df.iterrows():
            out.append(Job(
                source=str(r.get("site", "board")),
                title=str(r.get("title", "")),
                company=str(r.get("company", "")),
                url=str(r.get("job_url", "")),
                location=str(r.get("location", "")),
                description=str(r.get("description", "") or ""),
                posted=str(r.get("date_posted", "")),
            ))
    print(f"[boards] {len(out)} jobs")
    return out
