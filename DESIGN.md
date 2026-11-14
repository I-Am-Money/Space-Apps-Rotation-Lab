# Design

Source of truth for tokens is `ui/theme.py` (OKLCH, converted to hex for Plotly). Scene: a farmer reading on a phone in daylight, so light theme, high contrast.

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
