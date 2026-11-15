# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Verify NASS connectivity before a long pre-cache run; never print the key."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import api


def main():
    try:
        result = api.check_nass()
    except Exception as exc:
        # Even unexpected lower-level errors must not expose a credential-bearing URL.
        result = {'authenticated': False, 'status': 'unverified', 'error_type': type(exc).__name__,
                  'next_step': 'Check NASS_API_KEY in environment or .streamlit/secrets.toml, then retry from a network that reaches quickstats.nass.usda.gov.'}
        print(json.dumps(result))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
