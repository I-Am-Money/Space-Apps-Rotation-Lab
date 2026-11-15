# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Reproducible local checks, reports and performance measurements."""
import argparse
import json
import hashlib
from pathlib import Path
import time

import numpy as np
import pandas as pd

from engine import api_v3 as api, fetch_icrisat, optimize


def main():
    parser = argparse.ArgumentParser(description="RotationLab offline verification and reporting")
    parser.add_argument("command", choices=["check-data", "report", "benchmark"])
    parser.add_argument("--scenarios", type=int, default=500)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-tipping", action="store_true")
    args = parser.parse_args()
    if not 10 <= args.scenarios <= 1000:
        parser.error("--scenarios must be between 10 and 1000")
    api.N_SCEN = api.BOUNDARY_N_SCEN = args.scenarios
    if args.command == "check-data":
        source_dir = api.ROOT / "data/raw/icrisat_dld"
        source = json.loads((source_dir / "SOURCE.json").read_text())
        observed_path = source_dir / Path(source["extracted_file"]).name
        if hashlib.sha256(observed_path.read_bytes()).hexdigest() != source["extracted_sha256"]:
            raise ValueError("District-yield cache checksum does not match its source manifest")
        annual = api.annual()
        for key in ("precip", "et0", "tmax"):
            if not np.isfinite(annual[key]).all():
                raise ValueError(f"Missing or nonfinite weather: {key}")
        observed = fetch_icrisat.load_district_yields()
        result = {"weather_years": annual["years"].tolist(), "crop_year_counts": fetch_icrisat.year_counts(observed),
                  "district_yield_source": observed.attrs["source"], "offline_data_checks": "passed"}
    elif args.command == "report":
        rec = api.recommend()
        validation = api.hindcast()
        result = {"recommendation": rec["top"], "baseline": rec["metrics"].query("id == 'rice-rice-rice-rice'").iloc[0].to_dict(),
                  "parameters": rec["params"], "farm": rec["farm"], "n_scenarios": rec["n_scenarios"],
                  "validation": validation, "limitations": (api.ROOT / "LIMITATIONS.md").read_text()}
        if args.include_tipping:
            result["tipping_points"] = api.tipping_points()
    else:
        result = {}
        tasks = [("cold_recommend", lambda: api.recommend()),
                 ("priority_change", lambda: api.recommend({"lam": .9, "w": .9})),
                 ("supply_change", lambda: api.recommend({"canal_supply_mm": 300., "well_supply_mm": 100.}))]
        if args.include_tipping:
            tasks += [("cold_tipping", lambda: api.tipping_points({"boundary_scenarios": args.scenarios})), ("warm_tipping", lambda: api.tipping_points({"boundary_scenarios": args.scenarios}))]
        for label, fn in tasks:
            start = time.perf_counter(); fn()
            result[label + "_seconds"] = round(time.perf_counter() - start, 4)
        result.update(scenarios=args.scenarios, candidate_rotations=len(optimize.ALL_PLANS),
                      model_cache_mb=round((optimize._SIM_CACHE.bytes + optimize._ARR_CACHE.bytes) / 2**20, 2))
    def clean(value):
        if isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        if isinstance(value, (np.ndarray, pd.Series)):
            return clean(value.tolist())
        if isinstance(value, pd.DataFrame):
            return clean(value.to_dict("records"))
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, np.generic):
            return clean(value.item())
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    text = json.dumps(clean(result), indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
        print(args.output)
    else:
        print(text)


if __name__ == "__main__":
    main()
