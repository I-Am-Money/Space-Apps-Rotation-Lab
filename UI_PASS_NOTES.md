# Planner UI refresh

This supersedes the earlier `p3-ui-pass` layout notes. The requested visual overhaul adds a small shared CSS layer in `ui/planner_style.py`, injected once by the global app shell. Native Streamlit widgets still handle interaction and accessibility. Scientific code, datasets, and scoring are unchanged.

## Changes

- Shared warm neutral palette, forest accent, white cards, system typography, tabular numbers, and consistent spacing.
- Compact leaf brand and clearer sidebar navigation, with an active-step treatment and native mobile sidebar controls.
- Welcome panel with a primary action, three simple planning steps, and separate example-farm cards.
- Consistent page introductions and styled form sections across setup, plans, tipping points, measurement questions, and trust information.
- One prominent recommendation, two compact alternatives, and folded detailed comparisons. Removed the duplicate summary metric row; all five measures remain available.
- Shorter measurement metric values, with units on a separate line to avoid crowding.
- Lighter chart grids and a consistent comparison-chart palette. Existing markers, values, units, and warnings remain.
- Supporting result notes folded away; example-farm identification and validation warnings remain visible.
- Responsive padding and type, 44px button/tab targets, explicit focus styles, and reduced-motion support.

## Verification

The targeted automated UI suite passed: 46 tests covering setup, example farms, editable answers, unit switches, priority controls, recommendations, tipping points, measurement questions, and trust pages.

The full suite passed on Python 3.13: 513 passed, 3 skipped in 108.21 seconds. The 46 targeted UI tests were repeated after final presentation changes and passed again. Pyflakes on changed Python modules and `git diff --check` also passed.

Browser and native Chrome preview access were unavailable in this session. Automated UI checks do not establish visual correctness at desktop or phone widths. Existing screenshots predate this refresh and were not replaced with unverified images.

The earlier custom `inject_v5()` theme is not used by the global planner. Legacy screens retain their separate theme. See `DESIGN.md` for the current global planner design rules.
