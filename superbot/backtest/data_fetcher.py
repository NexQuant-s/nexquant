"""
NexQuant DataFetcher — Phase 1 Backtesting
==========================================
Télécharge les données OHLCV historiques réelles depuis les brokers NexQuant
(Binance, Alpaca, MT5) avec pagination automatique et cache local CSV.

Fallback automatique sur yfinance si aucun broker n'est configuré.

Usage :
    fetcher = DataFetcher('binance')
    df = fetcher.fetch('BTCUSDT', '1h', start='2024-01-01', end='2024-12-31')

    # Force le re-téléchargement même si le cache existe
    df = fetcher.fetch('BTCUSDT', '1h', start='2024-01-01', force_refresh=True)
"""
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger("backtest.data_fetcher")

# Répertoire de cache local (nexquant/superbot/backtest/cache/)
CACHE_DIR = Path(__file__).parent / "cache"


class DataFetcher:
    """
    Télécharge et met en cache les données OHLCV historiques.

    Stratégie de source (par ordre de priorité) :
      1. Cache local CSV (si valide et non expiré)
      2. Broker NexQuant natif (Binance / Alpaca / MT5) avec pagination
      3. yfinance (fallback universel sans clé API)
    """

    # Mapping des timeframes vers des timedeltas pour la pagination
    TIMEFRAME_DELTA = {
        '1m':  timedelta(minutes=1),
        '5m':  timedelta(minutes=5),
        '15m': timedelta(minutes=15),
        '30m': timedelta(minutes=30),
        '1h':  timedelta(hours=1),
        '4h':  timedelta(hours=4),
        '1d':  timedelta(days=1),
        '1w':  timedelta(weeks=1),
    }

    # Mapping des timeframes pour yfinance
    YFINANCE_INTERVAL_MAP = {
        '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1h', '4h': '4h', '1d': '1d', '1w': '1wk',
    }

    def __init__(self, broker_type: str = 'mt5', cache_dir: Optional[Path] = None):
        """
        Args:
            broker_type: Type de broker ('binance', 'alpaca', 'mt5', 'yfinance')
            cache_dir: Répertoire de cache (défaut: superbot/backtest/cache/)
        """
        self.broker_type = broker_type.lower()
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Limite de bougies par requête selon le broker
        self._page_size = 1000 if self.broker_type == 'binance' else 500

    # ─── API publique ────────────────────────────────────────────────────────

    def fetch(
        self,
        symbol: str,
        timeframe: str = '1h',
        start: Optional[str] = None,
        end: Optional[str] = None,
        periods: int = 2000,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Retourne un DataFrame OHLCV complet pour le symbole et la période demandés.

        Args:
            symbol    : Symbole de l'instrument (ex: 'BTCUSDT', 'SPY', 'EURUSD')
            timeframe : Intervalle de temps ('1m','5m','15m','30m','1h','4h','1d','1w')
            start     : Date de début ISO (ex: '2024-01-01'). Si None, calcule depuis `periods`.
            end       : Date de fin ISO (ex: '2024-12-31'). Si None, utilise maintenant.
            periods   : Nombre de bougies à télécharger si start n'est pas fourni.
            force_refresh: Si True, ignore le cache et re-télécharge.

        Returns:
            DataFrame avec colonnes ['open','high','low','close','volume'] et index DatetimeIndex.
        """
        # Normaliser les dates
        end_dt = self._parse_date(end) if end else datetime.now(timezone.utc)
        if start:
            start_dt = self._parse_date(start)
        else:
            delta = self.TIMEFRAME_DELTA.get(timeframe, timedelta(hours=1))
            start_dt = end_dt - delta * periods

        # Vérifier le cache
        cache_key = self._cache_key(symbol, timeframe, start_dt, end_dt)
        cache_path = self.cache_dir / f"{cache_key}.csv"

        if not force_refresh and cache_path.exists():
            log.info(f"[DataFetcher] Cache hit — {cache_path.name}")
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            log.info(f"[DataFetcher] {len(df)} bougies chargées depuis le cache.")
            return df

        # Télécharger les données
        log.info(f"[DataFetcher] Téléchargement : {symbol} {timeframe} {start_dt.date()} → {end_dt.date()}")
        df = self._download(symbol, timeframe, start_dt, end_dt)

        if df is None or df.empty:
            raise ValueError(
                f"Impossible de télécharger des données pour {symbol} ({timeframe}) "
                f"sur la période {start_dt.date()} → {end_dt.date()}."
            )

        # Sauvegarder en cache
        df.to_csv(cache_path)
        log.info(f"[DataFetcher] {len(df)} bougies sauvegardées → {cache_path.name}")
        return df

    def list_cache(self) -> list:
        """Liste les entrées de cache disponibles."""
        return [f.stem for f in self.cache_dir.glob("*.csv")]

    def clear_cache(self, symbol: Optional[str] = None):
        """Vide le cache (tout ou filtré par symbole)."""
        for f in self.cache_dir.glob("*.csv"):
            if symbol is None or symbol.upper() in f.stem.upper():
                f.unlink()
                log.info(f"[DataFetcher] Cache supprimé : {f.name}")

    # ─── Téléchargement par source ───────────────────────────────────────────

    def _download(self, symbol: str, timeframe: str, start_dt: datetime, end_dt: datetime) -> Optional[pd.DataFrame]:
        """Tente le téléchargement par ordre de priorité des sources."""

        # 1. Binance public klines (sans clé API, historique complet)
        if self.broker_type == 'binance':
            df = self._download_from_binance_public(symbol, timeframe, start_dt, end_dt)
            if df is not None and not df.empty:
                return df
            log.warning("[DataFetcher] Binance public indisponible — fallback broker natif.")

        # 2. Broker natif NexQuant
        if self.broker_type in ('binance', 'alpaca', 'mt5'):
            df = self._download_from_broker(symbol, timeframe, start_dt, end_dt)
            if df is not None and not df.empty:
                return df
            log.warning(f"[DataFetcher] Broker {self.broker_type} indisponible — fallback yfinance.")

        # 3. Fallback yfinance (universel, sans clé API)
        return self._download_from_yfinance(symbol, timeframe, start_dt, end_dt)

    def _download_from_binance_public(self, symbol: str, timeframe: str,
                                      start_dt: datetime, end_dt: datetime) -> Optional[pd.DataFrame]:
        """
        Télécharge via l'API publique spot Binance (aucune clé requise) avec
        pagination sur startTime/endTime — indispensable pour l'historique
        intraday (15m/1h) que le testnet futures ne conserve pas.
        """
        try:
            from binance.client import Client
        except ImportError:
            log.warning("[DataFetcher] python-binance non installé.")
            return None

        binance_symbol = symbol.replace('/', '').upper()
        interval = timeframe  # '1m'/'5m'/'15m'/'1h'… sont des intervalles spot valides
        delta = self.TIMEFRAME_DELTA.get(timeframe, timedelta(hours=1))
        page_limit = 1000
        window = delta * page_limit

        client = Client(api_key='', api_secret='')
        frames: list = []
        current_start = start_dt

        while current_start < end_dt:
            current_end = min(current_start + window, end_dt)
            try:
                klines = client.get_klines(
                    symbol=binance_symbol,
                    interval=interval,
                    startTime=int(current_start.timestamp() * 1000),
                    endTime=int(current_end.timestamp() * 1000),
                    limit=page_limit,
                )
            except Exception as e:
                log.warning(f"[DataFetcher] Erreur klines publics {binance_symbol} {current_start.date()}: {e}")
                break

            if not klines:
                break

            df_page = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore',
            ])
            df_page['open_time'] = pd.to_datetime(df_page['open_time'], unit='ms', utc=True)
            df_page = df_page.set_index('open_time')
            for col in ('open', 'high', 'low', 'close', 'volume'):
                df_page[col] = pd.to_numeric(df_page[col], errors='coerce')
            df_page = df_page[['open', 'high', 'low', 'close', 'volume']]
            frames.append(df_page)

            if len(klines) < page_limit:
                break
            # Avancer au-delà de la dernière bougie pour ne pas dupliquer la frontière
            current_start = df_page.index[-1] + delta

        if not frames:
            return None

        df = pd.concat(frames).sort_index()
        df = df[~df.index.duplicated(keep='first')]
        mask = (df.index >= start_dt) & (df.index <= end_dt)
        df = df[mask]
        return self._normalize_ohlcv(df)

    def _download_from_broker(self, symbol: str, timeframe: str,
                              start_dt: datetime, end_dt: datetime) -> Optional[pd.DataFrame]:
        """
        Télécharge via le broker NexQuant avec pagination automatique.
        Chaque appel est limité (500-1000 bougies) → on boucle sur des fenêtres glissantes.
        """
        try:
            from superbot.broker.base import create_broker
            broker = create_broker(self.broker_type)
        except Exception as e:
            log.warning(f"[DataFetcher] Impossible de créer le broker '{self.broker_type}': {e}")
            return None

        delta = self.TIMEFRAME_DELTA.get(timeframe, timedelta(hours=1))
        window = delta * self._page_size  # Fenêtre couverte par un seul appel

        all_frames = []
        current_start = start_dt

        while current_start < end_dt:
            current_end = min(current_start + window, end_dt)
            # Nombre de bougies pour cette fenêtre
            pages_count = int((current_end - current_start) / delta) + 1

            try:
                broker_symbol = broker.normalize_symbol(symbol)
                df_page = broker.fetch_candles(
                    symbol=broker_symbol,
                    timeframe=timeframe,
                    limit=min(pages_count, self._page_size)
                )
                if df_page is not None and not df_page.empty:
                    # Filtrer sur la fenêtre demandée
                    df_page.index = pd.to_datetime(df_page.index, utc=True)
                    mask = (df_page.index >= current_start) & (df_page.index <= current_end)
                    df_page = df_page[mask]
                    if not df_page.empty:
                        all_frames.append(df_page)
                        log.debug(f"[DataFetcher] Page {current_start.date()} → {current_end.date()} : {len(df_page)} bougies")
            except Exception as e:
                log.warning(f"[DataFetcher] Erreur page {current_start.date()}: {e}")

            current_start = current_end + delta

        if not all_frames:
            return None

        df = pd.concat(all_frames).sort_index()
        df = df[~df.index.duplicated(keep='first')]  # Déduplication
        return self._normalize_ohlcv(df)

    def _download_from_yfinance(self, symbol: str, timeframe: str,
                                start_dt: datetime, end_dt: datetime) -> Optional[pd.DataFrame]:
        """
        Fallback : télécharge via yfinance (aucune clé API requise).
        Compatible avec les actions US, ETFs, crypto (via -USD suffix), et Forex.
        """
        try:
            import yfinance as yf
        except ImportError:
            log.error(
                "[DataFetcher] yfinance non installé. "
                "Installez-le avec : pip install yfinance"
            )
            return None

        # Adapter le symbole pour yfinance
        yf_symbol = self._adapt_symbol_for_yfinance(symbol)
        yf_interval = self.YFINANCE_INTERVAL_MAP.get(timeframe, '1h')

        log.info(f"[DataFetcher] yfinance : {yf_symbol} interval={yf_interval}")
        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(
                start=start_dt.strftime('%Y-%m-%d'),
                end=end_dt.strftime('%Y-%m-%d'),
                interval=yf_interval,
                auto_adjust=True,
            )
            if df.empty:
                log.error(f"[DataFetcher] yfinance n'a retourné aucune donnée pour {yf_symbol}.")
                return None

            df.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low',
                'Close': 'close', 'Volume': 'volume'
            }, inplace=True)
            df.index = pd.to_datetime(df.index, utc=True)
            log.info(f"[DataFetcher] yfinance : {len(df)} bougies récupérées.")
            return self._normalize_ohlcv(df)

        except Exception as e:
            log.error(f"[DataFetcher] Erreur yfinance pour {yf_symbol}: {e}")
            return None

    # ─── Utilitaires ─────────────────────────────────────────────────────────

    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise le DataFrame pour garantir les colonnes et types corrects."""
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                df[col] = 0.0
        df = df[required].copy()
        for col in required:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
        df.sort_index(inplace=True)
        return df

    def _adapt_symbol_for_yfinance(self, symbol: str) -> str:
        """Convertit un symbole NexQuant en format yfinance."""
        symbol = symbol.upper().replace('/', '')
        # Crypto (ex: BTCUSDT → BTC-USD)
        if symbol.endswith('USDT'):
            return symbol[:-4] + '-USD'
        if symbol.endswith('BUSD'):
            return symbol[:-4] + '-USD'
        # Forex (ex: EURUSD → EURUSD=X)
        if len(symbol) == 6 and symbol.isalpha():
            return symbol + '=X'
        # Actions/ETFs restent identiques (ex: SPY, AAPL)
        return symbol

    def _cache_key(self, symbol: str, timeframe: str,
                   start_dt: datetime, end_dt: datetime) -> str:
        """Génère une clé de cache unique et lisible."""
        raw = f"{self.broker_type}_{symbol}_{timeframe}_{start_dt.date()}_{end_dt.date()}"
        # Hash court pour éviter les noms de fichiers trop longs
        short_hash = hashlib.md5(raw.encode()).hexdigest()[:8]
        safe_symbol = symbol.replace('/', '_').replace('-', '_')
        return f"{safe_symbol}_{timeframe}_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}_{short_hash}"

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse une date ISO en datetime UTC."""
        for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"Format de date non reconnu : '{date_str}'. Utilisez YYYY-MM-DD.")
