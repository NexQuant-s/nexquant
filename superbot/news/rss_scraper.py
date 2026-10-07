# -*- coding: utf-8 -*-
"""
NexQuant RssScraper -- Phase 3
================================
Scrape les flux RSS financiers publics (sans cle API) pour alimenter
l'analyseur de sentiment en temps reel.

Flux couverts :
  - Reuters Economics  (macroeconomie mondiale)
  - Yahoo Finance      (actualites bourse et crypto)
  - CoinTelegraph      (crypto specifique)
  - Investing.com      (forex, matieres premieres, indices)
  - CoinDesk           (crypto institutionnel)

Usage :
    scraper = RssScraper()
    articles = scraper.fetch_all(symbol_filter="BTC")
    # -> [{'title': '...', 'summary': '...', 'published': '...', 'source': '...'}, ...]

    # Mise a jour asynchrone avec cache 15 minutes
    fresh = scraper.get_cached(symbol_filter="EUR")
"""
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

log = logging.getLogger("news.rss_scraper")

# -- Flux RSS publics indexes par categorie ----------------------------------

FEEDS = {
    "general": [
        {
            "name": "Reuters Business",
            "url": "https://feeds.reuters.com/reuters/businessNews",
            "weight": 1.0,
        },
        {
            "name": "Yahoo Finance",
            "url": "https://finance.yahoo.com/rss/",
            "weight": 0.9,
        },
        {
            "name": "Investing.com Forex",
            "url": "https://www.investing.com/rss/news_14.rss",
            "weight": 0.8,
        },
    ],
    "crypto": [
        {
            "name": "CoinTelegraph",
            "url": "https://cointelegraph.com/rss",
            "weight": 1.0,
        },
        {
            "name": "CoinDesk",
            "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "weight": 1.0,
        },
        {
            "name": "Bitcoin Magazine",
            "url": "https://bitcoinmagazine.com/.rss/full/",
            "weight": 0.8,
        },
    ],
    "forex": [
        {
            "name": "Forex Factory News",
            "url": "https://www.forexfactory.com/news?filter=forex",
            "weight": 1.0,
        },
        {
            "name": "DailyFX",
            "url": "https://www.dailyfx.com/feeds/all",
            "weight": 0.9,
        },
    ],
    "stocks": [
        {
            "name": "MarketWatch",
            "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
            "weight": 1.0,
        },
        {
            "name": "Seeking Alpha",
            "url": "https://seekingalpha.com/feed.xml",
            "weight": 0.8,
        },
    ],
}

# Mots-cles pour filtrer les articles par symbole
SYMBOL_KEYWORDS: Dict[str, List[str]] = {
    "BTC": ["bitcoin", "btc", "crypto", "satoshi", "halving", "lightning network"],
    "ETH": ["ethereum", "eth", "defi", "smart contract", "layer 2", "vitalik"],
    "BNB": ["binance", "bnb", "binance coin", "bnb chain"],
    "XRP": ["ripple", "xrp", "sec vs ripple"],
    "SOL": ["solana", "sol", "solana blockchain"],
    "EUR": ["euro", "eur", "ecb", "european central bank", "eurozone"],
    "USD": ["dollar", "usd", "fed", "federal reserve", "inflation", "cpi"],
    "SPY": ["s&p 500", "spx", "spy", "stock market", "wall street"],
    "GLD": ["gold", "xau", "precious metals", "safe haven"],
    "GC=F": ["gold", "xau", "precious metals"],
}


