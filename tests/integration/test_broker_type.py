from unittest.mock import MagicMock, patch

import pytest

from superbot.orchestrator import SuperBot


@pytest.fixture
def cloud_bot():
    """SuperBot complet dont le cloud renvoie un broker différent du `.env` (mt5)."""
    fake_telemetry = MagicMock()
    fake_telemetry.enabled = True
    fake_telemetry.sync_config.return_value = {
        "ok": True,
        "is_expired": False,
        "config": {"risk_pct": 1.5, "score_min": 5.0, "is_running": True},
        "broker": {"broker_type": "binance", "api_key": "k", "api_secret": "s"},
        "update": {"available": False},
    }

    with patch("superbot.orchestrator.create_broker") as mock_create_broker:
        mock_broker = MagicMock()
        mock_broker.get_asset_type.return_value = "crypto"
        mock_broker.get_balance.return_value = 10000.0
        mock_broker.get_account_summary.return_value = {"equity": 10000.0}
        mock_broker.get_default_instruments.return_value = ["BTC/USDT"]
        mock_create_broker.return_value = mock_broker

        with patch("superbot.orchestrator.telemetry_client", fake_telemetry), \
             patch("superbot.orchestrator.ENABLE_DASHBOARD", False), \
             patch("superbot.orchestrator.WEBHOOK_ENABLED", False):
            bot = SuperBot()
            # Les multiplicateurs de session (risque/score selon l'heure UTC) passent désormais
            # par RuntimeConfig : on les neutralise pour un test indépendant de l'heure.
            bot.runtime_config.set_session_multipliers(risk_multiplier=1.0, score_offset=0)
            yield bot, mock_create_broker


def test_cloud_broker_type_not_clobbered(cloud_bot):
    bot, mock_create_broker = cloud_bot
    # Le broker renvoyé par le cloud (binance) ne doit pas être écrasé par le `.env` (mt5).
    assert bot.active_broker_type == "binance"
    assert bot.strategy.config["BROKER_TYPE"] == "binance"
    assert mock_create_broker.call_args[0][0] == "binance"


def test_cloud_adaptive_params_applied_at_init(cloud_bot):
    bot, _ = cloud_bot
    # Les valeurs cloud (risk_pct/score_min) sont propagées dès l'initialisation.
    assert bot.risk_manager.RISK_PCT == 1.5
    assert bot.strategy.score_min == 5.0
    assert bot.strategy.risk_per_trade == 1.5


def test_adaptive_setters_auto_propagate(cloud_bot):
    bot, _ = cloud_bot
    # Source unique de vérité : écrire sur les propriétés adaptatives doit
    # propager vers RiskManager / Strategy SANS appel manuel à _apply_adaptive_params.
    bot.adaptive_risk_pct = 2.0
    bot.adaptive_score_min = 7.0
    assert bot.risk_manager.RISK_PCT == 2.0
    assert bot.strategy.score_min == 7.0
    assert bot.strategy.risk_per_trade == 2.0
