"""The Job record that flows through ingest -> score -> generate."""
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Job:
    source: str                 # "greenhouse", "lever", "ashby", "indeed", ...
    title: str
    company: str
    url: str
    location: str = ""
    description: str = ""
    posted: str = ""            # ISO date string if known
    job_id: str = field(default="")

    # populated by the scorer
    score: Optional[int] = None
    reasons: str = ""
    gaps: str = ""

    def __post_init__(self):
        if not self.job_id:
            # short, stable id derived from the canonical url (or source+title fallback)
            basis = (self.url or f"{self.source}:{self.company}:{self.title}").strip().lower()
            self.job_id = hashlib.sha1(basis.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return asdict(self)
