"""
NexQuant V3 — Knowledge Feeder Autonome
=========================================
Phase 3 : Ingestion quotidienne de ressources gratuites.

Sources intégrées :
  1. RSS Feeds        : ForexFactory blog, BabyPips, Investopedia, Reuters Finance
  2. Reddit           : r/Forex, r/algotrading, r/CryptoCurrency (via RSS)
  3. ForexFactory     : Calendrier économique (impact HIGH)
  4. FRED             : Données macro US (Fed Funds Rate, CPI, NFP)
  5. Fear & Greed     : Crypto sentiment (alternative.me)
  6. CoinGecko        : Données crypto (sans clé API)
  7. Actualités forex : Contenu structuré pour l'analyse du marché

Planification :
  - Ingestion complète : 00:30 UTC quotidien
  - Mise à jour news économiques : toutes les 2h
  - Mise à jour sentiment crypto : toutes les 4h

Tout est gratuit, sans clé API requise sauf NewsAPI (optionnel).
"""

import logging
import threading
import time
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexquant.knowledge_feeder")

# ─── Imports HTTP conditionnels ───────────────────────────────────────────────
try:
    import urllib.request
    import urllib.error
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCES RSS GRATUITES
# ═══════════════════════════════════════════════════════════════════════════════

RSS_SOURCES = [
    # Forex & Trading
    {"url": "https://www.babypips.com/feed", "type": "rss", "label": "BabyPips", "assets": ["EUR", "GBP", "USD", "JPY"], "relevance": 0.9},
    {"url": "https://www.forexfactory.com/ff_calendar_thisweek.json", "type": "calendar", "label": "ForexFactory Calendar", "assets": ["USD", "EUR", "GBP", "JPY"], "relevance": 1.0},
    {"url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "type": "rss", "label": "WSJ Markets", "assets": ["USD", "EUR", "SPX"], "relevance": 0.85},
    # Crypto
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "type": "rss", "label": "CoinDesk", "assets": ["BTC", "ETH", "BNB"], "relevance": 0.9},
    {"url": "https://cointelegraph.com/rss", "type": "rss", "label": "CoinTelegraph", "assets": ["BTC", "ETH"], "relevance": 0.85},
    # Reddit via RSS (pas d'auth requise)
    {"url": "https://www.reddit.com/r/Forex.rss", "type": "rss", "label": "Reddit/Forex", "assets": ["EUR", "GBP", "USD", "JPY"], "relevance": 0.75},
    {"url": "https://www.reddit.com/r/algotrading.rss", "type": "rss", "label": "Reddit/AlgoTrading", "assets": ["ALL"], "relevance": 0.80},
    {"url": "https://www.reddit.com/r/CryptoCurrency/.rss", "type": "rss", "label": "Reddit/Crypto", "assets": ["BTC", "ETH", "BNB"], "relevance": 0.70},
    # Macro économique
    {"url": "https://news.google.com/rss/search?q=Federal+Reserve+interest+rate&hl=en-US&gl=US&ceid=US:en", "type": "rss", "label": "Google News Fed", "assets": ["USD"], "relevance": 0.95},
]

# ─── APIs gratuites ───────────────────────────────────────────────────────────
FEAR_GREED_API = "https://api.alternative.me/fng/?limit=1&format=json"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
FRED_SERIES = {
    "DFF": "Fed Funds Rate",          # Taux Fed
    "CPIAUCSL": "CPI Inflation",       # Inflation
    "UNRATE": "Unemployment Rate",     # Chômage
    "DEXUSEU": "EUR/USD Exchange Rate", # Taux de change
}
FRED_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="


