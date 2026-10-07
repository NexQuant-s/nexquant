import requests
import hmac
import hashlib
import json
import logging
import os
import queue
import threading
from typing import Optional

log = logging.getLogger("telemetry")

class TelemetryClient:
    """
    Client de télémétrie pour connecter le bot local à la plateforme Web NexQuant.
    Gère la signature HMAC-SHA256, l'envoi asynchrone des données (ingest) 
    et la récupération synchrone de configuration/licence.
    """

    def __init__(self, api_url: Optional[str] = None, user_id: Optional[str] = None, ingest_token: Optional[str] = None):
        # Charger les configurations depuis .env si non passées en paramètres
        self.api_url = api_url or os.getenv("NEXQUANT_API_URL", "http://localhost:8080")
        self.user_id = user_id or os.getenv("NEXQUANT_USER_ID")
        self.ingest_token = ingest_token or os.getenv("NEXQUANT_INGEST_TOKEN")
        self.enabled = bool(self.user_id and self.ingest_token)

        # File d'attente et thread worker pour l'envoi asynchrone
        self._telemetry_queue = queue.Queue()
        self._worker_thread = None
        self._running = False

        if not self.enabled:
            log.warning("⚠️  Télémétrie désactivée : NEXQUANT_USER_ID ou NEXQUANT_INGEST_TOKEN non configuré dans .env")
        else:
            log.info(f"Télémétrie activée pour l'utilisateur {self.user_id} sur {self.api_url}")
            self._running = True
            self._worker_thread = threading.Thread(target=self._telemetry_worker, daemon=True, name="TelemetryWorker")
            self._worker_thread.start()

    def _sign_payload(self, payload_str: str) -> str:
        """Calcule la signature HMAC-SHA256 du corps de la requête."""
        if not self.ingest_token:
            return ""
        return hmac.new(
            self.ingest_token.encode('utf-8'),
            payload_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _post_immediate(self, endpoint: str, data: dict) -> Optional[dict]:
        """Envoie immédiatement une requête POST sécurisée et signée au serveur (synchrone/bloquant)."""
        if not self.enabled:
            return None

        url = f"{self.api_url.rstrip('/')}/api/public/{endpoint}"
        
        # Stringify le body de manière déterministe pour la signature
        body_str = json.dumps(data, separators=(',', ':'))
        signature = self._sign_payload(body_str)

        headers = {
            "Content-Type": "application/json",
            "x-user-id": self.user_id,
            "x-signature": signature
        }

        try:
            response = requests.post(url, data=body_str, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 403:
                log.error("❌ Licence expirée ou invalide. Le bot va être arrêté.")
                return {"error": "licence_expired", "is_expired": True}
            else:
                log.debug(f"Erreur d'ingestion [{response.status_code}] : {response.text}")
                return None
        except Exception as e:
            log.debug(f"Impossible de contacter le serveur de télémétrie : {e}")
            return None

    def _post_async(self, endpoint: str, data: dict) -> bool:
        """Ajoute la requête d'envoi de données à la queue asynchrone d'arrière-plan."""
        if not self.enabled:
            return False
        
        try:
            # Éviter la croissance infinie de la file d'attente si le serveur est injoignable
            if self._telemetry_queue.qsize() > 1000:
                try:
                    self._telemetry_queue.get_nowait()
                    self._telemetry_queue.task_done()
                except (queue.Empty, ValueError):
                    pass
            
            self._telemetry_queue.put((endpoint, data))
            return True
        except Exception:
            return False

    def _telemetry_worker(self):
        """Thread worker d'arrière-plan traitant la file d'attente de télémétrie."""
        while self._running:
            try:
                task = self._telemetry_queue.get(timeout=1.0)
                if task is None:
                    break
                
                endpoint, data = task
                try:
                    self._post_immediate(endpoint, data)
                except Exception as _exc:
                    log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
                finally:
                    self._telemetry_queue.task_done()
            except queue.Empty:
                continue
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

    def stop(self):
        """Arrête proprement le thread de télémétrie."""
        self._running = False
        if self._worker_thread:
            self._telemetry_queue.put(None)
            self._worker_thread.join(timeout=2.0)

    def push_heartbeat(self, is_running: bool, broker_type: str, testnet: bool, kelly_fraction: float = 0.0, news_sentiment: float = 0.0, fear_greed: float = 50.0, uptime_seconds: int = 0, regime: str = "", regime_confidence: float = 0.0, daily_achieved_eur: float = 0.0, daily_target_eur: float = 0.0, win_rate: float = 0.0, profit_factor: float = 1.0) -> bool:
        """Envoie un signal de présence (heartbeat) du bot de manière synchrone."""
        payload = {
            "kind": "heartbeat",
            "user_id": self.user_id,
            "payload": {
                "is_running": is_running,
                "broker_type": broker_type,
                "testnet": testnet,
                "kelly_fraction": float(kelly_fraction),
                "news_sentiment": float(news_sentiment),
                "fear_greed": float(fear_greed),
                "uptime_seconds": int(uptime_seconds),
                "regime": regime,
                "regime_confidence": float(regime_confidence),
                "daily_achieved_eur": float(daily_achieved_eur),
                "daily_target_eur": float(daily_target_eur),
                "win_rate": float(win_rate),
                "profit_factor": float(profit_factor)
            }
        }
        res = self._post_immediate("ingest", payload)
        return res is not None and not res.get("is_expired", False)

    def push_equity(self, equity: float, pnl_total: float = 0.0, drawdown: float = 0.0) -> bool:
        """Envoie une capture de la courbe d'équité de manière asynchrone."""
        payload = {
            "kind": "equity",
            "user_id": self.user_id,
            "payload": {
                "equity": float(equity),
                "pnl_total": float(pnl_total),
                "drawdown": float(drawdown)
            }
        }
        return self._post_async("ingest", payload)

    def push_position(self, symbol: str, side: str, qty: float, entry_price: float, current_price: float, pnl: float, pnl_pct: float, status: str = "open", broker: str = "mt5") -> bool:
        """Envoie les détails d'une position ouverte ou fermée de manière asynchrone."""
        payload = {
            "kind": "position",
            "user_id": self.user_id,
            "payload": {
                "symbol": symbol,
                "side": side.lower(),  # "long" ou "short"
                "qty": float(qty),
                "entry_price": float(entry_price),
                "current_price": float(current_price),
                "pnl": float(pnl),
                "pnl_pct": float(pnl_pct),
                "status": status,  # "open" ou "closed"
                "broker": broker
            }
        }
        return self._post_async("ingest", payload)

    def push_log(self, level: str, message: str, source: str = "engine") -> bool:
        """Envoie un log d'exécution pour affichage distant de manière asynchrone."""
        lvl_map = {
            "DEBUG": "debug",
            "INFO": "info",
            "WARNING": "warn",
            "ERROR": "error",
            "CRITICAL": "error",
            "SUCCESS": "success"
        }
        mapped_level = lvl_map.get(level.upper(), "info")

        payload = {
            "kind": "log",
            "user_id": self.user_id,
            "payload": {
                "level": mapped_level,
                "source": source,
                "message": message
            }
        }
        return self._post_async("ingest", payload)

    def push_regime(self, symbol: str, regime: str, confidence: float, trend_direction: str = "neutral", news_sentiment: float = 0.0) -> bool:
        """Envoie l'état du régime de marché de manière asynchrone."""
        payload = {
            "kind": "regime",
            "user_id": self.user_id,
            "payload": {
                "symbol": symbol,
                "regime": regime.lower(),  # "trending", "ranging", "volatile"
                "confidence": float(confidence),
                "trend_direction": trend_direction.lower(),  # "up", "down", "neutral"
                "news_sentiment": float(news_sentiment)
            }
        }
        return self._post_async("ingest", payload)

    def sync_config(self, current_version: str = "v1.0.0") -> Optional[dict]:
        """
        Récupère la configuration de trading, les clés API du broker et vérifie les mises à jour (synchrone).
        """
        if not self.enabled:
            return None

        payload = {
            "user_id": self.user_id,
            "version": current_version
        }
        
        return self._post_immediate("config", payload)


class TelemetryLoggingHandler(logging.Handler):
    """
    Handler de logging Python redirigeant automatiquement les logs significatifs
    vers l'API de télémétrie NexQuant.
    """
    def __init__(self, telemetry_client: TelemetryClient):
        super().__init__()
        self.telemetry_client = telemetry_client
        # Filtrer pour ne pousser que les événements importants (INFO, WARNING, ERROR, CRITICAL)
        self.setLevel(logging.INFO)

    def emit(self, record):
        try:
            # Éviter la récursion infinie
            if record.name in ("telemetry", "urllib3", "requests"):
                return
            
            message = self.format(record)
            self.telemetry_client.push_log(
                level=record.levelname,
                message=message,
                source=record.name
            )
        except Exception as _exc:
            log.debug(f"Erreur ignorée (non bloquante) : {_exc}")


from prometheus_client import start_http_server, Gauge, Counter, Histogram

class PrometheusExporter:
    """
    Phase 3.3 : Exportateur de métriques Prometheus.
    Expose le endpoint /metrics pour le scraping par un serveur Prometheus.
    """
    _instance = None
    
    def __new__(cls, port=8000):
        if cls._instance is None:
            cls._instance = super(PrometheusExporter, cls).__new__(cls)
            cls._instance.port = port
            cls._instance.is_running = False
            cls._instance._init_metrics()
        return cls._instance
        
    def _init_metrics(self):
        # Gauges (Valeurs qui montent et descendent)
        self.bot_balance = Gauge('bot_balance', 'Solde actuel du compte de trading')
        self.bot_pnl_session = Gauge('bot_pnl_session', 'PnL de la session en cours')
        self.bot_drawdown_pct = Gauge('bot_drawdown_pct', 'Drawdown maximum actuel en pourcentage')
        self.bot_open_positions = Gauge('bot_open_positions', 'Nombre de positions actuellement ouvertes')
        
        # Counters (Valeurs qui ne font qu'augmenter)
        self.bot_api_errors_total = Counter('bot_api_errors_total', 'Nombre total derreurs API', ['broker', 'error_code'])
        self.bot_trades_executed_total = Counter('bot_trades_executed_total', 'Nombre total de trades executes', ['symbol', 'side'])
        
        # Histograms
        self.bot_cycle_duration_seconds = Histogram('bot_cycle_duration_seconds', 'Duree dun cycle dexecution complet en secondes')
        
    def start(self):
        if not self.is_running:
            try:
                start_http_server(self.port)
                self.is_running = True
                log.info(f"🚀 Prometheus Exporter demarre sur le port {self.port} (endpoint /metrics)")
            except Exception as e:
                log.error(f"Erreur au demarrage de Prometheus Exporter: {e}")


# Export des classes publiques
__all__ = ['TelemetryClient', 'TelemetryLoggingHandler', 'PrometheusExporter']
