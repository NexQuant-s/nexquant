"""
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╩
"""
import requests
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional
import logging
from dataclasses import dataclass, asdict

# Importer la configuration
from superbot.config import (
    FEAR_GREED_API, FOREXFACTORY_API
)

log = logging.getLogger("news_manager")

# Base de l'API publique CryptoCompare (nouvelles : /v2/news/)
CRYPTOCOMPARE_API = "https://min-api.cryptocompare.com/data"


@dataclass
class NewsEvent:
    """Représente un événement de nouvelle."""
    title: str
    source: str
    timestamp: datetime
    impact: str  # HIGH, MEDIUM, LOW
    currency: str  # USD, EUR, BTC, etc.
    description: str = ""
    url: str = ""

    def is_recent(self, minutes: int = 60) -> bool:
        """Vérifie si l'événement est récent."""
        return (datetime.now() - self.timestamp).total_seconds() < (minutes * 60)

    def is_high_impact(self) -> bool:
        """Vérifie si l'événement est à haut impact."""
        return self.impact.upper() == "HIGH"


@dataclass
class SentimentScore:
    """Représente un score de sentiment agrégé."""
    overall: float  # -1 à 1 (négatif à positif)
    confidence: float  # 0 à 1
    fear_greed: float  # 0 à 100
    news_impact: float  # -1 à 1
    social_media: float  # -1 à 1
    on_chain: float  # -1 à 1
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NewsManager:
    """
    Gestionnaire de nouvelles et de sentiment unifié qui agrège des données
    de multiples sources pour fournir un facteur de risque et de sentiment.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise le gestionnaire de nouvelles.

        Args:
            config: Dictionnaire contenant la configuration
        """
        self.config = config
        self.assets = [asset.upper() for asset in config.get('NEWS_ASSETS', ['BTC', 'ETH', 'EUR', 'USD', 'SPY'])]
        self.update_interval = config.get('NEWS_UPDATE_INTERVAL', 300)  # 5 minutes par défaut
        self.avoidance_before = config.get('NEWS_AVOIDANCE_BEFORE', 30)  # minutes avant
        self.avoidance_after = config.get('NEWS_AVOIDANCE_AFTER', 15)   # minutes après
        self.risk_reduction_factor = config.get('NEWS_RISK_REDUCTION_FACTOR', 0.5)
        self.high_impact_only = config.get('NEWS_HIGH_IMPACT_ONLY', True)
        self.fear_greed_extreme_fear = config.get('FEAR_GREED_EXTREME_FEAR', 20)
        self.fear_greed_extreme_greed = config.get('FEAR_GREED_EXTREME_GREED', 80)

        # État interne
        self.latest_sentiment: Optional[SentimentScore] = None
        self.latest_news: List[NewsEvent] = []
        self.fear_greed_history: List[Tuple[datetime, float]] = []
        self.news_lock = threading.RLock()
        self.update_thread: Optional[threading.Thread] = None
        self.running = False

        # Cache pour éviter les requêtes répétées
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, datetime] = {}

        log.info("NewsManager initialisé")

    def start(self):
        """Démarre le thread de mise à jour en arrière-plan."""
        if self.running:
            return

        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()
        log.info("NewsManager démarré")

    def stop(self):
        """Arrête le thread de mise à jour."""
        self.running = False
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=5.0)
        log.info("NewsManager arrêté")

    def _update_loop(self):
        """Boucle principale de mise à jour des nouvelles.

        ⚠️ ROBUSTESSE (fix freeze 6h26 du 24/07/2026) :
        Chaque source est lancée dans un thread isolé avec timeout.
        Si une source freeze (DNS, SSL), le cycle ne bloque pas.
        """
        while self.running:
            try:
                self._update_all_sources_non_blocking()
                time.sleep(self.update_interval)
            except Exception as e:
                log.error(f"Erreur dans la boucle de mise à jour des nouvelles: {e}")
                time.sleep(min(self.update_interval, 60))

    def _run_source_with_timeout(self, fn, name: str, timeout: float = 15.0):
        """
        Exécute une fonction de mise à jour dans un thread isolé avec timeout strict.
        Si le thread ne se termine pas dans le délai imparti, on l'abandonne et
        on continue — la source reste en cache jusqu'à la prochaine tentative.

        Args:
            fn: Callable à exécuter (ex: self._update_fear_greed)
            name: Nom lisible de la source (pour les logs)
            timeout: Délai max en secondes (défaut 15s)
        """
        t = threading.Thread(target=fn, name=f"news_{name}", daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            log.warning(
                f"⚠️ [NewsManager] Source '{name}' a dépassé le timeout de {timeout}s — "
                f"poursuite avec les données en cache. Le thread continuera en arrière-plan."
            )

    def _update_all_sources_non_blocking(self):
        """
        Met à jour toutes les sources de nouvelles de manière non-bloquante.

        Chaque source est isolée dans son propre thread avec un timeout de 15s.
        Même si une source est injoignable (DNS, SSL, timeout réseau), le cycle
        de trading ne sera jamais bloqué.
        """
        sources = [
            (self._update_fear_greed,       "fear_greed"),
            (self._update_forex_factory_news, "forex_factory"),
            (self._update_crypto_news,       "crypto"),
            (self._update_social_sentiment,  "social_sentiment"),
        ]

        for fn, name in sources:
            self._run_source_with_timeout(fn, name, timeout=15.0)

        # Calculer le sentiment global après les mises à jour
        try:
            self._calculate_global_sentiment()
        except Exception as e:
            log.warning(f"[NewsManager] Erreur calcul sentiment global (non-bloquant): {e}")

        log.debug("Mise à jour des nouvelles terminée (non-bloquant)")

    def _update_all_sources(self):
        """Alias de compatibilité → délègue au mode non-bloquant."""
        self._update_all_sources_non_blocking()

    def _update_fear_greed(self):
        """Met à jour l'indice Fear & Greed."""
        try:
            # Vérifier le cache
            cache_key = "fear_greed"
            if self._is_cached_valid(cache_key, minutes=30):  # Cache de 30 minutes
                return

            response = requests.get(FEAR_GREED_API, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    fg_data = data['data'][0]
                    value = int(fg_data['value'])
                    classification = fg_data['value_classification']

                    # Stocker dans l'historique
                    self.fear_greed_history.append((datetime.now(), value))
                    # Garder seulement les 30 derniers jours
                    if len(self.fear_greed_history) > 30 * 24 * 2:  # Toutes les 30 minutes pendant 30 jours
                        self.fear_greed_history = self.fear_greed_history[-30 * 24 * 2:]

                    self._cache[cache_key] = {
                        'value': value,
                        'classification': classification,
                        'timestamp': datetime.now()
                    }
                    self._cache_timestamps[cache_key] = datetime.now()

                    log.debug(f"Fear & Greed mis à jour: {value} ({classification})")
                else:
                    log.warning("Réponse Fear & Greed vide ou mal formée")
                    self._cache_timestamps[cache_key] = datetime.now()
            else:
                log.warning(f"API Fear & Greed retourné le code {response.status_code}")
                self._cache_timestamps[cache_key] = datetime.now()
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour du Fear & Greed: {e}")
            # Backoff fixe de 60 min en cas d'erreur réseau : l'ancienne formule
            # mélangeait secondes (update_interval) et minutes et produisait des
            # timestamps incohérents.
            self._cache_timestamps[cache_key] = datetime.now() + timedelta(minutes=60)

    def _update_forex_factory_news(self):
        """Met à jour les nouvelles de Forex Factory."""
        try:
            # Vérifier le cache
            cache_key = "forex_factory"
            if self._is_cached_valid(cache_key, minutes=15):  # Cache de 15 minutes
                return

            response = requests.get(FOREXFACTORY_API, timeout=10)
            if response.status_code == 200:
                data = response.json()

                news_events = []
                for item in data:
                    if isinstance(item, dict):
                        title = item.get('title', '')
                        date_str = item.get('date', '')
                        time_str = item.get('time', '')
                        impact = item.get('impact', 'LOW')
                        # Le flux faireconomy fournit la devise dans 'country' (ex: "USD")
                        currency = item.get('currency') or item.get('country', '')
                        forecast = item.get('forecast', '')
                        previous = item.get('previous', '')

                        # Filtrer selon les paramètres (les jours fériés ne sont pas des annonces)
                        if str(impact).lower() == 'holiday':
                            continue
                        if self.high_impact_only and impact.upper() != 'HIGH':
                            continue

                        # Vérifier si la monnaie est pertinente
                        if currency and currency.upper() not in self.assets:
                            continue

                        # Construire la timestamp
                        try:
                            if 'T' in date_str:
                                # Format actuel : ISO-8601 avec fuseau (ex: "2026-10-09T08:30:00-04:00").
                                # Converti en heure locale naïve, comme datetime.now() dans ce module.
                                news_time = datetime.fromisoformat(date_str).astimezone().replace(tzinfo=None)
                                news_event = NewsEvent(
                                    title=title,
                                    source="Forex Factory",
                                    timestamp=news_time,
                                    impact=impact,
                                    currency=currency,
                                    description=f"Forecast: {forecast}, Previous: {previous}",
                                    url=""
                                )
                                news_events.append(news_event)
                                continue

                            # Ancien format : date "MM/DD/YYYY" + time "HH:MM" ou "Tentative"
                            if time_str.lower() in ['tentative', 'all day', 'holiday']:
                                continue  # Ignorer les événements non horodatés précisément

                            dt_str = f"{date_str} {time_str}"
                            # Essayer de parser - les événements peuvent être dans le futur
                            news_time = datetime.strptime(dt_str, "%m/%d/%Y %H:%M")
                            # Ajuster l'année si nécessaire (Forex Factory ne fournit pas toujours l'année)
                            now = datetime.now()
                            if news_time.month < now.month - 2:  # Si la date semble être dans le passé lointain
                                news_time = news_time.replace(year=now.year + 1)
                            elif news_time.month > now.month + 2:  # Si la date semble être dans le futur lointain
                                news_time = news_time.replace(year=now.year - 1)
                        except ValueError:
                            # Si on ne peut pas parser la date, utiliser maintenant comme approximation
                            news_time = datetime.now()

                        # Créer l'événement de nouvelle
                        news_event = NewsEvent(
                            title=title,
                            source="Forex Factory",
                            timestamp=news_time,
                            impact=impact,
                            currency=currency,
                            description=f"Forecast: {forecast}, Previous: {previous}",
                            url=""  # Forex Factory ne fournit pas d'URL directe dans cet endpoint
                        )
                        news_events.append(news_event)

                # Mettre à jour le cache
                self._cache[cache_key] = {
                    'events': news_events,
                    'timestamp': datetime.now()
                }
                self._cache_timestamps[cache_key] = datetime.now()

                # Aussi mettre à jour les nouvelles générales
                with self.news_lock:
                    # Ne garder que les nouvelles récentes (24h) des AUTRES sources : le flux
                    # ForexFactory renvoie toute la semaine à chaque rafraîchissement ; sans ce
                    # filtre, ses événements (datés dans le futur) seraient dupliqués à chaque appel.
                    cutoff_time = datetime.now() - timedelta(hours=24)
                    recent_news = [event for event in self.latest_news
                                   if event.timestamp > cutoff_time and event.source != "Forex Factory"]
                    self.latest_news = recent_news + news_events
                    # Trier par timestamp décroissant
                    self.latest_news.sort(key=lambda x: x.timestamp, reverse=True)

                log.debug(f"Forex Factory news mis à jour: {len(news_events)} événements")
            else:
                log.warning(f"API Forex Factory retourné le code {response.status_code}")
                self._cache_timestamps[cache_key] = datetime.now()
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour des nouvelles Forex Factory: {e}")
            # Backoff fixe de 60 min en cas d'erreur réseau pour éviter les retry
            # frénétiques qui peuvent bloquer le cycle (fix freeze 24/07/2026).
            self._cache_timestamps[cache_key] = datetime.now() + timedelta(minutes=60)

    def _update_crypto_news(self):
        """Met à jour les nouvelles crypto depuis CoinGecko et CryptoCompare."""
        try:
            # Mettre à jour depuis CoinGecko (tendances, recherche)
            self._update_coingecko_trends()

            # Mettre à jour depuis CryptoCompare (news sentiment)
            self._update_cryptocompare_news()
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour des nouvelles crypto: {e}")

    def _update_coingecko_trends(self):
        """Met à jour les tendances depuis CoinGecko."""
        try:
            cache_key = "coingecko_trends"
            if self._is_cached_valid(cache_key, minutes=30):  # Cache de 30 minutes
                return

            # Obtenir les tendances de recherche
            url = "https://api.coingecko.com/api/v3/search/trending"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Les données de tendencia sont utiles mais pas directement des nouvelles
                # On pourrait les utiliser pour mesurer l'intérêt du marché
                self._cache[cache_key] = {
                    'data': data,
                    'timestamp': datetime.now()
                }
                self._cache_timestamps[cache_key] = datetime.now()
                log.debug("CoinGecko trends mis à jour")
            else:
                log.warning(f"API CoinGecko trends retourné le code {response.status_code}")
                self._cache_timestamps[cache_key] = datetime.now()
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour des tendances CoinGecko: {e}")
            self._cache_timestamps[cache_key] = datetime.now()

    def _update_cryptocompare_news(self):
        """Met à jour les nouvelles depuis CryptoCompare (nécessite une clé API)."""
        try:
            # Vérifier la présence de la clé API avant tout appel
            api_key = self.config.get('CRYPTOCOMPARE_API_KEY', '').strip()
            if not api_key:
                log.debug("CRYPTOCOMPARE_API_KEY non définie — nouvelles CryptoCompare ignorées")
                return

            cache_key = "cryptocompare_news"
            if self._is_cached_valid(cache_key, minutes=15):  # Cache de 15 minutes
                return

            # Obtenir les nouvelles générales
            url = f"{CRYPTOCOMPARE_API}/v2/news/"
            params = {'lang': 'EN', 'api_key': api_key}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 401:
                log.debug("CryptoCompare news : clé API invalide (401) — fonctionnalité désactivée")
                return
            if response.status_code == 200:
                data = response.json()
                if 'Data' in data and isinstance(data['Data'], list):
                    news_events = []
                    for item in data['Data'][:20]:  # Limiter aux 20 dernières
                        title = item.get('title', '')
                        body = item.get('body', '')
                        source = item.get('source', 'CryptoCompare')
                        published_on = item.get('published_on', 0)
                        categories = item.get('categories', '')
                        tags = item.get('tags', '')

                        # Convertir le timestamp
                        try:
                            news_time = datetime.fromtimestamp(published_on)
                        except (ValueError, TypeError):
                            news_time = datetime.now()

                        # Déterminer l'impact basé sur les catégories/tags (simplifié)
                        impact = "MEDIUM"  # Par défaut
                        if any(word in title.upper() for word in ['BREAKING', 'CRASH', 'SURGE', 'RALLY']):
                            impact = "HIGH"
                        elif any(word in title.upper() for word in ['UPDATE', 'MINOR', 'SLIGHT']):
                            impact = "LOW"

                        # Extraire les monnaies mentionnées (simplifié)
                        mentioned_currencies = []
                        text_to_search = f"{title} {body} {categories} {tags}".upper()
                        for asset in self.assets:
                            if asset in text_to_search:
                                mentioned_currencies.append(asset)

                        # Si aucune monnaie spécifique n'est mentionnée, considérer comme générale
                        if not mentioned_currencies:
                            mentioned_currencies = self.assets[:]  # Toutes les assets

                        # Créer un événement pour chaque monnaie mentionnée
                        for currency in mentioned_currencies:
                            news_event = NewsEvent(
                                title=title,
                                source=source,
                                                timestamp=news_time,
                                impact=impact,
                                    currency=currency,
                                description=body[:200] + "..." if len(body) > 200 else body,
                                url=item.get('url', '')
                            )
                            news_events.append(news_event)

                    # Mettre à jour le cache
                    self._cache[cache_key] = {
                        'events': news_events,
                        'timestamp': datetime.now()
                    }
                    self._cache_timestamps[cache_key] = datetime.now()

                    # Mettre à jour les nouvelles générales
                    with self.news_lock:
                        cutoff_time = datetime.now() - timedelta(hours=24)
                        recent_news = [event for event in self.latest_news if event.timestamp > cutoff_time]
                        self.latest_news = recent_news + news_events
                        self.latest_news.sort(key=lambda x: x.timestamp, reverse=True)

                    log.debug(f"CryptoCompare news mis à jour: {len(news_events)} événements")
                else:
                    log.warning("Réponse CryptoCompare news vide ou mal formée")
                    self._cache_timestamps[cache_key] = datetime.now()
            else:
                log.warning(f"API CryptoCompare news retourné le code {response.status_code}")
                self._cache_timestamps[cache_key] = datetime.now()
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour des nouvelles CryptoCompare: {e}")
            self._cache_timestamps[cache_key] = datetime.now()

    def _update_social_sentiment(self):
        """
        Met à jour le sentiment via RSS et NLP (VADER/FinBERT).
        """
        try:
            cache_key = "social_sentiment"
            if self._is_cached_valid(cache_key, minutes=10):  # Cache de 10 minutes
                return

            # Initialiser le scraper RSS et l'analyseur NLP si pas encore fait
            if not hasattr(self, '_rss_scraper'):
                from superbot.news.rss_scraper import RssScraper
                from superbot.news.sentiment_analyzer import SentimentAnalyzer
                self._rss_scraper = RssScraper()
                # On désactive FinBERT par défaut pour le scraping rapide (utiliser VADER)
                self._sentiment_analyzer = SentimentAnalyzer(use_finbert=False)

            # Récupérer les articles récents (toutes catégories confondues)
            articles = self._rss_scraper.fetch_all()
            
            if articles:
                # Calculer le score de sentiment via NLP sur les titres/résumés
                social_sentiment = self._sentiment_analyzer.analyze_rss_items(articles)
            else:
                social_sentiment = 0.0

            self._cache[cache_key] = {
                'sentiment': social_sentiment,
                'timestamp': datetime.now()
            }
            self._cache_timestamps[cache_key] = datetime.now()
            log.debug(f"Sentiment NLP mis à jour (sur {len(articles) if articles else 0} articles): {social_sentiment:.3f}")
        except Exception as e:
            log.error(f"Erreur lors de la mise à jour du sentiment NLP: {e}")

    def _calculate_global_sentiment(self):
        """
        Calcule le score de sentiment global basé sur toutes les sources.
        """
        with self.news_lock:
            try:
                # 1. Fear & Greed Index (0-100 -> -1 to 1)
                fg_score = 0.0
                fg_confidence = 0.0
                fg_data = self._cache.get('fear_greed')
                if fg_data and 'value' in fg_data:
                    fg_value = fg_data['value']
                    # Convertir 0-100 en -1 to 1: (value - 50) / 50
                    fg_score = (fg_value - 50.0) / 50.0
                    # La confiance est basée sur la fraîcheur des données
                    age_minutes = (datetime.now() - fg_data.get('timestamp', datetime.now())).total_seconds() / 60
                    fg_confidence = max(0.0, 1.0 - (age_minutes / 60.0))  # Décroît sur 1 heure
                    fg_confidence = max(0.0, min(fg_confidence, 1.0))

                # 2. Nouvelles impact (basé sur les événements récents et à haut impact)
                news_score = 0.0
                news_confidence = 0.0
                high_impact_recent = 0
                total_recent = 0
                cutoff_time = datetime.now() - timedelta(hours=6)  # Regarder les 6 dernières heures

                for event in self.latest_news:
                    if event.timestamp > cutoff_time:
                        total_recent += 1
                        if event.is_high_impact():
                            high_impact_recent += 1
                            # Contribuer négativement au score (les nouvelles à haut impact sont souvent négatives pour le trading à court terme)
                            news_score -= 0.5  # Impact modéré par événement

                if total_recent > 0:
                    news_score = max(-1.0, min(1.0, news_score))  # Limiter la plage
                    news_confidence = min(1.0, total_recent / 10.0)  # Plus de nouvelles = plus de confiance

                # 3. Sentiment des réseaux sociaux
                social_score = 0.0
                social_confidence = 0.0
                social_data = self._cache.get('social_sentiment')
                if social_data and 'sentiment' in social_data:
                    social_score = social_data['sentiment']
                    age_minutes = (datetime.now() - social_data.get('timestamp', datetime.now())).total_seconds() / 60
                    social_confidence = max(0.0, 1.0 - (age_minutes / 30.0))  # Décroît sur 30 minutes
                    social_confidence = max(0.0, min(social_confidence, 1.0))

                # 4. Sentiment on-chain (simplifié - à améliorer avec de vraies données on-chain)
                on_chain_score = 0.0
                on_chain_confidence = 0.1  # Faible confiance car simplifié

                # Calculer le score global pondéré
                weights = {
                    'fear_greed': 0.4,
                    'news': 0.3,
                    'social': 0.2,
                    'on_chain': 0.1
                }

                # Normaliser les poids basé sur la confiance
                total_weight = 0
                weighted_sum = 0.0

                if fg_confidence > 0:
                    total_weight += weights['fear_greed'] * fg_confidence
                    weighted_sum += weights['fear_greed'] * fg_confidence * fg_score

                if news_confidence > 0:
                    total_weight += weights['news'] * news_confidence
                    weighted_sum += weights['news'] * news_confidence * news_score

                if social_confidence > 0:
                    total_weight += weights['social'] * social_confidence
                    weighted_sum += weights['social'] * social_confidence * social_score

                if on_chain_confidence > 0:
                    total_weight += weights['on_chain'] * on_chain_confidence
                    weighted_sum += weights['on_chain'] * on_chain_confidence * on_chain_score

                overall_sentiment = 0.0
                overall_confidence = 0.0

                if total_weight > 0:
                    overall_sentiment = weighted_sum / total_weight
                    # La confiance globale est la moyenne pondérée des confiances
                    if fg_confidence > 0:
                        overall_confidence += weights['fear_greed'] * fg_confidence
                    if news_confidence > 0:
                        overall_confidence += weights['news'] * news_confidence
                    if social_confidence > 0:
                        overall_confidence += weights['social'] * social_confidence
                    if on_chain_confidence > 0:
                        overall_confidence += weights['on_chain'] * on_chain_confidence
                    overall_confidence = overall_confidence / sum(weights.values()) if sum(weights.values()) > 0 else 0
                    overall_confidence = max(0.0, min(1.0, overall_confidence))

                # Créer l'objet de sentiment
                sentiment = SentimentScore(
                    overall=overall_sentiment,
                    confidence=overall_confidence,
                    fear_greed=fg_value if fg_data and 'value' in fg_data else 50.0,
                    news_impact=news_score,
                    social_media=social_score,
                    on_chain=on_chain_score,
                    timestamp=datetime.now()
                )

                self.latest_sentiment = sentiment

                log.debug(f"Sentiment global calculé: {overall_sentiment:.3f} (conf: {overall_confidence:.3f})")

            except Exception as e:
                log.error(f"Erreur lors du calcul du sentiment global: {e}")

    def get_risk_factor(self) -> float:
        """
        Retourne un facteur de risque basé sur le sentiment actuel.
        Retourne une valeur entre 0 et 1 où:
        - 1.0 = risque normal (pas d'ajustement)
        - < 1.0 = risque réduit (nouveaux défavorables, sentiment extrême)
        - > 1.0 = risque augmenté (rare, seulement pour des opportunités claires)

        Returns:
            Facteur de risque à appliquer à la taille de position
        """
        if self.latest_sentiment is None:
            return 1.0  # Pas de données, risque normal

        sentiment = self.latest_sentiment.overall
        confidence = self.latest_sentiment.confidence
        fear_greed = self.latest_sentiment.fear_greed

        # Commencer avec un facteur neutre
        risk_factor = 1.0

        # 1. Ajuster basé sur le sentiment général
        # Sentiment très négatif -> réduire le risque
        # Sentiment très positif -> on pourrait augmenter légèrement, mais on reste conservateur
        if sentiment < -0.6:  # Sentiment négatif fort
            risk_factor *= 0.5  # Réduire de moitié
        elif sentiment < -0.3:  # Sentiment négatif modéré
            risk_factor *= (1.0 + sentiment)  # Entre 0.4 et 0.7 pour sentiment entre -0.6 et -0.3
        elif sentiment > 0.3:  # Sentiment positif modéré
            # On reste conservateur, on n'augmente pas beaucoup le risque
            risk_factor *= (1.0 + min(sentiment * 0.5, 0.2))  # Max +20%

        # 2. Ajuster basé sur l'indice Fear & Greed (approche contrarienne modérée)
        if fear_greed < self.fear_greed_extreme_fear:  # Peur extrême -> opportunité d'achat
            # Mais on ne augmente pas le risque trop beaucoup dans un environnement de peur
            fg_adjustment = 1.0 + ((self.fear_greed_extreme_fear - fear_greed) / self.fear_greed_extreme_fear) * 0.2
            risk_factor *= min(fg_adjustment, 1.2)  # Max +20%
        elif fear_greed > self.fear_greed_extreme_greed:  # Avidité extrême -> réduction du risque
            fg_adjustment = 1.0 - ((fear_greed - self.fear_greed_extreme_greed) / (100 - self.fear_greed_extreme_greed)) * 0.5
            risk_factor *= max(fg_adjustment, 0.5)  # Min 50%

        # 3. Ajuster basé sur les nouvelles à haut impact récentes
        recent_high_impact_news = self.get_recent_high_impact_news(hours=2)
        if len(recent_high_impact_news) > 0:
            # Chaque nouvelle à haut impact récente réduit le risque
            reduction_per_news = 0.2  # 20% de réduction par nouvelle
            total_reduction = min(len(recent_high_impact_news) * reduction_per_news, 0.8)  # Max 80% de réduction
            risk_factor *= (1.0 - total_reduction)

        # 4. Appliquer le facteur de réduction de risque basé sur les nouvelles (configuration)
        # Ceci est une couche supplémentaire de réduction basée sur la configuration
        risk_factor *= self.risk_reduction_factor if self.latest_sentiment.news_impact < -0.5 else 1.0

        # S'assurer que le facteur reste dans des limites raisonnables
        risk_factor = max(0.1, min(2.0, risk_factor))

        # Ajuster basé sur la confiance (moins de confiance = retour vers 1.0)
        if confidence < 1.0:
            risk_factor = 1.0 + (risk_factor - 1.0) * confidence

        return risk_factor

    @staticmethod
    def _symbol_currencies(symbol: str) -> List[str]:
        """
        Devises concernées par un symbole : 'EUR/USD' et 'EURUSD' -> ['EUR', 'USD'],
        'XAUUSD' -> ['XAU', 'USD']. (Avec les symboles MT5 sans '/', l'ancien code
        cherchait la devise 'EURUSD' et le filtre ne se déclenchait jamais.)
        """
        parts = [p for p in symbol.upper().replace('-', '/').split('/') if p]
        if len(parts) >= 2:
            return parts[:2]
        clean = parts[0] if parts else ''
        if len(clean) >= 6:
            return [clean[:3], clean[3:6]]
        return [clean]

    def should_avoid_trading_due_to_news(self, symbol: str = None,
                                        minutes_before: Optional[int] = None,
                                        minutes_after: Optional[int] = None) -> Tuple[bool, Optional[NewsEvent]]:
        """
        Détermine si on devrait éviter de trader à cause d'une nouvelle imminente ou récente.

        Args:
            symbol: Symbole à vérifier (si None, vérifie pour tous les actifs)
            minutes_before: Minutes avant l'événement à considérer (si None, utilise la config)
            minutes_after: Minutes après l'événement à considérer (si None, utilise la config)

        Returns:
            Tuple de (should_avoid, causative_event)
        """
        if minutes_before is None:
            minutes_before = self.avoidance_before
        if minutes_after is None:
            minutes_after = self.avoidance_after

        # Déterminer quelles monnaies vérifier
        if symbol:
            currencies_to_check = self._symbol_currencies(symbol)
        else:
            currencies_to_check = self.assets[:]

        cutoff_before = datetime.now() + timedelta(minutes=minutes_before)
        cutoff_after = datetime.now() - timedelta(minutes=minutes_after)

        with self.news_lock:
            for event in self.latest_news:
                # Vérifier si l'événement concerne une monnaie d'intérêt
                if event.currency.upper() in currencies_to_check:
                    # Vérifier si c'est un événement à haut impact (si configuré)
                    if self.high_impact_only and not event.is_high_impact():
                        continue

                    # Vérifier si l'événement est dans la fenêtre d'évitement
                    if event.timestamp >= cutoff_after and event.timestamp <= cutoff_before:
                        # Événement récent ou imminent détecté
                        log.info(
                            f"News avoidance triggered for {symbol if symbol else 'any symbol'}: "
                            f"{event.currency} {event.title} at {event.timestamp} "
                            f"(avoidance window: {minutes_before}min before, {minutes_after}min after)"
                        )
                        return True, event

        return False, None

    def get_recent_news(self, hours: int = 24) -> List[NewsEvent]:
        """Nouvelles déjà publiées dans les `hours` dernières heures (tous impacts)."""
        now = datetime.now()
        cutoff_time = now - timedelta(hours=hours)
        with self.news_lock:
            return [event for event in self.latest_news if cutoff_time < event.timestamp <= now]

    def get_recent_high_impact_news(self, hours: int = 24) -> List[NewsEvent]:
        """
        Nouvelles à HAUT impact déjà publiées dans les `hours` dernières heures.

        L'ancienne version renvoyait aussi les événements FUTURS de la semaine (calendrier
        ForexFactory) et tous les impacts : get_risk_factor() réduisait alors le risque
        d'environ 65 % en permanence (facteur ≈ 0,35 mesuré dans les logs).
        """
        return [event for event in self.get_recent_news(hours) if event.is_high_impact()]

    def get_fear_greed_level(self) -> Tuple[Optional[int], Optional[str]]:
        """
        Retourne le niveau actuel du Fear & Greed Index.

        Returns:
            Tuple de (value, classification) ou (None, None) si pas de données
        """
        fg_data = self._cache.get('fear_greed')
        if fg_data and 'value' in fg_data:
            return fg_data['value'], fg_data.get('classification', 'Unknown')
        return None, None

    def get_sentiment_summary(self) -> Dict[str, Any]:
        """
        Retourne un résumé complet du sentiment actuel.

        Returns:
            Dictionnaire avec le résumé du sentiment
        """
        if self.latest_sentiment is None:
            return {'error': 'No sentiment data available'}

        return {
            'overall': {
                'score': self.latest_sentiment.overall,
                'confidence': self.latest_sentiment.confidence,
                'label': self._sentiment_to_label(self.latest_sentiment.overall)
            },
            'fear_greed': {
                'value': self.latest_sentiment.fear_greed,
                'label': self._fear_greed_to_label(self.latest_sentiment.fear_greed)
            },
            'news_impact': self.latest_sentiment.news_impact,
            'social_media': self.latest_sentiment.social_media,
            'on_chain': self.latest_sentiment.on_chain,
            'timestamp': self.latest_sentiment.timestamp.isoformat(),
            'recent_high_impact_count': len(self.get_recent_high_impact_news(hours=6)),
            'avoidance_active': self.should_avoid_trading_due_to_news()[0],
            'recent_events': [
                {
                    'title': event.title,
                    'source': event.source,
                    'timestamp': event.timestamp.isoformat(),
                    'impact': event.impact,
                    'currency': event.currency,
                    'description': event.description,
                    'url': event.url
                }
                for event in self.get_recent_news(hours=24)
            ]
        }

    def _is_cached_valid(self, key: str, minutes: int = 10) -> bool:
        """
        Vérifie si une entrée de cache est encore valide.

        Args:
            key: Clé du cache
            minutes: Durée de validité en minutes

        Returns:
            True si le cache est valide, False sinon
        """
        if key not in self._cache_timestamps:
            return False
        age = (datetime.now() - self._cache_timestamps[key]).total_seconds() / 60
        return age < minutes

    def _sentiment_to_label(self, score: float) -> str:
        """Convertit un score de sentiment (-1 à 1) en label lisible."""
        if score <= -0.6:
            return "Très Négatif"
        elif score <= -0.2:
            return "Négatif"
        elif score < 0.2:
            return "Neutre"
        elif score < 0.6:
            return "Positif"
        else:
            return "Très Positif"

    def _fear_greed_to_label(self, value: int) -> str:
        """Convertit une valeur Fear & Greed (0-100) en label lisible."""
        if value <= 20:
            return "Peur Extrême"
        elif value <= 40:
            return "Peur"
        elif value <= 60:
            return "Neutre"
        elif value <= 80:
            return "Avidité"
        else:
            return "Avidité Extrême"

    def cleanup_old_data(self):
        """Nettoie les anciennes données pour éviter l'accumulation inutile."""
        cutoff_time = datetime.now() - timedelta(days=7)  # Garder une semaine de données

        with self.news_lock:
            # Nettoyer les nouvelles anciennes
            self.latest_news = [
                event for event in self.latest_news
                if event.timestamp > cutoff_time
            ]

            # Nettoyer le cache ancien
            keys_to_delete = []
            for key, timestamp in self._cache_timestamps.items():
                if timestamp < cutoff_time:
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                self._cache.pop(key, None)
                self._cache_timestamps.pop(key, None)

            # Nettoyer l'historique Fear & Greed (garder 30 jours)
            fg_cutoff = datetime.now() - timedelta(days=30)
            self.fear_greed_history = [
                (ts, val) for ts, val in self.fear_greed_history
                if ts > fg_cutoff
            ]

        log.debug("Nettoyage des anciennes données effectué")


# Export des classes publiques
__all__ = ['NewsManager', 'NewsEvent', 'SentimentScore']