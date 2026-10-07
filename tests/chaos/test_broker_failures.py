import pytest
from unittest.mock import patch
from superbot.orchestrator import SuperBot

class FakeBroker:
    def __init__(self):
        self.testnet = True
        self.account_type = "PAPER"
    def get_balance(self):
        return 10000.0
    def get_asset_type(self):
        return "crypto"
    def get_symbol_limits(self, symbol):
        return {'min_qty': 0.001, 'step_size': 0.001, 'max_qty': 1000.0, 'max_nominal': float('inf')}
    def get_leverage(self, symbol=None):
        return 1.0
    def get_free_margin(self):
        return 10000.0
    def get_symbol_info(self, symbol):
        return {'tick_size': 1.0, 'contract_size': 1.0}
    def get_min_order_size(self, symbol):
        return 0.001
    def place_order(self, *args, **kwargs):
        raise Exception("API Timeout (Simulé Chaos Engineering)")
    def get_account_summary(self):
        return {"equity": 10000.0}
    def get_position(self, symbol):
        return None
    def cancel_all_orders(self, symbol):
        pass
    def get_trade_history(self, days=1):
        return []
    def __getattr__(self, name):
        # Pour intercepter n'importe quel autre appel et renvoyer une valeur dummy
        if "size" in name or "min" in name or "max" in name or "step" in name:
            return lambda *a, **k: 0.001
        return lambda *a, **k: 1.0

@pytest.fixture
def mock_bot(monkeypatch):
    monkeypatch.setenv("BROKER_TYPE", "paper")
    fake = FakeBroker()
    with patch('superbot.orchestrator.create_broker', return_value=fake):
        bot = SuperBot()
        bot.broker = fake
        
        # Synchroniser le mock avec le risk manager
        if bot.risk_manager:
            bot.risk_manager.broker = bot.broker
        
        return bot

def test_broker_network_failure_handling(mock_bot):
    """
    Test 3.6.1 : Vérifie que le bot ne crashe pas si le broker renvoie
    une erreur réseau (Exception) lors du placement d'un ordre,
    et que le cooldown de 15 minutes est bien activé pour cet actif.
    """
    symbol = "BTC/USDT"
    signal_data = {
        "market_regime": "TRENDING",
        "total_score": 8.0,
        "should_long": True,
        "should_short": False,
        "rr_ratio": 2.5,
        "entry_price": 50000.0,
    }
    
    import pandas as pd
    df_with_indicators = pd.DataFrame([{
        'close': 50000.0,
        'atr': 1000.0,
        'rsi': 40
    }])
    
    from superbot.components.signal_executor import execute_signal_trade
    
    # 1. On lance le trade qui va déclencher l'Exception Chaos
    mock_bot.online_learner = None
    execute_signal_trade(mock_bot, symbol, signal_data, df_with_indicators)
    
    # 2. Assertions de survie
    # Le bot ne doit pas avoir planté l'application (pas d'exception remontée non catchée)
    assert mock_bot.stats['trades_executed'] == 0
    
    # 3. Le système immunitaire doit s'activer (Cooldown de 15 min pour BTC/USDT)
    assert symbol in mock_bot.failed_execution_cooldowns, "Le cooldown de protection n'a pas été activé après la panne API."
