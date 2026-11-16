# Design

The global planner uses `ui/planner_style.py` and `.streamlit/config.toml`. The older Nalgonda screens retain `ui/theme.py`. Both favor a light, readable interface for a farmer using a phone in daylight.

## Current global planner

- Warm off-white canvas (`#f7f9f6`), white cards, dark green ink (`#20342e`), muted text (`#586b63`) and a restrained forest accent (`#236653`). System sans-serif fonts; no external font request.
- One shared style injected by `app.py`, with semantic Streamlit test IDs and explicit `rl_` container keys. No generated CSS classes, JavaScript, or replacement widget behavior.
- A compact brand and planning steps in the sidebar. Native sidebar controls remain available on mobile. Form fields remain in the main content area.
- Clear page introductions, consistent spacing, 14px card corners, quiet borders, and a stronger top border for the recommended plan.
- The welcome panel leads to farm setup; three editable examples follow. Setup is organized into location, crops, and water sections.
- One primary recommendation with profit, bad-year profit, and soil metrics. Water and food remain visible in its caption; the complete five-measure comparison is in an expander. Two compact alternatives sit side by side on desktop and stack through native Streamlit columns on small screens. Repeated summary metric cards are removed.
- Chart units, provenance badges, validation warnings, modeled-estimate disclaimers, and unknown-data states stay intact. Supporting background notes use an expander.
- Buttons and tabs have 44px minimum targets, visible keyboard focus, and restrained transitions that respect reduced-motion preferences. Mobile styles reduce padding and scale headings and numbers.
- Automated UI flows are checked separately from visual browser QA. Do not claim a viewport was visually verified without an available browser.

## Legacy Nalgonda design

The following records the original theme and design references for the legacy screens.

## Color (OKLCH)
- bg `0.972 0.008 135` paddy mist, surface `0.993 0.004 135`, line `0.87 0.016 140`
- ink `0.24 0.035 220` monsoon slate (body), ink2 `0.40 0.03 220` (secondary), ash `0.49 0.025 220` (captions)
- accent `0.45 0.085 205` monsoon water
- Crops (categorical, fixed order, validated with the dataviz CVD check): rice water blue `0.46 0.10 240`, jowar ochre `0.76 0.15 85`, bajra clay `0.46 0.13 30`, pigeon pea leaf `0.70 0.15 150`
- Tipping grid winners are coloured by rice share (blue = rice every year through ochre = no rice).
- Placeholder badge is yellow `0.90 0.13 95` with dark ink.

## Type
Fraunces (display, big numbers) with Source Sans 3 (body), via Google Fonts. Tabular numerals on stats. Body max 70ch.

## Components
Provenance badge (distinct glyph per kind), stat row (ruled, not carded), rotation ribbon (one block per plan year), dark recommendation panel, single-level panels only, plain tab underline nav.

## Charts
No modebar, 1px recessive grid, direct labels or a colour key above the chart, hover tooltips in plain language, a table view for the main charts.

## Reference studied (taste capture)
Our World in Data, "Cereal yields" grapher page, captured in a real browser at 1440x900 (screenshot plus computed styles). A condensed capture: DOM style sampling and a screenshot, not the full four-step written analysis.
Measured: serif title 25px/600 (Playfair Display) over a Lato 16px body; one plain sentence under the title that states the unit; chart in a 1px hairline frame; axis text 12px grey 91,91,91; sequential map ramp from pale yellow rgb(255,255,229) to deep green; a dedicated "No data" swatch; a "Data source" and "Note" footer under every chart; a segmented Table / Map / Line / Bar control.
Adapted, not copied: charts sit in hairline frames with 12px axis text; every chart has a Source or Note footer; each section opens with a title plus a one-line unit sentence; crop and rotation controls are segmented; missing data gets a dashed "No validation data" panel. Palette, type pairing and layout stay RotationLab's own.

## Second reference studied (taste capture)
farmers.gov home page, full four-step capture in `docs/design/farmers.gov.md` and `.json`. Adapted, not copied: the accent only on interactive elements, an 18px body with a modest headline, one container recipe, and actions named in plain words. Palette and type pairing stay RotationLab's own.
