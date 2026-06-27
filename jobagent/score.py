"""Score a job against the profile. Returns a 0-100 match with reasons + gaps."""
import yaml

from .llm import LLMError, chat, extract_json
from .models import Job

SYSTEM = (
    "You are a precise technical recruiter. Score how well a candidate matches a job. "
    "Be honest and calibrated — most jobs are not a 90+. Reward real overlap in skills, "
    "level, and domain; penalize missing hard requirements. "
    "Respond with ONLY a JSON object, no prose, no code fences."
)

TEMPLATE = """Candidate profile (YAML):
{profile}

Job:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Return JSON exactly like:
{{"score": <int 0-100>, "reasons": "<one sentence on the fit>", "gaps": "<one sentence on missing requirements, or empty>"}}"""


def score_job(job: Job, profile: dict, models: dict) -> Job:
    user = TEMPLATE.format(
        profile=yaml.safe_dump(profile, sort_keys=False),
        title=job.title,
        company=job.company,
        location=job.location,
        description=(job.description or "")[:6000],   # keep prompt bounded
    )
    try:
        data = extract_json(chat(SYSTEM, user, models))
        job.score = int(data.get("score", 0))
        job.reasons = str(data.get("reasons", ""))
        job.gaps = str(data.get("gaps", ""))
    except LLMError:
        raise   # LLM is down / no key / quota — let the scan surface a clear message
    except Exception as e:
        print(f"[score] unparseable response for {job.title} @ {job.company}: {e}")
        job.score = 0
        job.reasons = "scoring failed (could not parse model output)"
    return job
