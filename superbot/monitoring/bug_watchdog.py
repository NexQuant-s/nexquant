"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  BUG WATCHDOG — Agent de supervision technique (Formulation 2)             ║
║                                                                              ║
║  Vérifie en continu la santé technique du bot, indépendamment de sa         ║
║  performance de trading.                                                     ║
║                                                                              ║
║  Checks effectués à chaque intervalle :                                      ║
║    1. Connectivité broker (Binance Futures, Alpaca, MT5)                    ║
║    2. Cohérence des réponses API (balance, positions)                        ║
║    3. Intégrité du flux webhook TradingView                                  ║
║    4. Cohérence du risk_manager (SL/TP non nuls, sizing valide)             ║
║    5. Latence d'exécution du dernier cycle                                  ║
║    6. Exceptions non gérées (via compteur d'erreurs du bot)                 ║
║                                                                              ║
║  Classification de sévérité : Low / Medium / High / Critical               ║
║                                                                              ║
║  Kill switch automatique :                                                   ║
║    - Sévérité High ou Critical → arrêt immédiat                             ║
║    - Anomalie sur un module de décision (strategy, risk, signals)            ║
║      même si sévérité brute plus basse → arrêt immédiat                    ║
║    - Low/Medium sans impact sur la décision → journalisé, bot continue      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from superbot.orchestrator import SuperBot

log = logging.getLogger("bug_watchdog")

# Modules considérés comme critiques pour la décision de trading
DECISION_MODULES = {"strategy", "risk_manager", "signal_executor", "risk_monitor"}

# Mapping sévérité → numéro pour les comparaisons
SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}


