"""Pull jobs from public ATS JSON feeds. No scraping, no ToS issues.

Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Lever:      https://api.lever.co/v0/postings/{token}?mode=json
Ashby:      https://api.ashbyhq.com/posting-api/job-board/{token}
"""
import re

import requests

from ..models import Job

TIMEOUT = 20
HEADERS = {"User-Agent": "job-agent/1.0 (personal use)"}


def _clean(html: str) -> str:
    """ATS descriptions are HTML; strip tags to plain-ish text for the LLM."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;|&amp;|&#39;|&quot;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def greenhouse(token: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(Job(
            source="greenhouse",
            title=j.get("title", ""),
            company=token,
            url=j.get("absolute_url", ""),
            location=(j.get("location") or {}).get("name", ""),
            description=_clean(j.get("content", "")),
            posted=j.get("updated_at", ""),
        ))
    return jobs


def lever(token: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    jobs = []
    for j in data:
        cats = j.get("categories", {}) or {}
        jobs.append(Job(
            source="lever",
            title=j.get("text", ""),
            company=token,
            url=j.get("hostedUrl", ""),
            location=cats.get("location", ""),
            description=_clean(j.get("descriptionPlain", j.get("description", ""))),
            posted=str(j.get("createdAt", "")),
        ))
    return jobs


def ashby(token: str) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    data = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(Job(
            source="ashby",
            title=j.get("title", ""),
            company=token,
            url=j.get("jobUrl", ""),
            location=j.get("location", ""),
            description=_clean(j.get("descriptionPlain", "")),
            posted=j.get("publishedAt", ""),
        ))
    return jobs


_FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def fetch_all(ats_cfg: dict) -> list[Job]:
    out = []
    for provider, tokens in (ats_cfg or {}).items():
        fetcher = _FETCHERS.get(provider)
        if not fetcher:
            continue
        for token in tokens:
            try:
                got = fetcher(token)
                print(f"[ats] {provider}/{token}: {len(got)} jobs")
                out.extend(got)
            except Exception as e:
                print(f"[ats] {provider}/{token} failed: {e}")
    return out


def fetch_job(url: str) -> Job:
    """Fetch a single posting from a Greenhouse / Lever / Ashby job-board URL."""
    u = (url or "").strip()

    m = re.search(r"(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", u)
    if m:
        token, jid = m.group(1), m.group(2)
        d = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}",
                         headers=HEADERS, timeout=TIMEOUT).json()
        return Job(source="greenhouse", title=d.get("title", ""), company=token,
                   url=d.get("absolute_url", u),
                   location=(d.get("location") or {}).get("name", ""),
                   description=_clean(d.get("content", "")),
                   posted=d.get("updated_at", ""))

    m = re.search(r"jobs\.lever\.co/([^/?#]+)/([^/?#]+)", u)
    if m:
        token, jid = m.group(1), m.group(2)
        d = requests.get(f"https://api.lever.co/v0/postings/{token}/{jid}?mode=json",
                         headers=HEADERS, timeout=TIMEOUT).json()
        cats = d.get("categories", {}) or {}
        return Job(source="lever", title=d.get("text", ""), company=token,
                   url=d.get("hostedUrl", u), location=cats.get("location", ""),
                   description=_clean(d.get("descriptionPlain", d.get("description", ""))),
                   posted=str(d.get("createdAt", "")))

    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([^/?#]+)", u)
    if m:
        token, jid = m.group(1), m.group(2)
        data = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                            headers=HEADERS, timeout=TIMEOUT).json()
        for j in data.get("jobs", []):
            if jid == j.get("id") or jid in (j.get("jobUrl") or ""):
                return Job(source="ashby", title=j.get("title", ""), company=token,
                           url=j.get("jobUrl", u), location=j.get("location", ""),
                           description=_clean(j.get("descriptionPlain", "")),
                           posted=j.get("publishedAt", ""))
        raise ValueError("That Ashby posting wasn't found on the board.")

    raise ValueError(
        "Unrecognized job URL. Supported: boards.greenhouse.io/<token>/jobs/<id>, "
        "jobs.lever.co/<token>/<id>, jobs.ashbyhq.com/<token>/<id>. "
        "Otherwise paste the job description text instead.")
