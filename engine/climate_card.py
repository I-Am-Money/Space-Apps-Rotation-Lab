# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Observed-weather comparison, with explicit team-defined season and rain-start conventions."""
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

CONFIG = Path(__file__).resolve().parents[1] / 'config/assumptions/setup.yaml'


def climate_trend(weather, lat):
    from engine.api import ClimateTrend
    cfg = yaml.safe_load(CONFIG.read_text())['climate_card']
    value = lambda name: cfg[name]['value']
    if not isinstance(weather.index, pd.DatetimeIndex) or weather.index.has_duplicates:
        raise ValueError('Climate card needs unique daily dates.')
    for field in ('precip', 'tmax'):
        if field not in weather or not np.isfinite(weather[field]).all() or (weather[field] <= -900).any():
            raise ValueError(f'Climate card needs valid daily {field}.')
    start = int(value('north_season_start_month') if lat >= 0 else value('south_season_start_month'))
    length = int(value('season_months'))
    full = []
    last = weather.index.max()
    for year in range(weather.index.min().year, last.year + 1):
        # Label a cross-calendar season by its harvest/end year.
        begin_year = year - int(start + length - 1 > 12)
        begin = pd.Timestamp(begin_year, start, 1)
        end = begin + pd.DateOffset(months=length) - pd.Timedelta(days=1)
        idx = pd.date_range(begin, end, freq='D')
        if not idx.isin(weather.index).all():
            continue
        frame = weather.loc[idx]
        rolling = frame.precip.rolling(int(value('onset_window_days'))).sum()
        wet = rolling[rolling >= float(value('onset_rain_mm'))]
        offset = None if wet.empty else (wet.index[0] - begin).days - int(value('onset_window_days')) + 1
        full.append({'year': year, 'rain': float(frame.precip.sum()),
                     'heat': float((frame.tmax >= float(value('heat_threshold_c'))).sum()),
                     'onset_doy': None if offset is None else float((begin + pd.Timedelta(days=offset)).dayofyear)})
    if not full:
        raise ValueError('No complete comparison seasons are available.')
    annual = pd.DataFrame(full).set_index('year')
    last_full = int(weather.attrs.get('last_full_year', last.year if (last.month, last.day) == (12, 31) else last.year - 1))
    early = (int(value('early_start')), int(value('early_end')))
    recent = (last_full - int(value('recent_years')) + 1, last_full)
    def period(bounds):
        sub = annual.loc[(annual.index >= bounds[0]) & (annual.index <= bounds[1])]
        if sub.empty:
            return (None, None, None, None, 0)
        rain = float(sub.rain.mean())
        cv = None if len(sub) < 2 or rain == 0 else float(sub.rain.std(ddof=1) / rain)
        onsets = sub.onset_doy.dropna()
        if onsets.empty:
            onset = None
        elif start + length - 1 <= 12:
            onset = float(onsets.mean())
        else:
            angles = 2 * np.pi * (onsets.to_numpy() - 1) / 365.25
            onset = float((np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()) % (2*np.pi)) * 365.25 / (2*np.pi) + 1)
        return rain, cv, float(sub.heat.mean()), onset, len(sub)
    a, b = period(early), period(recent)
    note = (f'Warm-season comparison: {length} months from month {start}; {a[4]} baseline and {b[4]} recent seasons available. '
            f'Rain-start proxy: first {value("onset_rain_mm")} mm in {value("onset_window_days")} days. '
            'Season/onset definitions are team assumptions, not a crop calendar or validated rainy-season onset. Not a forecast.')
    return ClimateTrend(early, recent, (a[0], b[0]), (a[1], b[1]), (a[2], b[2]), (a[3], b[3]),
                        heat_threshold_c=float(value('heat_threshold_c')), note=note,
                        badges={'season_rain_mm': 'estimated', 'rain_variability_cv': 'estimated',
                                'heat_days': 'estimated', 'rainy_season_start_doy': 'assumption'}, example=False)