class KnowledgeFeeder:
    """
    Ingestion autonome de ressources financières gratuites.
    
    Stocke tout dans la DB SQLite via NexQuantDB.
    Peut être lancé en background thread ou appelé manuellement.
    
    Usage :
        feeder = KnowledgeFeeder(db_instance)
        feeder.start()  # Background thread quotidien
        # ou
        feeder.run_full_ingestion()  # Appel manuel
    """

    def __init__(self, db=None, config: Dict = None):
        self._db = db
        self._config = config or {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Intervalles de mise à jour
        self._full_ingestion_interval_h = 24   # Ingestion complète toutes les 24h
        self._news_update_interval_h = 2       # News économiques toutes les 2h
        self._sentiment_update_interval_h = 4  # Sentiment toutes les 4h

        self._last_full_ingestion: Optional[datetime] = None
        self._last_news_update: Optional[datetime] = None
        self._last_sentiment_update: Optional[datetime] = None

        # Résultats de la dernière ingestion
        self._last_ingestion_stats: Dict = {}

        # Cache de sentiment
        self._fear_greed_index: Optional[int] = None
        self._fear_greed_label: str = "Unknown"
        self._btc_market_cap_dominance: float = 0.0

        log.info("KnowledgeFeeder V3 initialisé")

    def start(self):
        """Lance le feeder en background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._background_loop,
            name="knowledge_feeder",
            daemon=True
        )
        self._thread.start()
        log.info("KnowledgeFeeder démarré en background")

    def stop(self):
        """Arrête le feeder."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        log.info("KnowledgeFeeder arrêté")

    def _background_loop(self):
        """Boucle principale du feeder (background thread)."""
        # Première ingestion au démarrage
        self.run_full_ingestion()

        while self._running:
            now = datetime.now(timezone.utc)

            # Ingestion complète toutes les 24h
            if (self._last_full_ingestion is None or
                    (now - self._last_full_ingestion).total_seconds() >= self._full_ingestion_interval_h * 3600):
                self.run_full_ingestion()

            # Mise à jour news économiques toutes les 2h
            elif (self._last_news_update is None or
                  (now - self._last_news_update).total_seconds() >= self._news_update_interval_h * 3600):
                self._fetch_economic_calendar()
                self._last_news_update = now

            # Mise à jour sentiment toutes les 4h
            elif (self._last_sentiment_update is None or
                  (now - self._last_sentiment_update).total_seconds() >= self._sentiment_update_interval_h * 3600):
                self._fetch_fear_greed()
                self._fetch_crypto_market_data()
                self._last_sentiment_update = now

            time.sleep(300)  # Vérifier toutes les 5 minutes

    def run_full_ingestion(self) -> Dict[str, Any]:
        """
        Lance une ingestion complète de toutes les sources.
        Retourne les statistiques de l'ingestion.
        """
        log.info("🌐 KnowledgeFeeder : Ingestion complète démarrée...")
        stats = {'rss': 0, 'calendar': 0, 'fred': 0, 'sentiment': 0, 'errors': 0}

        # 1. RSS / Blogs
        stats['rss'] = self._fetch_rss_sources()

        # 2. Calendrier économique ForexFactory
        stats['calendar'] = self._fetch_economic_calendar()

        # 3. Données macro FRED
        stats['fred'] = self._fetch_fred_data()

        # 4. Fear & Greed + CoinGecko
        fear_greed_ok = self._fetch_fear_greed()
        crypto_ok = self._fetch_crypto_market_data()
        stats['sentiment'] = 1 if fear_greed_ok or crypto_ok else 0

        # 5. Purge des items expirés
        if self._db:
            try:
                self._db.purge_expired_knowledge()
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        self._last_full_ingestion = datetime.now(timezone.utc)
        self._last_news_update = self._last_full_ingestion
        self._last_sentiment_update = self._last_full_ingestion
        self._last_ingestion_stats = stats

        total = sum(v for v in stats.values() if isinstance(v, int))
        log.info(f"✅ KnowledgeFeeder : Ingestion terminée | {total} items | {stats}")
        return stats

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH RSS
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_rss_sources(self) -> int:
        """Récupère et parse tous les flux RSS."""
        total = 0
        for source in RSS_SOURCES:
            if source['type'] != 'rss':
                continue
            try:
                items = self._fetch_rss(source['url'], source['label'], source['assets'], source['relevance'])
                total += items
            except Exception as e:
                log.debug(f"RSS {source['label']} error: {e}")
        return total

    def _fetch_rss(self, url: str, label: str, assets: List[str], relevance: float) -> int:
        """Parse un flux RSS et insère les items dans la DB."""
        content = self._http_get(url, timeout=10)
        if not content:
            return 0

        # Parse XML basique (sans lxml/beautifulsoup4)
        items_parsed = self._parse_rss_xml(content)
        count = 0
        for item in items_parsed[:10]:  # Max 10 items par source
            if self._db:
                try:
                    inserted = self._db.insert_knowledge_item({
                        'source_type': 'rss',
                        'source_url': url,
                        'title': item.get('title', '')[:200],
                        'content': item.get('description', '')[:2000],
                        'summary': item.get('description', '')[:300],
                        'sentiment': self._compute_quick_sentiment(item.get('title', '') + ' ' + item.get('description', '')),
                        'relevance_score': relevance,
                        'assets_mentioned': assets,
                        'published_at': item.get('pubDate', ''),
                    })
                    if inserted:
                        count += 1
                except Exception as e:
                    log.debug(f"Insert RSS item error: {e}")
        log.debug(f"RSS {label} : {count} nouveaux items")
        return count

    def _parse_rss_xml(self, xml_content: str) -> List[Dict]:
        """Parse XML RSS basique sans dépendances externes."""
        items = []
        # Extraire les blocs <item>
        item_pattern = re.compile(r'<item>(.*?)</item>', re.DOTALL | re.IGNORECASE)
        for match in item_pattern.finditer(xml_content):
            item_text = match.group(1)
            item = {}
            for field in ['title', 'description', 'link', 'pubDate', 'guid']:
                pattern = re.compile(f'<{field}[^>]*><!\\[CDATA\\[(.*?)\\]\\]></{field}>|<{field}[^>]*>(.*?)</{field}>', re.DOTALL | re.IGNORECASE)
                m = pattern.search(item_text)
                if m:
                    item[field] = (m.group(1) or m.group(2) or '').strip()
            if item.get('title'):
                items.append(item)
        return items

    # ─────────────────────────────────────────────────────────────────────────
    # CALENDRIER ÉCONOMIQUE
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_economic_calendar(self) -> int:
        """Récupère le calendrier ForexFactory et stocke les events HIGH impact."""
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        content = self._http_get(url, timeout=15)
        if not content:
            return 0

        try:
            events = json.loads(content)
        except json.JSONDecodeError:
            return 0

        count = 0
        # Ne garder que les events HIGH impact des 3 prochains jours
        for event in events:
            try:
                impact = event.get('impact', '').lower()
                if impact not in ('high', 'medium'):
                    continue

                event_time_str = event.get('date', '')
                currency = event.get('currency') or event.get('country', '')  # flux faireconomy : 'country'
                title = event.get('title', '')
                forecast = event.get('forecast', '')
                previous = event.get('previous', '')

                content_text = (
                    f"Economic Event: {title} | Currency: {currency} | Impact: {impact} | "
                    f"Forecast: {forecast} | Previous: {previous}"
                )

                if self._db:
                    inserted = self._db.insert_knowledge_item({
                        'source_type': 'economic_calendar',
                        'source_url': url,
                        'title': f"[{impact.upper()}] {currency}: {title}",
                        'content': content_text,
                        'summary': content_text[:200],
                        'sentiment': 0.0,
                        'relevance_score': 1.0 if impact == 'high' else 0.7,
                        'assets_mentioned': [currency],
                        'published_at': event_time_str,
                    })
                    if inserted:
                        count += 1
            except Exception as e:
                log.debug(f"Calendar event parse error: {e}")

        log.info(f"📅 ForexFactory Calendar : {count} events HIGH/MEDIUM ingérés")
        return count

    # ─────────────────────────────────────────────────────────────────────────
    # DONNÉES MACRO FRED
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_fred_data(self) -> int:
        """Récupère les données macro depuis FRED (gratuit, sans clé)."""
        count = 0
        for series_id, description in FRED_SERIES.items():
            try:
                url = f"{FRED_BASE_URL}{series_id}&vintage_dates={datetime.now().strftime('%Y-%m-%d')}"
                content = self._http_get(url, timeout=10)
                if not content:
                    continue

                # CSV : DATE,VALUE
                lines = [line for line in content.strip().split('\n') if line and not line.startswith('DATE')]
                if not lines:
                    continue

                # Dernière valeur
                last_line = lines[-1].strip()
                parts = last_line.split(',')
                if len(parts) >= 2:
                    date_str, value_str = parts[0], parts[1]
                    value = float(value_str) if value_str not in ('.', '') else None
                    if value is not None:
                        asset = 'USD' if 'USD' in series_id or series_id in ('DFF', 'CPIAUCSL', 'UNRATE') else 'EUR'
                        content_text = f"FRED {series_id} ({description}) : {value} (date: {date_str})"
                        if self._db:
                            inserted = self._db.insert_knowledge_item({
                                'source_type': 'fred',
                                'source_url': url,
                                'title': f"FRED: {description} = {value}",
                                'content': content_text,
                                'summary': content_text,
                                'sentiment': 0.0,
                                'relevance_score': 0.9,
                                'assets_mentioned': [asset],
                                'published_at': date_str,
                            })
                            if inserted:
                                count += 1
            except Exception as e:
                log.debug(f"FRED {series_id} error: {e}")

        log.debug(f"FRED macro data : {count} séries ingérées")
        return count

    # ─────────────────────────────────────────────────────────────────────────
    # FEAR & GREED + CRYPTO MARKET
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_fear_greed(self) -> bool:
        """Récupère l'indice Fear & Greed de alternative.me."""
        content = self._http_get(FEAR_GREED_API, timeout=10)
        if not content:
            return False
        try:
            data = json.loads(content)
            fg_data = data.get('data', [{}])[0]
            self._fear_greed_index = int(fg_data.get('value', 50))
            self._fear_greed_label = fg_data.get('value_classification', 'Neutral')

            if self._db:
                self._db.insert_knowledge_item({
                    'source_type': 'fear_greed',
                    'source_url': FEAR_GREED_API,
                    'title': f"Crypto Fear & Greed Index: {self._fear_greed_index} ({self._fear_greed_label})",
                    'content': f"F&G={self._fear_greed_index} | Classification={self._fear_greed_label}",
                    'summary': f"F&G={self._fear_greed_index} {self._fear_greed_label}",
                    'sentiment': (self._fear_greed_index - 50) / 50.0,  # Normaliser -1 à +1
                    'relevance_score': 0.85,
                    'assets_mentioned': ['BTC', 'ETH'],
                })
            log.info(f"😱 Fear & Greed : {self._fear_greed_index} ({self._fear_greed_label})")
            return True
        except Exception as e:
            log.debug(f"Fear & Greed parse error: {e}")
            return False

    def _fetch_crypto_market_data(self) -> bool:
        """Récupère les données globales du marché crypto via CoinGecko."""
        content = self._http_get(COINGECKO_GLOBAL, timeout=10)
        if not content:
            return False
        try:
            data = json.loads(content)
            market = data.get('data', {})
            btc_dom = market.get('market_cap_percentage', {}).get('btc', 0)
            total_cap = market.get('total_market_cap', {}).get('usd', 0)
            volume_24h = market.get('total_volume', {}).get('usd', 0)
            self._btc_market_cap_dominance = btc_dom

            content_text = (
                f"Crypto Global Market | BTC dominance: {btc_dom:.1f}% | "
                f"Total cap: ${total_cap/1e12:.2f}T | 24h volume: ${volume_24h/1e9:.1f}B"
            )
            if self._db:
                self._db.insert_knowledge_item({
                    'source_type': 'coingecko',
                    'source_url': COINGECKO_GLOBAL,
                    'title': f"Crypto Market: BTC dom={btc_dom:.1f}%, Cap=${total_cap/1e12:.2f}T",
                    'content': content_text,
                    'summary': content_text,
                    'sentiment': 0.3 if btc_dom > 50 else -0.1,  # Dominance BTC = bullish signal
                    'relevance_score': 0.80,
                    'assets_mentioned': ['BTC', 'ETH', 'BNB'],
                })
            log.debug(f"CoinGecko global : BTC dom={btc_dom:.1f}%")
            return True
        except Exception as e:
            log.debug(f"CoinGecko parse error: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────────────────────────────────────

    def _http_get(self, url: str, timeout: int = 10) -> Optional[str]:
        """Effectue une requête HTTP GET simple (sans dépendances externes)."""
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'NexQuantBot/3.0 (AlgoTrading Research; +https://github.com/nexquant)',
                    'Accept': 'application/json, text/xml, text/html, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read()
                # Décoder en UTF-8 avec fallback
                try:
                    return content.decode('utf-8')
                except UnicodeDecodeError:
                    return content.decode('latin-1', errors='ignore')
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log.debug(f"Rate limit: {url}")
            elif e.code != 404:
                log.debug(f"HTTP {e.code}: {url}")
            return None
        except Exception as e:
            log.debug(f"HTTP error {url}: {e}")
            return None

    def _compute_quick_sentiment(self, text: str) -> float:
        """
        Analyse de sentiment basique (lexicon-based, sans ML).
        Retourne une valeur entre -1.0 (très négatif) et +1.0 (très positif).
        """
        text_lower = text.lower()

        bullish_words = [
            'bull', 'bullish', 'rally', 'surge', 'gain', 'rise', 'high', 'growth',
            'strong', 'positive', 'up', 'pump', 'breakout', 'record', 'peak',
            'profit', 'win', 'buy', 'long', 'momentum', 'support'
        ]
        bearish_words = [
            'bear', 'bearish', 'crash', 'drop', 'fall', 'loss', 'low', 'decline',
            'weak', 'negative', 'down', 'dump', 'breakdown', 'sell', 'short',
            'fear', 'risk', 'warning', 'concern', 'uncertainty', 'volatility'
        ]

        bull_count = sum(1 for w in bullish_words if w in text_lower)
        bear_count = sum(1 for w in bearish_words if w in text_lower)

        total = bull_count + bear_count
        if total == 0:
            return 0.0

        sentiment = (bull_count - bear_count) / total
        return round(max(-1.0, min(1.0, sentiment)), 3)

    # ─────────────────────────────────────────────────────────────────────────
    # API PUBLIQUE
    # ─────────────────────────────────────────────────────────────────────────

    def get_current_sentiment(self) -> Dict[str, Any]:
        """Retourne le sentiment de marché courant (mis à jour en background)."""
        return {
            'fear_greed_index': self._fear_greed_index,
            'fear_greed_label': self._fear_greed_label,
            'btc_dominance': self._btc_market_cap_dominance,
            'overall_sentiment': 'bullish' if (self._fear_greed_index or 50) > 60
                                 else ('bearish' if (self._fear_greed_index or 50) < 40 else 'neutral'),
            'last_update': self._last_sentiment_update.isoformat() if self._last_sentiment_update else None,
        }

    def get_ingestion_stats(self) -> Dict[str, Any]:
        """Retourne les stats de la dernière ingestion."""
        return {
            **self._last_ingestion_stats,
            'last_full_ingestion': self._last_full_ingestion.isoformat() if self._last_full_ingestion else None,
        }

    def get_relevant_items(self, symbols: List[str] = None, limit: int = 20) -> List[Dict]:
        """Retourne les items de connaissance pertinents pour les symboles donnés."""
        if not self._db:
            return []
        try:
            return self._db.get_knowledge_items(limit=limit)
        except Exception:
            return []
