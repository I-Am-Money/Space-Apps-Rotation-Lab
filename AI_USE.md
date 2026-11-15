# AI use disclosure

RotationLab is a NASA Space Apps 2026 project (challenge: Field Shift). AI tools were used heavily, and this
page says where.

## Who wrote what

- **Code.** AI coding assistants wrote most of the code and tests while the team directed them. Each team member
  ran their own assistant on their own part of the repo, following the shared build spec. Two tools were used:
  - **Claude Code (Anthropic):** the simulation and tipping points, the recommendations and "what to measure"
    engine and pages, the US data, hindcast and trust page, and the docs.
  - **OpenAI Codex:** the version 4 app shell and farm setup (`app.py`, `ui/setup.py`, `ui/planner_model.py`,
    `ui/zones.py`), the site and data fetchers (`engine/site.py`, `engine/fetch_soilgrids.py`, `engine/fetch_gibs.py`,
    `engine/climate_card.py`, `engine/zones.py`), parts of `engine/economics.py`, `scripts/precache.py` and their
    tests. Line 1 of each of those files says so.
  The team chose what to build, checked the results, set the modeling rules and approved every merge.
- **Earlier India version (v3).** Claude Code built it. OpenAI Codex later helped with debugging, passing
  inputs through, caching, the irrigation-saving objective, tests and documentation.
- **Explanations in the app.** Claude (`claude-sonnet-5-5`, via the Anthropic API) writes the short
  plain-English explanation on each recommendation. It only gets computed numbers and crop names, sent as
  JSON. A guard pulls every number and crop name out of the reply. If any of them is not in the input
  (allowing for rounding), the reply is thrown away and a fixed template is used instead. With no API key the
  template is always used. Replies are cached by a hash of the input. Code: `engine/explain.py`.
- **Docs and project text.** Claude Code drafted the README, LIMITATIONS, DATA_SOURCES, this file and the
  draft project page and deck. The team edits them.

## What AI did not do

- AI did not make up any data. Weather, soil, yield, price and cost values come from the sources in
  `DATA_SOURCES.md`. Values nobody has verified are marked "team to verify" and carry a Placeholder or
  Assumption badge.
- AI-written text is never used as a model input, and validation uses no AI-generated yields.
- AI help does not show that the model is right for farming. See `LIMITATIONS.md`.
- No NASA endorsement is claimed.

## Header comment for every code file

Each code file starts with this line (the owner of each file adds it):

```python
# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
```

Files from the earlier version use the same idea in slightly different words ("written and revised by Claude
Code (Anthropic) under the team's direction"). Files written with OpenAI Codex say "written with OpenAI Codex
under the team's direction". Files that both tools worked on say "written with AI coding assistants (Claude Code
and OpenAI Codex)". A file a person wrote with no AI help should say so instead:
`# AI use: written by the team without AI assistance. See AI_USE.md.`

Every code file in the repo now starts with an AI-use line (checked 2026-11-15).

### US data and trust page (Feature 4)

Claude Code wrote `engine/fetch_nass.py`, `engine/fetch_ers.py`, `engine/us_rules.py`, `ui/trust.py`, the NASS
and weather wiring in `engine/hindcast.py` and `engine/correction.py`, their tests, and these docs, under the
team's direction. ERS costs and regions come from the ERS files listed in `DATA_SOURCES.md`. Tests that need
NASS data use synthetic records, labelled as synthetic in the test files. They are never used in the app.

### How these docs are put together

Each owner writes notes for LIMITATIONS, DATA_SOURCES and AI_USE in `docs/notes/person<N>.md`. Person 3
compiles them into the top-level files.
