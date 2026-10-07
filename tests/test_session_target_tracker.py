"""
tests/test_session_target_tracker.py
Tests unitaires pour le traqueur d'objectif de session journalière (Cible 35€ - 40€).
"""
from superbot.brain.session_target_tracker import SessionTargetTracker
from superbot.risk.risk_manager import RiskManager
from superbot.broker.symbol_specs import get_asset_class


def test_session_target_tracker_progress():
    tracker = SessionTargetTracker(start_balance=15.0, target_min=35.0, target_max=40.0)
    assert tracker.get_progress_pct() == 0.0
    assert tracker.get_remaining_amount() == 20.0
    assert tracker.goal_reached is False

    # Progression à 25€ (mi-chemin vers 35€ : 10€ gagnés sur 20€ visés = 50%)
    tracker.update(balance=25.0, equity=25.0)
    assert tracker.get_progress_pct() == 50.0
    assert tracker.get_remaining_amount() == 10.0
    assert tracker.goal_reached is False

    # Atteinte de l'objectif à 35€
    tracker.update(balance=35.5, equity=36.0)
    assert tracker.get_progress_pct() == 105.0
    assert tracker.get_remaining_amount() == 0.0
    assert tracker.goal_reached is True
    assert tracker.goal_reached_at is not None


def test_session_target_tracker_standard_account():
    # Sur un compte standard de 1000€, l'objectif est d'atteindre +35€ (1035€)
    tracker = SessionTargetTracker(start_balance=1000.0, target_min=35.0, target_max=40.0)
    assert tracker.effective_target_min == 1035.0
    assert tracker.effective_target_max == 1040.0
    assert tracker.get_progress_pct() == 0.0
    assert tracker.get_remaining_amount() == 35.0

    # Progression avec gain de 17.5€ (50% de l'objectif de gain)
    tracker.update(balance=1000.0, equity=1017.5)
    assert tracker.get_progress_pct() == 50.0
    assert tracker.get_remaining_amount() == 17.5
    assert tracker.goal_reached is False

    # Objectif atteint à 1035€
    tracker.update(balance=1035.0, equity=1035.0)
    assert tracker.get_progress_pct() == 100.0
    assert tracker.goal_reached is True


def test_micro_account_position_sizing_allows_oil_and_gold():
    config = {
        'RISK_PCT': 1.0,
        'MAX_OPEN_POSITIONS': 5,
        'MAX_DAILY_LOSS_PCT': 3.0,
        'ENABLE_LOSS_LIMIT': False,
        'KELLY_FRACTION': 0.05,
    }
    rm = RiskManager(config)
    rm.ENABLE_LOSS_LIMIT = False

    class FakeBroker:
        def get_min_order_size(self, symbol): return 0.01
        def get_step_size(self, symbol): return 0.01
        def get_account_summary(self): return {'free_margin': 12.0, 'leverage': 500}
        def calculate_margin(self, symbol, size, price, side): return 1.50

    broker = FakeBroker()
    # Sur un compte de 15.73€, 0.01 lot de pétrole (XTIUSD) à 95.80 avec SL à 96.18 (diff 0.38)
    # avec risk_per_unit ~2.50€ (environ 16% de 15.73€)
    size, details = rm.calculate_position_size(
        account_balance=15.73,
        entry_price=95.80,
        stop_loss=96.18,
        symbol="XTIUSD",
        broker=broker,
    )
    # Doit autoriser au moins 0.01 lot (sans être rejeté par la limite 10%)
    assert size >= 0.01
    assert 'error' not in details


def test_commodity_spread_check_accepts_oil_and_metals():
    # Vérifier que get_asset_class commence bien par commodity
    assert get_asset_class("XBRUSD").startswith("commodity")
    assert get_asset_class("XTIUSD").startswith("commodity")
    assert get_asset_class("XAUUSD").startswith("commodity")
    assert get_asset_class("XAGUSD").startswith("commodity")
    assert get_asset_class("XNGUSD").startswith("commodity")
