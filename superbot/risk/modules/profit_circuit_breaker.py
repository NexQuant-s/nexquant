"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TRAILING PROFIT CIRCUIT BREAKER — Protection des gains en série           ║
║                                                                              ║
║  Protège les gains d'une série gagnante contre un retournement brutal,        ║
║  indépendamment de la gestion de risque standard (2%/trade).                 ║
║                                                                              ║
║  Règles d'activation (Formulation 2) :                                       ║
║    - Déclencheur : s'active dès que le profit cumulé de la session          ║
║      atteint un pic ≥ PROFIT_CB_TRIGGER_EUR (défaut: 200 €).                 ║
║                                                                              ║
║    - Règle 1 (Pause 3h) : si le profit retombe à (1 - 0.25) × Pic,           ║
║      le bot est mis en pause d'exécution pour 3h. Il continue d'analyser     ║
║      le marché et de générer des signaux sans ouvrir de nouvelles positions. ║
║                                                                              ║
║    - Règle 2 (Arrêt Définitif) : après la reprise, si le profit retombe de   ║
║      nouveau de 25% par rapport au profit restant au moment de la reprise    ║
║      (nouveau plancher recalculé), le bot s'arrête définitivement.           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import logging
import time
from typing import Optional, TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from superbot.orchestrator import SuperBot

log = logging.getLogger("profit_circuit_breaker")


