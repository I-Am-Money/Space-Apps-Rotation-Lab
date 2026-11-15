# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Create a reviewed source bundle; credentials and personal farm uploads are excluded."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "rotationlab-deploy.zip"
patterns = ["app.py", "pytest.ini", "requirements.txt", "Dockerfile", ".dockerignore", ".streamlit/config.toml", "README.md", "LIMITATIONS.md", "AI_USE.md", "HANDOFF.md", "PRODUCT.md", "DESIGN.md",
            "engine/*.py", "engine/*.md", "scripts/*.py", "ui/*.py", "ui/tabs/*.py", "config/*.yaml", "assets/favicon.svg", "assets/nalgonda_outline.json",
            "data/gibs_layers.json", "data/raw/power_*.json", "data/raw/soil_*.json", "data/raw/msp_*.html",
            "data/raw/icrisat_dld/*.csv", "data/raw/icrisat_dld/SOURCE.json", "docs/*.md", "tests/*.py", ".github/workflows/ci.yml"]
files = sorted({p for pattern in patterns for p in ROOT.glob(pattern) if p.is_file()})
OUTPUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
    for p in files:
        archive.write(p, str(p.relative_to(ROOT)))
manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(OUTPUT.parent / "deployment-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"{OUTPUT}: {len(files)} files, {OUTPUT.stat().st_size:,} bytes")
