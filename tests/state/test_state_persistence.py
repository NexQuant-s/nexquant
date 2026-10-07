import os
import tempfile
import json
from datetime import datetime, timedelta
from superbot.state import StateManager

def test_state_manager_save_and_load():
    """Vérifie que le StateManager sauvegarde et recharge correctement l'état."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        filepath = tmp.name
        
    try:
        manager = StateManager(filepath=filepath, ttl_hours=24)
        
        # Données de test avec les nouveaux champs persistés (Kill-Switch, solde journalier initial)
        manager.save_state(
            failed_cooldowns={"BTC/USDT": 1700000000.0},
            blocked={"ETH/USDT"},
            session_pnl={"BTC/USDT": 150.5},
            consecutive={"BTC/USDT": 3},
            adaptation=5,
            is_paused=True,
            day_start_balance=9500.0,
            last_daily_reset_str="2026-07-11T12:00:00"
        )
        
        # Nouveau manager pour charger
        manager2 = StateManager(filepath=filepath, ttl_hours=24)
        manager2.load_state()
        
        assert manager2.failed_execution_cooldowns == {"BTC/USDT": 1700000000.0}
        assert manager2.blocked_symbols == {"ETH/USDT"}
        assert manager2.session_pnl_by_symbol == {"BTC/USDT": 150.5}
        assert manager2.consecutive_losses == {"BTC/USDT": 3}
        assert manager2.adaptation_counter == 5
        assert manager2.is_paused is True
        assert manager2.day_start_balance == 9500.0
        assert manager2.last_daily_reset_str == "2026-07-11T12:00:00"
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

def test_state_manager_ttl_expiration():
    """Vérifie que l'état est purgé s'il est plus vieux que le TTL."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        filepath = tmp.name
        
    try:
        # Créer manuellement un fichier obsolète (vieux de 25h)
        old_time = (datetime.now() - timedelta(hours=25)).isoformat()
        data = {
            "last_update": old_time,
            "blocked_symbols": ["BTC/USDT"]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f)
            
        manager = StateManager(filepath=filepath, ttl_hours=24)
        manager.load_state()
        
        # Étant obsolète, l'état ne devrait pas être chargé
        assert manager.blocked_symbols == set()
        
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

def test_state_manager_corrupted_file():
    """Vérifie que le manager ne crashe pas si le fichier JSON est corrompu."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        filepath = tmp.name
        tmp.write(b"this is not a valid json")
        
    try:
        manager = StateManager(filepath=filepath, ttl_hours=24)
        manager.load_state()  # Ne doit pas raise d'exception
        
        assert manager.blocked_symbols == set()
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
