# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""MSP (Minimum Support Price) loader for the four RotationLab crops.

Source of truth: PIB press release "Cabinet approves Minimum Support Prices (MSP)
for Kharif Crops for Marketing Season 2026-27", 13 May 2026,
https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1

`refresh()` re-downloads the PIB page into data/raw/ and parses the table, then
checks it against config/prices_india.yaml. `load_prices()` reads the YAML only
(offline). `potential_yield_from_icrisat()` fills potential yield (P90 of
detrended district yields) from engine.fetch_icrisat.
"""
from __future__ import annotations
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "config" / "prices_india.yaml"
RAW = ROOT / "data" / "raw" / "msp_kharif_2026_27_pib_PRID2260617.html"
PIB_URL = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1"

# row label in the PIB table -> our crop id (first match after the label wins)
_ROWS = {"rice": r"Paddy\s+Common", "jowar": r"Jowar\s+Hybrid", "bajra": r"Bajra",
         "pigeonpea": r"Tur\s*/?\s*Arhar"}


def load_prices() -> dict:
    """Parsed config/prices_india.yaml (works offline)."""
    return yaml.safe_load(YAML_PATH.read_text())


def parse_pib_table(html: str) -> dict:
    """Return {crop: dict(msp, cost_a2fl, margin_pct, msp_prev)} from the PIB page.
    Columns in the PIB table: MSP 2026-27, Cost (all-India weighted avg, A2+FL),
    margin %, MSP 2025-26, MSP 2013-14, increase vs 2025-26, increase vs 2013-14."""
    text = re.sub(r"<[^>]*>", " ", html)
    text = re.sub(r"&nbsp;|&#8211;", " ", text)
    text = re.sub(r"\s+", " ", text)
    out = {}
    for crop, label in _ROWS.items():
        m = re.search(label + r"\s+(\d{3,5})\s+(\d{3,5})\s+(\d{2})\s+(\d{3,5})", text)
        if not m:
            raise ValueError(f"could not parse PIB row for {crop}")
        out[crop] = dict(msp=int(m[1]), cost_a2fl=int(m[2]), margin_pct=int(m[3]), msp_prev=int(m[4]))
    return out


def refresh(timeout: int = 60) -> dict:
    """Download the PIB page (cached to data/raw), parse, compare with the YAML."""
    import requests
    r = requests.get(PIB_URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    RAW.write_bytes(r.content)
    return verify()


def verify() -> dict:
    """Parse the cached PIB page and assert it matches the YAML. Offline."""
    parsed = parse_pib_table(RAW.read_text(errors="ignore"))
    cfg = load_prices()["msp"]
    for crop, row in parsed.items():
        assert cfg[crop]["msp_rs_per_quintal"] == row["msp"], (crop, cfg[crop], row)
        assert cfg[crop]["cost_a2fl_rs_per_quintal_allindia"] == row["cost_a2fl"], (crop, row)
    return parsed


def potential_yield_from_icrisat(district: str | None = None) -> dict:
    """{crop: kg/ha or None} = P90 of detrended district yields (None if no data)."""
    from engine.fetch_icrisat import load_district_yields, potential_yield
    df = load_district_yields(district)
    return {c: potential_yield(df, c) for c in ("rice", "jowar", "bajra", "pigeonpea")}


if __name__ == "__main__":
    print(verify())
