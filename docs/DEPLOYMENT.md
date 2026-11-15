# Deploying RotationLab

## Streamlit Community Cloud

1. Put the tested source and bundled public data in a repository you can write to.
2. Create a Streamlit Community Cloud app, select the repository/branch, set app.py as the entry point, and use Python 3.11. Install from requirements.txt.
3. No secrets are required. If desired, configure ANTHROPIC_API_KEY in the hosting secret/environment settings; never put it in source. ANTHROPIC_MODEL can override the documented default. Users opt in before computed totals are sent.
4. After deployment, open the public URL in a private window and check all five screens, both map modes, a supply override, a local-cost change, CSV downloads, the full tipping option and the no-key explanation. Verify narrow/mobile layout visually. Wake a sleeping app before any demonstration.

The default map and numerical calculations use bundled files. Online GIBS/basemap tiles need connectivity. Native compilation adds first-run latency; warm calculations are cached. Interactive tipping uses 150 seeded weather sequences, while the full option uses 500.

## Docker

```sh
docker build -t rotationlab .
docker run --rm -p 8501:8501 rotationlab
```

Open http://localhost:8501. The image exposes a Streamlit health check. The configuration is supplied; a container build was not executed in the task environment.

## Portable source bundle

```sh
python scripts/prepare_deploy.py
```

The ZIP and SHA-256 manifest appear in output/. It contains the app, required public caches, documentation and tests. Credentials, local farm-record files, model-response caches and virtual environments are excluded. Extract the bundle, create a virtual environment and follow README.md. Do not treat a successful local health check as proof that a public endpoint is reachable.

## Checks

GitHub Actions runs `python -m engine check-data` and `python -m pytest -q` on Python 3.11. Run those locally before deployment as well. `python -m engine report --output output/planning-report.json` exports a reproducible default planning/validation report; `python -m engine benchmark --scenarios 500 --include-tipping` records cold and cached timings.

Deployment does not authorize a Space Apps portal submission. Submit only after the team separately agrees and checks its links and disclosure text.
