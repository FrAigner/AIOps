"""MSTL-Dekomposition (Trend + taegliche/woechentliche Saisonalitaet) als
"echtes" ML-Gegenstueck zur handgebauten Lag-Mittelwert-Heuristik in
config/vmalert-rules.yaml. Laeuft parallel dazu, ersetzt sie nicht.

Kaltstart-Schwellen sind eine bewusst konservative Entscheidung dieses
Dienstes (statsmodels selbst macht dazu keine harte Vorgabe): eine
Dekomposition braucht mindestens zwei volle Zyklen der groessten Periode,
um Saisonalitaet ueberhaupt vom Trend zu trennen. Bei 15-Minuten-Aufloesung
sind das 2*96=192 Punkte (2 Tage) fuer ein Tagesmuster und 2*672=1344 Punkte
(14 Tage) fuer ein zusaetzliches Wochenmuster.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import MSTL

DAILY_PERIOD = 96  # 24h bei 15-Minuten-Schritten
WEEKLY_PERIOD = 672  # 7 Tage bei 15-Minuten-Schritten
MIN_POINTS_DAILY = 2 * DAILY_PERIOD
MIN_POINTS_WEEKLY = 2 * WEEKLY_PERIOD
BAND_WIDTH_SIGMA = 3


@dataclass
class ForecastResult:
    forecast: float
    upper: float
    lower: float
    cycles: int  # 0 = kein Modell, 1 = nur taeglich, 2 = taeglich+woechentlich


def decompose_and_score(series: pd.Series) -> ForecastResult | None:
    clean = series.dropna()
    if len(clean) < MIN_POINTS_DAILY:
        return None

    periods = [DAILY_PERIOD, WEEKLY_PERIOD] if len(clean) >= MIN_POINTS_WEEKLY else [DAILY_PERIOD]

    try:
        res = MSTL(clean, periods=periods).fit()
    except ValueError:
        return None

    # Der aktuellste Punkt ist bereits Teil der Dekomposition - trend+seasonal
    # an dieser Stelle IST der Erwartungswert "jetzt". Kein separater
    # Prognoseschritt in die Zukunft noetig, weil der Ist-Zustand bewertet
    # wird, nicht die Zukunft vorhergesagt wird.
    seasonal_cols = [c for c in res.seasonal.columns] if hasattr(res.seasonal, "columns") else []
    seasonal_now = sum(res.seasonal[c].iloc[-1] for c in seasonal_cols) if seasonal_cols else res.seasonal.iloc[-1]
    expected = float(res.trend.iloc[-1] + seasonal_now)

    # Streuung der Residuen ohne die letzte Stunde (4 Punkte), damit eine
    # bereits laufende Stoerung ihr eigenes Band nicht aufblaeht - dieselbe
    # Idee wie die "unless ALERTS firing"-Maske bei der bestehenden
    # Heuristik, hier vereinfacht: bei Tagen an Historie verschiebt eine
    # ausgeklammerte Stunde die Gesamtstreuung kaum.
    resid = res.resid
    resid_std = resid.iloc[:-4].std(ddof=1) if len(resid) > 4 else resid.std(ddof=1)
    if not np.isfinite(resid_std) or resid_std <= 0:
        resid_std = resid.std(ddof=1)
    if not np.isfinite(resid_std) or resid_std <= 0:
        resid_std = max(abs(expected) * 0.1, 1.0)  # letzter Rueckfall, verhindert Nullband

    return ForecastResult(
        forecast=max(expected, 0.0),
        upper=expected + BAND_WIDTH_SIGMA * resid_std,
        lower=max(expected - BAND_WIDTH_SIGMA * resid_std, 0.0),
        cycles=len(periods),
    )
