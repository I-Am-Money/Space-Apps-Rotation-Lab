# AI use statement

RotationLab was built with AI assistance. This file says exactly where, so nobody has to guess.

## What AI did

| Part of the project | AI tool | What it did |
|---|---|---|
| Code in `app.py`, `engine/`, `ui/` and `tests/` | Claude (Anthropic), through Claude Code | Wrote and revised the code and the tests under the team's direction. Every code file carries a header comment that says so. |
| Documentation (`README.md`, `LIMITATIONS.md`, `HANDOFF.md`, `docs/`, this file) | Claude, through Claude Code | Drafted and revised the text. |
| Finding and reading sources | Claude, through Claude Code | Looked up and read the public sources listed in `docs/NASA_DATA.md`, `docs/INDIA_DATA.md` and the app's source list. Values it could not confirm in a source are marked "team to verify" and badged Assumption or Placeholder. |
| The short explanation on the Our Priorities tab | Claude, through the Anthropic API (optional) | When an `ANTHROPIC_API_KEY` is set, Claude writes 3 to 4 plain sentences from the numbers the model has already computed. It is told to use only those numbers and to add no facts. With no key, or if the call fails, the app writes the same explanation from a fixed template. The app says on screen which of the two wrote the text. |

## What AI did not do

- AI did not produce any of the data. Weather comes from NASA POWER, map layers from NASA GIBS, yields from a published panel built on ICRISAT district data, prices from the Government of India, soil from SoilGrids and from the farm owner. Sources and access dates are in `docs/`.
- AI did not make the decisions. The team chose the challenge, the farm, the crops, the baseline (rice every year), the rules of the tool and what to submit.
- No AI-generated images, video or audio are used in the app or the repository.
- No NASA logo, flag or mission identifier is used, and nothing here implies NASA endorsement.

## How to tell AI-written text in the app

The explanation card on the Our Priorities tab ends with one of two lines: "Written by Claude from the numbers on this page" or "Written from a fixed template using the numbers on this page". Everything else on screen is fixed text or a number from the model.

## For the team before submitting

If any other AI tool was used for the slides, the video, the subtitles or the project page, add it to the table above and to the AI field of the submission form.