class ProfitCircuitBreaker:
    """
    Gestionnaire de coupe-circuit pour protéger les séries gagnantes.
    """

    def __init__(self, bot: "SuperBot", config: Optional[Dict[str, Any]] = None):
        self.bot = bot
        if config is None:
            try:
                import superbot.config as cfg
                config = {
                    "trigger_eur": getattr(cfg, "PROFIT_CB_TRIGGER_EUR", 200.0),
                    "retracement": getattr(cfg, "PROFIT_CB_RETRACEMENT", 0.25),
                    "pause_hours": getattr(cfg, "PROFIT_CB_PAUSE_HOURS", 3.0),
                    "stop_retracement": getattr(cfg, "PROFIT_CB_STOP_RETRACEMENT", 0.25),
                }
            except ImportError:
                config = {
                    "trigger_eur": 200.0,
                    "retracement": 0.25,
                    "pause_hours": 3.0,
                    "stop_retracement": 0.25,
                }

        self.trigger_eur = float(config.get("trigger_eur", 200.0))
        self.retracement = float(config.get("retracement", 0.25))
        self.pause_hours = float(config.get("pause_hours", 3.0))
        self.stop_retracement = float(config.get("stop_retracement", 0.25))

        # État interne
        self.is_active = False              # True dès que le pic ≥ trigger_eur
        self.peak_profit = 0.0              # Plus haut profit atteint de la session
        self.is_paused = False              # True pendant la pause de 3h (Règle 1)
        self.pause_end_time: Optional[float] = None
        self.has_paused_once = False        # True après avoir déclenché la Règle 1
        self.post_pause_ref_profit = 0.0    # Profit de référence lors de la reprise pour la Règle 2

        log.info(
            f"📈 ProfitCircuitBreaker initialisé | Déclencheur: +{self.trigger_eur}€ | "
            f"Retracement Pause: -{self.retracement*100:.0f}% ({self.pause_hours}h) | "
            f"Retracement Arrêt: -{self.stop_retracement*100:.0f}% du restant"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Vérification principale appelée à chaque cycle
    # ──────────────────────────────────────────────────────────────────────────

    def check(self, current_balance: float) -> bool:
        """
        Vérifie l'état du coupe-circuit en fonction du solde actuel du compte.

        Args:
            current_balance: Solde (ou équité) courant du compte

        Returns:
            True si les trades doivent être bloqués (en pause ou arrêté),
            False si le trading peut s'exécuter normalement.
        """
        initial_balance = getattr(self.bot, "initial_balance", 10000.0)
        if initial_balance <= 0:
            return False

        current_profit = current_balance - initial_balance

        # 1. Gestion de la fin de pause (Règle 1)
        if self.is_paused:
            if time.time() >= self.pause_end_time:
                self.is_paused = False
                self.has_paused_once = True
                # Règle 2 : le nouveau plancher est recalculé à partir du profit restant à la reprise
                self.post_pause_ref_profit = max(0.0, current_profit)
                log.warning(
                    f"▶️ [CircuitBreaker] Fin de la pause de {self.pause_hours}h. Reprise du trading. "
                    f"Nouveau profit de référence pour arrêt définitif : +{self.post_pause_ref_profit:.2f}€. "
                    f"Un retracement de {self.stop_retracement*100:.0f}% déclenchera l'arrêt du bot."
                )
            else:
                remaining_min = (self.pause_end_time - time.time()) / 60
                log.debug(f"⏸️ [CircuitBreaker] Pause active (reste {remaining_min:.0f} min). Trading suspendu.")
                return True

        # 2. Mise à jour du pic de profit
        if current_profit > self.peak_profit:
            self.peak_profit = current_profit
            # Activation du coupe-circuit si le pic dépasse le seuil (ex: 200€)
            if not self.is_active and self.peak_profit >= self.trigger_eur:
                self.is_active = True
                log.info(
                    f"🚀 [CircuitBreaker] ACTIVÉ ! Profit pic atteint: +{self.peak_profit:.2f}€ "
                    f"(seuil: +{self.trigger_eur}€). Protection active."
                )
            elif self.is_active:
                log.debug(f"📈 [CircuitBreaker] Nouveau pic de profit: +{self.peak_profit:.2f}€")

        # 3. Vérification des règles de déclenchement (si actif)
        if not self.is_active:
            return False

        # ── Règle 1 : Premier retracement → Pause de 3h ──────────────────────
        if not self.has_paused_once:
            threshold_profit = self.peak_profit * (1.0 - self.retracement)
            if current_profit <= threshold_profit:
                self.is_paused = True
                self.pause_end_time = time.time() + (self.pause_hours * 3600)
                log.warning(
                    f"⏸️ [CircuitBreaker] RÈGLE 1 DÉCLENCHÉE ! Retracement de {self.retracement*100:.0f}% "
                    f"depuis le pic (+{self.peak_profit:.2f}€ → +{current_profit:.2f}€ ≤ +{threshold_profit:.2f}€). "
                    f"Pause automatique du trading pour {self.pause_hours}h. L'analyse continue sans ordres."
                )
                return True

        # ── Règle 2 : Second retracement (après reprise) → Arrêt Définitif ───
        else:
            if self.post_pause_ref_profit > 0:
                stop_threshold = self.post_pause_ref_profit * (1.0 - self.stop_retracement)
                if current_profit <= stop_threshold:
                    log.critical(
                        f"🛑 [CircuitBreaker] RÈGLE 2 DÉCLENCHÉE ! Second retracement de {self.stop_retracement*100:.0f}% "
                        f"depuis la reprise (+{self.post_pause_ref_profit:.2f}€ → +{current_profit:.2f}€ ≤ +{stop_threshold:.2f}€). "
                        f"ARRÊT DÉFINITIF DU BOT ! Intervention manuelle requise."
                    )
                    try:
                        self.bot.stop()
                    except Exception as e:
                        log.error(f"Erreur lors de l'arrêt par CircuitBreaker: {e}")
                    return True

        return False

    def reset_daily(self):
        """Réinitialisation quotidienne si souhaitée."""
        if self.is_paused or self.has_paused_once:
            log.info("📅 [CircuitBreaker] Reset quotidien de l'état de protection.")
        self.is_active = False
        self.peak_profit = 0.0
        self.is_paused = False
        self.pause_end_time = None
        self.has_paused_once = False
        self.post_pause_ref_profit = 0.0