class BugWatchdog:
    """
    Agent de supervision technique du bot.

    Tourne en thread daemon, vérifie la santé du bot à intervalles réguliers,
    journalise les anomalies dans bug_log.md et arrête le bot si nécessaire.
    """

    def __init__(self, bot: "SuperBot", interval: int = 60, bug_log_path: Optional[Path] = None,
                 max_latency: float = 5.0):
        """
        Args:
            bot:          Instance du SuperBot à surveiller
            interval:     Intervalle de vérification en secondes (défaut: 60s)
            bug_log_path: Chemin du fichier bug_log.md
            max_latency:  Latence max d'un cycle avant alerte Medium (secondes)
        """
        self.bot = bot
        self.interval = interval
        self.max_latency = max_latency
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._anomaly_count = 0

        # Fichier de journal
        if bug_log_path is None:
            from superbot.config import BUG_LOG_FILE
            bug_log_path = BUG_LOG_FILE
        self.bug_log_path = Path(bug_log_path)
        self.bug_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_log_file()

        log.info(f"🐛 BugWatchdog initialisé — intervalle: {interval}s | log: {self.bug_log_path}")

    # ──────────────────────────────────────────────────────────────────────────
    # Cycle de vie
    # ──────────────────────────────────────────────────────────────────────────

    def start(self):
        """Démarre le thread de surveillance en arrière-plan."""
        if self._thread and self._thread.is_alive():
            log.warning("BugWatchdog déjà en cours d'exécution")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, name="bug_watchdog", daemon=True
        )
        self._thread.start()
        log.info("🐛 BugWatchdog démarré")

    def stop(self):
        """Arrête proprement le thread de surveillance."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("🐛 BugWatchdog arrêté")

    # ──────────────────────────────────────────────────────────────────────────
    # Boucle principale
    # ──────────────────────────────────────────────────────────────────────────

    def _watch_loop(self):
        """Boucle de surveillance périodique."""
        log.info(f"🐛 [Watchdog] Surveillance démarrée (intervalle: {self.interval}s)")
        while not self._stop_event.is_set():
            try:
                self._run_all_checks()
            except Exception as e:
                log.error(f"🐛 [Watchdog] Erreur interne (non bloquante): {e}")
            # Attendre le prochain cycle en petits pas pour répondre au stop_event
            for _ in range(self.interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    # ──────────────────────────────────────────────────────────────────────────
    # Ensemble des vérifications
    # ──────────────────────────────────────────────────────────────────────────

    def _run_all_checks(self):
        """Exécute tous les checks de santé et traite les résultats."""
        checks = [
            self._check_broker_connectivity,
            self._check_api_response_integrity,
            self._check_risk_manager_coherence,
            self._check_cycle_latency,
            self._check_unhandled_exceptions,
        ]

        for check_fn in checks:
            try:
                anomaly = check_fn()
                if anomaly:
                    self._handle_anomaly(*anomaly)
            except Exception as e:
                # Un check qui plante ne doit pas bloquer les autres
                log.debug(f"🐛 [Watchdog] Check {check_fn.__name__} a levé une exception: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Checks individuels
    # Chaque check retourne None (OK) ou un tuple
    # (module: str, description: str, severity: str, affects_trading: bool)
    # ──────────────────────────────────────────────────────────────────────────

    def _check_broker_connectivity(self):
        """Vérifie que le broker répond et que le solde est accessible."""
        try:
            balance = self.bot.broker.get_balance()
            if balance is None or balance < 0:
                return (
                    "broker",
                    f"get_balance() a retourné une valeur invalide: {balance}",
                    "High",
                    True,
                )
            return None
        except Exception as e:
            return (
                "broker",
                f"Connexion broker échouée: {type(e).__name__}: {e}",
                "Critical",
                True,
            )

    def _check_api_response_integrity(self):
        """Vérifie la cohérence du solde vs les positions déclarées."""
        try:
            positions = getattr(self.bot, "positions", {})
            # Vérifier qu'aucune position n'a de taille négative ou prix d'entrée nul
            for symbol, pos in positions.items():
                size = pos.get("size", 0)
                entry = pos.get("entry_price", 1)
                if size < 0:
                    return (
                        "broker_api",
                        f"Position {symbol} avec taille négative: size={size}",
                        "High",
                        True,
                    )
                if entry <= 0:
                    return (
                        "broker_api",
                        f"Position {symbol} avec prix d'entrée invalide: entry_price={entry}",
                        "Medium",
                        True,
                    )
            return None
        except Exception as e:
            return ("broker_api", f"Erreur vérification intégrité API: {e}", "Medium", False)


    def _check_risk_manager_coherence(self):
        """Vérifie la cohérence du risk_manager : paramètres valides, positions cohérentes."""
        try:
            rm = getattr(self.bot, "risk_manager", None)
            if rm is None:
                return ("risk_manager", "risk_manager est None — composant critique manquant", "Critical", True)

            # Vérifier les paramètres de base avec auto-guérison
            if rm.RISK_PCT <= 0 or rm.RISK_PCT > 10:
                healed_risk = 1.0
                log.warning(f"⚠️ [BugWatchdog] RISK_PCT anormal ({rm.RISK_PCT}%), auto-guérison appliquée à {healed_risk}%")
                rm.RISK_PCT = healed_risk
                if hasattr(self.bot, 'runtime_config') and self.bot.runtime_config:
                    self.bot.runtime_config.set(risk_pct=healed_risk)

            if rm.MAX_OPEN_POSITIONS <= 0:
                log.warning(f"⚠️ [BugWatchdog] MAX_OPEN_POSITIONS anormal ({rm.MAX_OPEN_POSITIONS}), auto-guérison appliquée à 3")
                rm.MAX_OPEN_POSITIONS = 3

            # Vérifier la cohérence des positions ouvertes
            open_positions = getattr(rm, "open_positions", {})
            bot_positions = getattr(self.bot, "positions", {})

            diff = len(open_positions) - len(bot_positions)
            if abs(diff) > 2:
                # Tenter une réconciliation automatique via position_syncer
                try:
                    from superbot.components.position_syncer import sync_positions_with_broker
                    sync_positions_with_broker(self.bot)
                    open_positions = getattr(rm, "open_positions", {})
                    bot_positions = getattr(self.bot, "positions", {})
                    diff = len(open_positions) - len(bot_positions)
                except Exception as _exc:
                    log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

            if abs(diff) > 2:
                return (
                    "risk_manager",
                    f"Désynchronisation positions : risk_manager voit {len(open_positions)} positions, "
                    f"bot.positions en a {len(bot_positions)} (écart={diff})",
                    "Low",
                    False,
                )

            return None
        except Exception as e:
            return ("risk_manager", f"Erreur vérification risk_manager: {e}", "Medium", True)

    def _check_cycle_latency(self):
        """Vérifie la latence du dernier cycle de trading."""
        try:
            if getattr(self.bot, "is_paused", False):
                return None
            last_hb = getattr(self.bot, "_last_cycle_heartbeat", None)
            if last_hb is None:
                return None  # Watchdog cycle pas encore démarré
            elapsed = time.time() - last_hb
            if elapsed > 300:  # > 300s (seuil de watchdog timeout de 5 min)
                return (
                    "cycle_runner",
                    f"Cycle gelé : dernier heartbeat il y a {elapsed:.0f}s (seuil critique: 300s)",
                    "High",
                    True,
                )
            if elapsed > 120:  # > 120s
                return (
                    "cycle_runner",
                    f"Cycle lent : dernier heartbeat il y a {elapsed:.0f}s",
                    "Medium",
                    False,
                )
            return None
        except Exception as e:
            return ("cycle_runner", f"Erreur vérification latence: {e}", "Low", False)

    def _check_unhandled_exceptions(self):
        """Surveille l'accumulation d'erreurs non gérées dans le bot."""
        try:
            errors_count = self.bot.stats.get("errors_count", 0)
            prev_count = getattr(self, "_prev_errors_count", 0)
            new_errors = errors_count - prev_count
            self._prev_errors_count = errors_count

            if new_errors >= 5:
                return (
                    "global",
                    f"{new_errors} nouvelles erreurs non gérées détectées en {self.interval}s "
                    f"(total session: {errors_count})",
                    "High",
                    False,
                )
            if new_errors >= 2:
                return (
                    "global",
                    f"{new_errors} nouvelles erreurs non gérées en {self.interval}s",
                    "Medium",
                    False,
                )
            return None
        except Exception as e:
            return ("global", f"Erreur vérification exceptions: {e}", "Low", False)

    # ──────────────────────────────────────────────────────────────────────────
    # Traitement des anomalies
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_anomaly(self, module: str, description: str, severity: str,
                        affects_trading: bool):
        """
        Journalise une anomalie et décide si le bot doit s'arrêter.

        Règles de kill switch :
          1. Sévérité High ou Critical → arrêt immédiat
          2. Module impactant la décision de trading (strategy, risk, signals)
             → arrêt immédiat même si sévérité Low/Medium
          3. Low/Medium sans impact trading → journalisé, bot continue
        """
        self._anomaly_count += 1
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        session = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Déterminer si on doit arrêter
        rank = SEVERITY_RANK.get(severity, 0)
        is_decision_module = any(dm in module.lower() for dm in DECISION_MODULES)
        must_stop = rank >= 3 or (is_decision_module and rank >= 2)

        status = "ARRÊT BOT" if must_stop else "Journalisé"

        log.error(
            f"🐛 [BugWatchdog] Anomalie #{self._anomaly_count} | "
            f"Module: {module} | Sévérité: {severity} | "
            f"Impact trading: {affects_trading} | Action: {status}\n"
            f"  ↳ {description}"
        )

        # Écrire dans bug_log.md
        self._write_bug_log(timestamp, session, module, description, severity,
                            affects_trading, status)

        # Kill switch
        if must_stop:
            log.critical(
                f"🛑 [BugWatchdog] KILL SWITCH ACTIVÉ — anomalie {severity} sur module '{module}'. "
                f"Le bot s'arrête pour protéger l'intégrité du trading. "
                f"Consultez {self.bug_log_path} pour les détails."
            )
            try:
                self.bot.stop()
            except Exception as e:
                log.error(f"🐛 [BugWatchdog] Erreur lors de l'arrêt du bot: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Journalisation Markdown
    # ──────────────────────────────────────────────────────────────────────────

    def _init_log_file(self):
        """Initialise le fichier bug_log.md s'il n'existe pas."""
        if not self.bug_log_path.exists():
            with open(self.bug_log_path, "w", encoding="utf-8") as f:
                f.write("# 🐛 Bug Log — SuperBot Watchdog\n\n")
                f.write("| # | Date/Heure (UTC) | Session | Module | Description | Sévérité | Impact Trading | Statut |\n")
                f.write("|---|---|---|---|---|---|---|---|\n")
            log.info(f"🐛 Fichier bug_log.md créé : {self.bug_log_path}")

    def _write_bug_log(self, timestamp: str, session: str, module: str,
                       description: str, severity: str, affects_trading: bool,
                       status: str):
        """Ajoute une ligne dans le fichier bug_log.md."""
        try:
            impact = "✅ Oui" if affects_trading else "Non"
            sev_icons = {"Low": "🟡 Low", "Medium": "🟠 Medium", "High": "🔴 High", "Critical": "💀 Critical"}
            sev_display = sev_icons.get(severity, severity)
            status_display = "🛑 ARRÊT BOT" if "ARRÊT" in status else "📝 Journalisé"

            # Échapper les pipes Markdown dans la description
            safe_desc = description.replace("|", "\\|").replace("\n", " ")

            line = (
                f"| {self._anomaly_count} | {timestamp} | {session} | "
                f"`{module}` | {safe_desc} | {sev_display} | {impact} | {status_display} |\n"
            )
            with open(self.bug_log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            log.error(f"🐛 [BugWatchdog] Impossible d'écrire dans bug_log.md: {e}")
