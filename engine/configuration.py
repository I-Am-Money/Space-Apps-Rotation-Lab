# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Cheap file-version tokens shared by model and UI caches."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version(include_data=False):
    paths = list((ROOT / "config").glob("*.yaml"))
    if include_data:
        paths += list((ROOT / "data/raw").glob("*.json"))
        paths += list((ROOT / "data/raw/icrisat_dld").glob("*.csv"))
        farm = ROOT / "data/raw/farm_records.csv"
        if farm.exists():
            paths.append(farm)
    return tuple((str(p.relative_to(ROOT)), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(paths))
