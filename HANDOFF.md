# RotationLab handoff

Updated 2026-11-15 after reconciling the upstream v3 rebuild and second audit (through 6be85cb) with the local completion (d39d893). Both remote branches pointed to 6be85cb at audit time; no separate branch changes were outstanding. Read README.md, LIMITATIONS.md, docs/AUDIT_2026-11-15.md and engine/CONTRACT.md for current behavior.

## Run and verify

Use Python 3.11-3.13. Streamlit >=1.58 and the pinned numerical compiler are in requirements.txt.

```sh
.venv/bin/python -m engine check-data
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
.venv/bin/python -m engine report --output output/planning-report.json
.venv/bin/python -m engine benchmark --scenarios 500 --include-tipping
.venv/bin/python scripts/prepare_deploy.py
```

No API key is needed. Five screens use real cached data, with an offline district map. Optional Claude explanations require user opt-in; the deterministic explanation always works. There is no toy engine or mock fallback.

## Reconciled behavior

- Preserved the upstream plan rule (253 offered rotations, blocked monocultures comparison-only), paddy sale conversion, calibrated-calendar onset shifts, crop-specific heat windows, late-sowing penalty, soil-cover carry-over, year 1 after the farm's rice, income-shortfall and no-rotation-effect sensitivity views, and Indian currency formatting.
- Retained the recovered ICRISAT/TCI apportioned DLD: 52 positive-yield years for rice, bajra, kharif sorghum and pigeon pea; 17 for ragi. Both bajra and jowar are selected. Source checksums are bundled. Potential-yield estimates and validation training exclude held-out years where appropriate.
- Verified the upstream Telangana rice and pigeon-pea cultivation costs against the official university table and retained their explicit scaling assumptions. Millet budgets remain national unit-cost proxies. Measurement quotes stay unknown until entered. No separate water charge is deducted from profit.
- Adapted the compiled daily water kernel to the upstream onset/heat model. Water accounting, fixed-calendar equation parity, heat/onset/supply monotonicity, capped wells and canal-first use are tested.
- Kept request-local settings, bounded immutable model caches, shared-prefix simulation reuse, copied cache slices, source/config version tokens, exact count-weighted boundary bootstrap, and cached tipping responses.
- Supply overrides scale in boundary/EVPI sweeps. The full tipping option actually uses 500 sequences; interactive mode uses 150, with 200 boundary resamples. Main recommendations use 500.
- Preserved anonymous session-only farm uploads, local cultivation costs and measurement quotes, CSV/JSON exports, accessible decision-grid tables, Docker/CI/source bundles. Private local farm-record files are excluded from Git and Docker.

## Verification and performance

150 combined tests passed in 51.97 seconds on Python 3.13 / Streamlit 1.67.0; final UI checks are repeated after presentation refinements. Static analysis and source checks pass. The 500-sequence benchmark measured 2.92 s for a cold recommendation, 0.08 s after priority changes, 0.92 s after supply changes, 19.84 s for cold full tipping and 0.03 s cached. Timing depends on hardware and compilation state. Machine-readable reports are generated under ignored output/.

## Remaining limitations

Farm supply, actual local budgets, agronomic calibration and measurement quotes cannot be established from public records alone. They remain labeled assumptions or optional local inputs. Weak validation remains visible; the app is decision support, not a guarantee.

Public hosting, mobile/browser visual review and a Docker image build still require their own verification; this audit does not claim them. Repository publishing does not authorize a Space Apps portal submission or external communications. Never include village locations, personal names, emails or keys in app artifacts.
