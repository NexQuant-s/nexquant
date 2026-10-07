"""Tests du mode ombre ML et de l'extraction de features à partir du journal des trades."""

from unittest.mock import MagicMock

import pandas as pd

from superbot import config
from superbot.ml.online_learner import OnlineLearner
from superbot.ml.probabilistic_scorer import FEATURES_EXTENDED, _extract_extended_features


def _feature(vector, name):
    return vector[0][FEATURES_EXTENDED.index(name)]


def test_shadow_mode_enabled_by_default():
    assert config.ML_SHADOW_MODE is True


def test_extractor_uses_values_recorded_at_entry():
    row = pd.Series({"rsi": 72.0, "adx": 40.0, "bb_pos": 0.97, "atr_pct": 0.08,
                     "market_regime": "trending_bull", "hour_of_day": 13.0, "day_of_week": 2.0})
    x = _extract_extended_features(row, {})
    assert _feature(x, "bb_pos") == 0.97          # et non 0.5 recalculé sans close/bandes
    assert _feature(x, "atr_pct") == 0.08         # et non 0 faute de colonne 'atr'
    assert _feature(x, "regime_id") == 2.0        # régime du trade, pas 'ranging'
    assert _feature(x, "hour_of_day") == 13.0     # heure d'entrée, pas heure de clôture
    assert _feature(x, "day_of_week") == 2.0


def test_extractor_still_computes_from_live_bar():
    bar = pd.Series({"close": 1.10, "bb_upper": 1.12, "bb_lower": 1.08, "atr": 0.0011, "rsi": 50.0})
    x = _extract_extended_features(bar, {"regime": "ranging"})
    assert abs(_feature(x, "bb_pos") - 0.5) < 1e-9
    assert abs(_feature(x, "atr_pct") - 0.1) < 1e-9


def test_online_learner_ignores_unverified_trades():
    scorer = MagicMock()
    learner = OnlineLearner(scorer=scorer)
    learner.on_trade_closed({"symbol": "EURUSD", "pnl": -7.2, "verified": False}, df_row=pd.Series({"rsi": 50}))
    scorer.partial_fit.assert_not_called()

    learner.on_trade_closed({"symbol": "EURUSD", "pnl": 3.1, "verified": True}, df_row=pd.Series({"rsi": 50}))
    scorer.partial_fit.assert_called_once()
