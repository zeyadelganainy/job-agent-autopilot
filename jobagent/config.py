"""Load config.yaml, the profile, writing samples, and environment secrets."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# override=True so .env is authoritative over any ambient shell env var. Without it,
# a key exported in the shell (e.g. Claude Code's own ANTHROPIC_API_KEY) silently
# shadows a blank .env entry — a real footgun for this BYOK tool.
load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str = "config.yaml") -> dict:
    with open(ROOT / path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile(cfg: dict) -> dict:
    with open(ROOT / cfg["paths"]["profile"], "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_master(cfg: dict) -> str:
    """The full master résumé (source of truth) used when generating documents."""
    p = ROOT / cfg["paths"]["master"]
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load_samples(cfg: dict) -> str:
    """Concatenate writing samples into one block used as voice exemplars."""
    d = ROOT / cfg["paths"]["samples"]
    if not d.exists():
        return ""
    chunks = []
    for p in sorted(d.glob("*")):
        if p.suffix.lower() in {".txt", ".md"} and p.name.lower() != "readme.txt":
            chunks.append(f"--- sample: {p.name} ---\n{p.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


def env(key: str, required: bool = False) -> str | None:
    val = os.getenv(key)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key} (set it in .env)")
    return val