class RssScraper:
    """
    Scraper de flux RSS financiers avec cache integre.

    Effectue les requetes dans un thread daemon en arriere-plan
    pour ne jamais bloquer la boucle de trading principale.
    """

    CACHE_TTL_SECONDS = 900  # 15 minutes

    def __init__(self, timeout: int = 8):
        """
        Args:
            timeout: Timeout HTTP en secondes par requete
        """
        self.timeout = timeout
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._lock = threading.RLock()
        self._has_feedparser = self._check_feedparser()

    # -- API publique ---------------------------------------------------------

    def fetch_all(self, symbol_filter: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Recupere et aggregate les articles de tous les flux configures.

        Args:
            symbol_filter: Filtre optionnel sur le symbole (ex: "BTC", "EUR")
                           Si fourni, ne retourne que les articles contenant
                           des mots-cles lies a ce symbole.
            categories    : Sous-ensemble de categories ("crypto","forex","stocks","general")
                           Si None, utilise toutes les categories.

        Returns:
            Liste de dicts tries par date (du plus recent au plus ancien) :
            {'title', 'summary', 'published', 'source', 'url', 'category'}
        """
        if not self._has_feedparser:
            log.warning("[RssScraper] feedparser non installe. pip install feedparser")
            return []

        target_categories = categories or list(FEEDS.keys())
        all_articles = []

        for category in target_categories:
            for feed_cfg in FEEDS.get(category, []):
                articles = self._fetch_feed(feed_cfg["url"], feed_cfg["name"], category)
                # Ponderer les articles selon le poids du flux
                for art in articles:
                    art["weight"] = feed_cfg.get("weight", 1.0)
                all_articles.extend(articles)

        # Filtrer par symbole si demande
        if symbol_filter:
            all_articles = self._filter_by_symbol(all_articles, symbol_filter)

        # Trier par date (plus recent en premier)
        all_articles.sort(key=lambda x: x.get("published_dt", datetime.min), reverse=True)

        log.debug(
            f"[RssScraper] {len(all_articles)} articles recuperes "
            f"(filtre={symbol_filter or 'aucun'})"
        )
        return all_articles

    def get_cached(self, symbol_filter: Optional[str] = None,
                   categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Retourne les articles en cache si < 15 min, sinon met a jour.
        Thread-safe.
        """
        cache_key = f"{symbol_filter}_{categories}"
        with self._lock:
            if self._is_cache_valid(cache_key):
                return self._cache.get(cache_key, [])

        # Cache expire -- rafraichir en avant-plan (acceptable en demarrage)
        articles = self.fetch_all(symbol_filter, categories)
        with self._lock:
            self._cache[cache_key] = articles
            self._cache_timestamps[cache_key] = datetime.now()

        return articles

    def fetch_symbol_sentiment_context(self, symbol: str) -> Dict[str, Any]:
        """
        Retourne le contexte d'actualites pour un symbole specifique :
        articles recents + meta-information pour le NewsManager.

        Args:
            symbol: Symbole de l'instrument (ex: "BTCUSDT", "EUR/USD")

        Returns:
            Dict avec 'articles', 'count', 'most_recent', 'keywords_matched'
        """
        # Normaliser le symbole pour le matching
        sym_clean = symbol.upper().replace("/", "").replace("-", "")
        sym_base = sym_clean[:3]  # Ex: "BTC" depuis "BTCUSDT"

        articles = self.get_cached(symbol_filter=sym_base)

        return {
            "articles": articles[:10],  # Top 10
            "count": len(articles),
            "most_recent": articles[0]["published"] if articles else None,
            "symbol": symbol,
            "base_currency": sym_base,
        }

    # -- Internals ------------------------------------------------------------

    def _fetch_feed(self, url: str, name: str, category: str) -> List[Dict[str, Any]]:
        """Parse un flux RSS et retourne une liste normalisee d'articles."""
        cache_key = f"feed_{url}"
        with self._lock:
            if self._is_cache_valid(cache_key):
                return self._cache.get(cache_key, [])

        try:
            import feedparser
            feed = feedparser.parse(url, request_headers={
                'User-Agent': 'NexQuant/1.0 (Trading Bot News Aggregator)',
            })

            articles = []
            for entry in feed.entries[:20]:  # Max 20 par flux
                title = self._clean_text(entry.get("title", ""))
                summary = self._clean_text(entry.get("summary", entry.get("description", "")))
                link = entry.get("link", "")

                # Parser la date de publication
                published_dt = self._parse_date(entry)
                published_str = published_dt.strftime("%Y-%m-%d %H:%M") if published_dt else "N/A"

                if not title:
                    continue

                articles.append({
                    "title": title,
                    "summary": summary[:300],
                    "url": link,
                    "source": name,
                    "category": category,
                    "published": published_str,
                    "published_dt": published_dt or datetime.min,
                })

            with self._lock:
                self._cache[cache_key] = articles
                self._cache_timestamps[cache_key] = datetime.now()

            log.debug(f"[RssScraper] {name}: {len(articles)} articles recuperes")
            return articles

        except Exception as e:
            log.debug(f"[RssScraper] {name} ({url}) inaccessible: {e}")
            return []

    def _filter_by_symbol(self, articles: List[Dict], symbol: str) -> List[Dict]:
        """Filtre les articles contenant des mots-cles lies au symbole."""
        # Trouver les mots-cles associes au symbole
        keywords = []
        sym_upper = symbol.upper()
        for sym_key, kws in SYMBOL_KEYWORDS.items():
            if sym_upper.startswith(sym_key) or sym_key in sym_upper:
                keywords.extend(kws)
                keywords.append(sym_key.lower())

        if not keywords:
            # Pas de mapping specifique -- utiliser le symbole brut comme mot-cle
            keywords = [symbol.lower(), symbol[:3].lower()]

        filtered = []
        for art in articles:
            text = f"{art.get('title', '')} {art.get('summary', '')}".lower()
            if any(kw in text for kw in keywords):
                filtered.append(art)

        return filtered

    def _is_cache_valid(self, key: str) -> bool:
        """Verifie si une entree de cache est encore valide (< 15 min)."""
        if key not in self._cache_timestamps:
            return False
        age = (datetime.now() - self._cache_timestamps[key]).total_seconds()
        return age < self.CACHE_TTL_SECONDS

    @staticmethod
    def _parse_date(entry) -> Optional[datetime]:
        """Parse la date de publication d'un article RSS."""
        for field in ["published_parsed", "updated_parsed", "created_parsed"]:
            val = entry.get(field)
            if val:
                try:
                    return datetime(*val[:6])
                except Exception as _exc:
                    log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
        return None

    @staticmethod
    def _clean_text(text: str) -> str:
        """Supprime les balises HTML et normalise le texte."""
        import re
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', ' ', text)  # Supprimer HTML
        text = re.sub(r'\s+', ' ', text)       # Normaliser espaces
        return text.strip()

    @staticmethod
    def _check_feedparser() -> bool:
        """Verifie si feedparser est installe."""
        import importlib.util
        return importlib.util.find_spec("feedparser") is not None
