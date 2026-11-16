# UI layout pass (branch `p3-ui-pass`)

Layout only. No change to `engine/`, numbers, data, config or tests. The five farmer pages now use built-in
Streamlit components only: no custom CSS, no `unsafe_allow_html`, no new theme colors.

Checked with the Python 3.11 venv: `pytest` 513 passed, 3 skipped (same as before the pass). The app was started
headless in offline mode (`ROTATIONLAB_OFFLINE=1`) and every page and tab was opened in a headless browser from an
example farm: no exceptions. Moving a slider shows new numbers in about 0.15 seconds.

## Every page (app shell, `app.py`)
- Side panel open by default: app name, page list, the controls of the open page, then the units switch,
  "Edit farm details" and "Start again". The page list used to be a CSS-styled row at the top.
- The theme CSS is no longer injected on these pages (`setup.style()` is now empty).
- The standing notes (disclaimer, example-farm note, accuracy check) are unchanged in wording. The disclaimer
  sentence is no longer printed twice on the pages that already print it under their heading.

## 1. Your farm (`ui/setup.py`)
- Start screen: the example farms sit in one bordered section.
- Farm form: the three steps (where, what you grow, farm and water) are each one bordered section.
- Data labels are drawn as built-in Streamlit badges, with the wording from `badge()`.
- The map pin uses the map library's default color.
- The form stays in the main area, not the side panel: it is a step-by-step form with a map and would not fit.

## 2. Best crop plans (`ui/recommendations.py`)
- The four sliders, the weather choice and the "most food" switch moved to the side panel.
- Three tabs: "Best plans", "Every plan we tested" (the chart), "Your climate" (the climate card, which used to
  sit above the plans).
- New row of three `st.metric` cards at the top, one per recommendation: average profit, with the difference
  from today's plan as the delta.
- Each plan is a bordered card: the four years as a small table, five `st.metric` cards with deltas (profit,
  bad-year profit, soil score, water, food), the plain sentence, and the full comparison table (open on the
  first card, folded on the others). Water use counts lower as better.
- The chart keeps its axis titles with units and now takes its colors from the Streamlit chart theme. The three
  plans are told apart by shape; the star is drawn on top when one plan wins two categories.

## 3. What could change it (`ui/tipping.py`)
- The headline findings and the climate setting sit in one bordered section at the top.
- The map and the three what-if charts each have their own tab (they used to be one long scroll). Headings,
  axis titles and chart colors are unchanged.
- Data labels no longer need HTML.

## 4. What to check first (`ui/measure.py`)
- The test-quote inputs moved to the side panel.
- Each question card shows the plain answer on the left and the value as a bordered `st.metric` on the right.

## Can I trust this? (`ui/trust.py`)
- Five tabs: Validation, Assumptions, Limitations, Data sources, AI use.
- Validation: new bar chart of the held-out r for each county and crop (the same numbers as the table), with
  axis titles. The table and the site map each have their own bordered section.
- Assumptions: four `st.metric` cards (listed values, published source, planning assumptions,
  "Placeholder (team to verify)"). The Placeholder labels stay in both tables.

## Shared (`ui/components.py`)
- `badge()` is unchanged. New `badge_md(kind)` takes the wording from `badge()` and returns a built-in Streamlit
  badge, so pages can show data labels without HTML.

## Left alone, for the reviewer to decide
- `.streamlit/config.toml` still has the earlier theme colors (teal buttons, pale green background). Nothing was
  added. Delete the `[theme]` color lines to get the stock Streamlit look.
- The old single-farm screens (`ui/legacy_app.py`, `ui/tabs/`, `ui/theme.py`) still use the CSS theme. They are not
  linked from the app and a test (`tests/test_app.py`) still renders them, so they were not touched.
- `assets/screens/*.png` are screenshots of the old layout.
