# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Display-only helpers for the v4 public engine contract; no model calculations."""
from dataclasses import fields, is_dataclass
import math

ACRES_PER_HECTARE = 2.4710538147
DEMO_SITES = (
    ('Corn Belt · Iowa', 42.03, -93.62),
    ('Great Plains · Kansas', 38.85, -99.33),
    ('Southeast · Georgia', 31.45, -83.51),
)

def record(value):
    if is_dataclass(value):
        return dict(vars(value))
    return value if isinstance(value, dict) else {}

def area_value(per_hectare, metric=False):
    return float(per_hectare) if metric else float(per_hectare) / ACRES_PER_HECTARE

def provenance(value):
    text = str(value).strip().lower()
    if any(word in text for word in ('example', 'stub', 'placeholder', 'mock')):
        return 'EXAMPLE DATA'
    return {'observed': 'Observed', 'local': 'Your input', 'input': 'Your input',
            'your input': 'Your input', 'assumption': 'Assumption'}.get(text, 'Estimated')

def contains_example(value):
    if is_dataclass(value):
        value = record(value)
    if isinstance(value, dict):
        return any(contains_example(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_example(v) for v in value)
    return isinstance(value, str) and provenance(value) == 'EXAMPLE DATA'

def input_errors(site, crops, acres, mode, source, normal, dry, overrides):
    errors = []
    if len(crops) != 4 or any(not c.strip() for c in crops):
        errors.append('Choose the current crop for each of the four years.')
    if not finite_number(acres) or acres <= 0:
        errors.append('Enter a farm size greater than zero.')
    if mode == 'irrigated' and (not source.strip() or normal is None or dry is None):
        errors.append('Enter the irrigation source and normal-year and dry-year supply.')
    elif mode == 'irrigated' and (not finite_number(dry) or not finite_number(normal) or dry < 0 or normal < 0 or dry > normal):
        errors.append('Dry-year supply must be between zero and normal-year supply.')
    s = record(site)
    defaults = record(s.get('us_defaults'))
    us = str(s.get('country', '')).upper() in ('US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA')
    if us and s.get('us_state') in ('AK', 'HI', 'Alaska', 'Hawaii'):
        errors.append('Alaska and Hawaii are not supported in this version.')
    for crop in set(crops):
        if not crop:
            continue
        for field, default_key in (('yield', 'yields'), ('price', 'prices'), ('cost', 'costs')):
            val = overrides.get(crop, {}).get(field)
            same_currency = not s.get('currency') or str(s['currency']).upper() == 'USD' or field == 'yield'
            if val is None and us and same_currency:
                val = (defaults.get(default_key) or {}).get(crop)
            if isinstance(val, dict):
                val = val.get('value')
            if not finite_number(val) or val < 0:
                errors.append(f'Enter {field} for {crop}; no usable default is available.')
    return errors

def currency(site):
    s = record(site)
    if s.get('currency'):
        return s['currency']
    country = str(s.get('country', '')).upper()
    return {'US': 'USD', 'USA': 'USD', 'UNITED STATES': 'USD', 'INDIA': 'INR', 'IN': 'INR'}.get(country, 'local currency')


def finite_number(value):
    """Reject unavailable and non-finite values before formatting or validation."""
    from numbers import Real
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def guardrail_allows(rec, tolerance_pct):
    """Display safety check: never promote a headline that contradicts its baseline."""
    r = record(rec)
    headline, baseline = record(r.get('headline')), record(r.get('current_plan_result'))
    value, current = headline.get('mean_profit'), baseline.get('mean_profit')
    if not r.get('guardrail_met') or not finite_number(value) or not finite_number(current):
        return False
    # Tolerance is a permitted loss, including when baseline profit is negative.
    minimum = current - abs(current) * float(tolerance_pct) / 100
    return value >= minimum - 1e-9


def badge_labels(value):
    if isinstance(value, dict):
        return {label for v in value.values() for label in badge_labels(v)}
    if isinstance(value, (list, tuple)):
        return {label for v in value for label in badge_labels(v)}
    return {provenance(value)} if value is not None else set()
