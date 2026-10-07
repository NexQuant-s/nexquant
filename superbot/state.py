import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Set

log = logging.getLogger("state_manager")

class StateManager:
    """
    Gestionnaire de persistance d'état du SuperBot (Phase 2.4).
    Gère la sauvegarde et le chargement des états critiques (blocages, PnL de session, compteurs)
    pour survivre aux redémarrages.
    """
    def __init__(self, filepath: str, ttl_hours: int = 24):
        self.filepath = filepath
        self.ttl_hours = ttl_hours
        self._lock = threading.Lock()
        
        # Variables d'état
        self.failed_execution_cooldowns: Dict[str, float] = {}
        self.blocked_symbols: Set[str] = set()
        self.session_pnl_by_symbol: Dict[str, float] = {}
        self.consecutive_losses: Dict[str, int] = {}
        self.adaptation_counter: int = 0
        self.is_paused: bool = False
        self.day_start_balance: float = 0.0
        self.last_daily_reset_str: str = ""
        
    def load_state(self):
        """Charge l'état depuis le disque et purge si le TTL est dépassé."""
        if not os.path.exists(self.filepath):
            log.info("Aucun fichier d'état trouvé, démarrage à zéro.")
            return
            
        with self._lock:
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    
                last_update_str = data.get("last_update", "")
                if last_update_str:
                    last_update = datetime.fromisoformat(last_update_str)
                    if datetime.now() - last_update > timedelta(hours=self.ttl_hours):
                        log.info(f"État obsolète (dernière màj > {self.ttl_hours}h), purge effectuée.")
                        return  # On garde l'état initial vide
                
                self.failed_execution_cooldowns = data.get("failed_execution_cooldowns", {})
                self.blocked_symbols = set(data.get("blocked_symbols", []))
                self.session_pnl_by_symbol = data.get("session_pnl_by_symbol", {})
                self.consecutive_losses = data.get("consecutive_losses", {})
                self.adaptation_counter = data.get("adaptation_counter", 0)
                self.is_paused = data.get("is_paused", False)
                self.day_start_balance = data.get("day_start_balance", 0.0)
                self.last_daily_reset_str = data.get("last_daily_reset_str", "")
                
                log.info(f"État restauré avec succès depuis {self.filepath}.")
            except Exception as e:
                log.warning(f"Erreur lors du chargement de l'état : {e}")
                
    def save_state(self, failed_cooldowns: Dict[str, float],
                   blocked: Set[str],
                   session_pnl: Dict[str, float],
                   consecutive: Dict[str, int],
                   adaptation: int,
                   is_paused: bool = False,
                   day_start_balance: float = 0.0,
                   last_daily_reset_str: str = ""):
        """Met à jour l'état interne et sauvegarde sur le disque."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with self._lock:
            self.failed_execution_cooldowns = failed_cooldowns
            self.blocked_symbols = blocked
            self.session_pnl_by_symbol = session_pnl
            self.consecutive_losses = consecutive
            self.adaptation_counter = adaptation
            self.is_paused = is_paused
            self.day_start_balance = day_start_balance
            self.last_daily_reset_str = last_daily_reset_str
            
            data = {
                "last_update": datetime.now().isoformat(),
                "failed_execution_cooldowns": self.failed_execution_cooldowns,
                "blocked_symbols": list(self.blocked_symbols),
                "session_pnl_by_symbol": self.session_pnl_by_symbol,
                "consecutive_losses": self.consecutive_losses,
                "adaptation_counter": self.adaptation_counter,
                "is_paused": self.is_paused,
                "day_start_balance": self.day_start_balance,
                "last_daily_reset_str": self.last_daily_reset_str
            }
            try:
                # Écriture atomique : un arrêt brutal ne laisse jamais un fichier tronqué
                tmp_path = self.filepath + '.tmp'
                with open(tmp_path, 'w') as f:
                    json.dump(data, f)
                os.replace(tmp_path, self.filepath)
            except Exception as e:
                log.warning(f"Erreur lors de la sauvegarde de l'état : {e}")

    def clear_state(self):
        """Réinitialise complètement l'état persistant."""
        with self._lock:
            self.failed_execution_cooldowns.clear()
            self.blocked_symbols.clear()
            self.session_pnl_by_symbol.clear()
            self.consecutive_losses.clear()
            self.adaptation_counter = 0
            self.is_paused = False
            self.day_start_balance = 0.0
            self.last_daily_reset_str = ""
            if os.path.exists(self.filepath):
                try:
                    os.remove(self.filepath)
                    log.info(f"Fichier d'état supprimé : {self.filepath}")
                except Exception as e:
                    log.warning(f"Erreur suppression état : {e}")

