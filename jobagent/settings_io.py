"""Read/write the editable parts of config.yaml for the Settings page.

Uses ruamel.yaml round-trip so the file's comments and structure survive edits.
"""
from ruamel.yaml import YAML

from .config import ROOT

PATH = ROOT / "config.yaml"
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


def _load():
    with open(PATH, "r", encoding="utf-8") as f:
        return _yaml.load(f)


def _save(data):
    with open(PATH, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)


def read() -> dict:
    """Flatten the editable fields into a plain dict for the form."""
    d = _load() or {}
    s = d.get("search", {}) or {}
    ats = (d.get("sources", {}) or {}).get("ats", {}) or {}
    boards = (d.get("sources", {}) or {}).get("boards", {}) or {}
    sc = d.get("scoring", {}) or {}
    m = d.get("models", {}) or {}
    sch = d.get("schedule", {}) or {}
    ag = d.get("agent", {}) or {}
    tr = d.get("tracker", {}) or {}
    return {
        "keywords": list(s.get("keywords") or []),
        "locations": list(s.get("locations") or []),
        "block_companies": list(s.get("block_companies") or []),
        "remote_ok": bool(s.get("remote_ok")),
        "max_age_days": s.get("max_age_days"),
        "greenhouse": list(ats.get("greenhouse") or []),
        "lever": list(ats.get("lever") or []),
        "ashby": list(ats.get("ashby") or []),
        "boards_enabled": bool(boards.get("enabled")),
        "threshold": sc.get("threshold"),
        "digest_size": sc.get("digest_size"),
        "max_to_score": sc.get("max_to_score"),
        "agent_enabled": bool(ag.get("enabled", True)),
        "min_score": ag.get("min_score", 80),
        "daily_cap": ag.get("daily_cap", 5),
        "auto_ghost": bool(tr.get("auto_ghost", True)),
        "ghost_after_weeks": tr.get("ghost_after_weeks", 4),
        "claude": m.get("claude"),
        "gemini": m.get("gemini"),
        "schedule_enabled": bool(sch.get("enabled")),
        "schedule_time": sch.get("time"),
        "schedule_timezone": sch.get("timezone"),
    }


def write(form: dict):
    """Apply form values back into config.yaml (only the known editable keys)."""
    d = _load() or {}
    d.setdefault("search", {})
    d["search"]["keywords"] = form["keywords"]
    d["search"]["locations"] = form["locations"]
    d["search"]["block_companies"] = form["block_companies"]
    d["search"]["remote_ok"] = form["remote_ok"]
    d["search"]["max_age_days"] = form["max_age_days"]

    d.setdefault("sources", {}).setdefault("ats", {})
    d["sources"]["ats"]["greenhouse"] = form["greenhouse"]
    d["sources"]["ats"]["lever"] = form["lever"]
    d["sources"]["ats"]["ashby"] = form["ashby"]
    d["sources"].setdefault("boards", {})["enabled"] = form["boards_enabled"]

    d.setdefault("scoring", {})
    d["scoring"]["threshold"] = form["threshold"]
    d["scoring"]["digest_size"] = form["digest_size"]
    d["scoring"]["max_to_score"] = form["max_to_score"]

    d.setdefault("agent", {})
    d["agent"]["enabled"] = form["agent_enabled"]
    d["agent"]["min_score"] = form["min_score"]
    d["agent"]["daily_cap"] = form["daily_cap"]

    d.setdefault("tracker", {})
    d["tracker"]["auto_ghost"] = form["auto_ghost"]
    d["tracker"]["ghost_after_weeks"] = form["ghost_after_weeks"]

    d.setdefault("models", {})
    d["models"]["claude"] = form["claude"]
    d["models"]["gemini"] = form["gemini"]

    d.setdefault("schedule", {})
    d["schedule"]["enabled"] = form["schedule_enabled"]
    d["schedule"]["time"] = form["schedule_time"]
    d["schedule"]["timezone"] = form["schedule_timezone"]
    _save(d)
