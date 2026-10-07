"""
NexQuant V3 — Base de données SQLite persistante
==================================================
Phase 1 : Remplace le stockage JSON/fichier par une DB SQL robuste.

Tables :
  - trades          : Historique complet de tous les trades fermés
  - sessions        : Résumé de chaque session de trading (pre/mid/post analyse)
  - performance_log : Log horaire des métriques de performance
  - knowledge_items : Items ingérés par le KnowledgeFeeder (articles, insights)
  - ml_models       : Sauvegarde des modèles ML (hyperparams + scores)
  - symbol_profiles : Profils par symbole (volatility, best hours, win rate, etc.)
  - market_regimes  : Historique des régimes de marché détectés par HMM
  - adaptive_params : Log des ajustements adaptatifs (score_min, risk_pct, etc.)

Caractéristiques :
  - WAL mode pour accès concurrent (thread-safe)
  - Indices pour les requêtes critiques (hot path du trading)
  - Compression automatique des données >30j
  - Tolérance aux pannes (PRAGMA journal_mode=WAL)
"""

import sqlite3
import json
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path
from contextlib import contextmanager

log = logging.getLogger("nexquant.db")

# Version du schéma (pour les migrations futures)
SCHEMA_VERSION = 3


class NexQuantDB:
    """
    Base de données SQLite principale de NexQuant V3.
    
    Thread-safe via un RLock + connexion par thread (threading.local).
    Utilise le WAL mode pour la performance en lecture concurrente.
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Chemin configuré (superbot/db/nexquant.db par défaut, redirigé par les tests via DB_PATH)
            from superbot.config import DB_PATH
            db_path = DB_PATH

        self.db_path = db_path
        self._lock = threading.RLock()
        self._local = threading.local()  # Connexion par thread

        # Créer le répertoire si nécessaire
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialiser le schéma
        self._init_schema()
        log.info(f"NexQuantDB V3 initialisée : {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Retourne une connexion SQLite par thread (thread-safe)."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            conn.row_factory = sqlite3.Row
            # WAL mode pour performance en lecture concurrente
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def transaction(self):
        """Context manager pour les transactions atomiques."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Exécute une requête SQL avec gestion d'erreurs."""
        conn = self._get_connection()
        try:
            return conn.execute(sql, params)
        except sqlite3.Error as e:
            log.error(f"Erreur SQL : {e} | Query: {sql[:100]}")
            raise

    def executemany(self, sql: str, params_list: list):
        """Exécute une requête SQL sur plusieurs lignes."""
        conn = self._get_connection()
        conn.executemany(sql, params_list)
        conn.commit()

    def fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Exécute une requête SELECT et retourne toutes les lignes."""
        cursor = self.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """Exécute une requête SELECT et retourne la première ligne."""
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def _init_schema(self):
        """Crée toutes les tables et indices si non existants."""
        conn = self._get_connection()
        with conn:
            # ── Versionning du schéma ─────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version     INTEGER PRIMARY KEY,
                    applied_at  TEXT NOT NULL,
                    description TEXT
                )
            """)

            # ── TABLE TRADES ──────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id        TEXT UNIQUE,
                    symbol          TEXT NOT NULL,
                    side            TEXT NOT NULL,
                    entry_price     REAL,
                    exit_price      REAL,
                    size            REAL,
                    pnl             REAL,
                    pnl_pct         REAL,
                    strategy_name   TEXT,
                    market_regime   TEXT,
                    session_name    TEXT,
                    score           REAL,
                    rr_ratio        REAL,
                    sl_price        REAL,
                    tp_price        REAL,
                    atr_at_entry    REAL,
                    sentiment_score REAL,
                    duration_min    REAL,
                    opened_at       TEXT NOT NULL,
                    closed_at       TEXT,
                    broker          TEXT DEFAULT 'mt5',
                    is_paper        INTEGER DEFAULT 1,
                    tags            TEXT,           -- JSON array
                    metadata        TEXT            -- JSON object
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades(opened_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_pnl ON trades(pnl)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_name)")

            # ── TABLE SESSIONS ────────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date    TEXT NOT NULL,
                    session_name    TEXT,          -- 'asia' | 'london' | 'new_york' | 'overlap'
                    started_at      TEXT NOT NULL,
                    ended_at        TEXT,
                    balance_start   REAL,
                    balance_end     REAL,
                    pnl_total       REAL,
                    pnl_target      REAL,          -- objectif du jour (DAILY_TARGET_EUR adapté)
                    target_achieved INTEGER DEFAULT 0,
                    trades_count    INTEGER DEFAULT 0,
                    wins            INTEGER DEFAULT 0,
                    losses          INTEGER DEFAULT 0,
                    win_rate        REAL,
                    avg_rr          REAL,
                    max_drawdown    REAL,
                    volatility_regime TEXT,        -- 'low' | 'medium' | 'high'
                    best_strategy   TEXT,
                    worst_symbol    TEXT,
                    notes           TEXT,          -- JSON : insights auto-générés
                    pre_analysis    TEXT,          -- JSON : analyse pré-session
                    post_analysis   TEXT           -- JSON : débrief post-session
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date)")

            # ── TABLE PERFORMANCE_LOG ─────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS performance_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at       TEXT NOT NULL,
                    balance         REAL,
                    equity          REAL,
                    daily_pnl       REAL,
                    daily_target    REAL,
                    target_pct      REAL,          -- % de l'objectif atteint
                    open_positions  INTEGER,
                    cycle_time_avg  REAL,
                    win_rate_20     REAL,          -- WinRate sur 20 derniers trades
                    sharpe_ratio    REAL,
                    profit_factor   REAL,
                    current_drawdown REAL,
                    market_regime   TEXT,
                    session_name    TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_logged_at ON performance_log(logged_at)")

            # ── TABLE KNOWLEDGE_ITEMS ─────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_hash       TEXT UNIQUE,    -- MD5 du contenu pour déduplication
                    source_type     TEXT,          -- 'rss' | 'reddit' | 'babypips' | 'fred' | 'manual'
                    source_url      TEXT,
                    title           TEXT,
                    content         TEXT,
                    summary         TEXT,          -- Résumé auto-généré (100 mots max)
                    sentiment       REAL,          -- -1.0 à +1.0
                    relevance_score REAL,          -- Pertinence pour le trading 0-1
                    assets_mentioned TEXT,         -- JSON array ['BTC', 'EUR', 'USD']
                    fetched_at      TEXT NOT NULL,
                    published_at    TEXT,
                    expires_at      TEXT           -- Pour purge automatique
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON knowledge_items(item_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_items(source_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_fetched ON knowledge_items(fetched_at)")

            # ── TABLE ML_MODELS ───────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ml_models (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name      TEXT NOT NULL,  -- 'regime_hmm' | 'ensemble_scorer' | 'online_lr'
                    model_version   TEXT,
                    symbol          TEXT DEFAULT 'ALL',
                    trained_at      TEXT NOT NULL,
                    n_samples       INTEGER,
                    features        TEXT,           -- JSON list of feature names
                    hyperparams     TEXT,           -- JSON hyperparameters
                    metrics         TEXT,           -- JSON {'accuracy': 0.7, 'f1': 0.65}
                    model_blob      BLOB,           -- Serialized model (pickle)
                    is_active       INTEGER DEFAULT 1
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_name ON ml_models(model_name, is_active)")

            # ── TABLE SYMBOL_PROFILES ─────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS symbol_profiles (
                    symbol          TEXT PRIMARY KEY,
                    asset_class     TEXT,          -- 'forex' | 'crypto' | 'commodity'
                    avg_daily_range REAL,          -- ATR journalier moyen
                    avg_spread      REAL,
                    best_session    TEXT,          -- 'london' | 'new_york' | 'asia'
                    best_hours_utc  TEXT,          -- JSON [8, 9, 10, 14, 15]
                    win_rate        REAL,
                    avg_rr          REAL,
                    total_trades    INTEGER DEFAULT 0,
                    profitable_days INTEGER DEFAULT 0,
                    drawdown_risk   REAL,          -- Score de risque 0-1
                    best_strategy   TEXT,
                    worst_strategy  TEXT,
                    notes           TEXT,
                    updated_at      TEXT NOT NULL
                )
            """)

            # ── TABLE MARKET_REGIMES ──────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_regimes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT NOT NULL,
                    detected_at     TEXT NOT NULL,
                    regime          TEXT NOT NULL,  -- 'trending_bull' | 'trending_bear' | 'ranging' | 'high_vol' | 'breakout'
                    confidence      REAL,
                    adx_value       REAL,
                    atr_value       REAL,
                    volume_factor   REAL,
                    hmm_state       INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_regimes_symbol ON market_regimes(symbol, detected_at)")

            # ── TABLE ADAPTIVE_PARAMS ─────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_params (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    adjusted_at     TEXT NOT NULL,
                    trigger         TEXT,          -- 'post_session' | 'mid_session' | 'pre_session' | 'manual'
                    param_name      TEXT NOT NULL,
                    old_value       REAL,
                    new_value       REAL,
                    reason          TEXT,
                    balance_at_adj  REAL,
                    pnl_trigger     REAL           -- PnL qui a déclenché l'ajustement
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_adaptive_at ON adaptive_params(adjusted_at)")

            # ── TABLE DAILY_TARGETS ───────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_targets (
                    trade_date      TEXT PRIMARY KEY,
                    balance_start   REAL,
                    target_eur      REAL,          -- Objectif du jour adapté au solde
                    achieved_eur    REAL DEFAULT 0,
                    achievement_pct REAL DEFAULT 0,
                    status          TEXT DEFAULT 'pending',  -- 'pending'|'achieved'|'partial'|'failed'
                    notes           TEXT
                )
            """)

            # ── Enregistrer la version du schéma ─────────────────────────────
            conn.execute("""
                INSERT OR IGNORE INTO schema_version (version, applied_at, description)
                VALUES (?, ?, ?)
            """, (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat(), "NexQuant V3 initial schema"))

        log.info(f"Schéma DB V3 initialisé (version {SCHEMA_VERSION})")

    # =========================================================================
    # MÉTHODES TRADES
    # =========================================================================

    def insert_trade(self, trade: Dict[str, Any]) -> int:
        """Insère un trade fermé dans la DB. Retourne l'ID inséré."""
        sql = """
            INSERT OR REPLACE INTO trades
            (trade_id, symbol, side, entry_price, exit_price, size, pnl, pnl_pct,
             strategy_name, market_regime, session_name, score, rr_ratio,
             sl_price, tp_price, atr_at_entry, sentiment_score, duration_min,
             opened_at, closed_at, broker, is_paper, tags, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        # Les trades du position_syncer utilisent d'autres noms de champs (position_size,
        # timestamp = clôture, open_time, signal_score…) : on les mappe pour ne plus perdre
        # la taille ni confondre ouverture et clôture. position_id sert d'identifiant
        # stable (INSERT OR REPLACE ne crée donc plus de doublon pour une même position).
        trade_id = trade.get('trade_id') or (f"mt5-{trade['position_id']}" if trade.get('position_id') else None)
        closed_at = trade.get('closed_at') or (trade.get('timestamp') if trade.get('status') == 'closed' else None)
        metadata = dict(trade.get('metadata') or {})
        for key in ('verified', 'close_reason', 'position_id'):
            if trade.get(key) is not None:
                metadata.setdefault(key, trade.get(key))
        params = (
            trade_id,
            trade.get('symbol', ''),
            trade.get('side', ''),
            trade.get('entry_price'),
            trade.get('exit_price'),
            trade.get('size', trade.get('position_size')),
            trade.get('pnl'),
            trade.get('pnl_pct'),
            trade.get('strategy_name'),
            trade.get('market_regime'),
            trade.get('session_name'),
            trade.get('score', trade.get('signal_score')),
            trade.get('rr_ratio'),
            trade.get('sl_price', trade.get('stop_loss')),
            trade.get('tp_price', trade.get('take_profit')),
            trade.get('atr_at_entry'),
            trade.get('sentiment_score'),
            trade.get('duration_min'),
            trade.get('opened_at') or trade.get('open_time') or closed_at or datetime.now(timezone.utc).isoformat(),
            closed_at,
            trade.get('broker', 'mt5'),
            1 if trade.get('is_paper', True) else 0,
            json.dumps(trade.get('tags', [])),
            json.dumps(metadata, default=str)
        )
        with self.transaction() as conn:
            cursor = conn.execute(sql, params)
            return cursor.lastrowid

    def get_trades(
        self,
        symbol: str = None,
        days: int = 30,
        strategy: str = None,
        limit: int = 500
    ) -> List[Dict]:
        """Récupère les trades avec filtres optionnels."""
        conditions = ["1=1"]
        params = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conditions.append("opened_at >= ?")
            params.append(cutoff)
        if strategy:
            conditions.append("strategy_name = ?")
            params.append(strategy)

        params.append(limit)
        sql = f"""
            SELECT * FROM trades
            WHERE {' AND '.join(conditions)}
            ORDER BY opened_at DESC
            LIMIT ?
        """
        return self.fetchall(sql, tuple(params))

    def get_performance_stats(self, days: int = 30) -> Dict[str, Any]:
        """Calcule les statistiques de performance globales."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = self.fetchone("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                ROUND(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as win_rate,
                ROUND(SUM(pnl), 2) as total_pnl,
                ROUND(AVG(pnl), 2) as avg_pnl,
                ROUND(MAX(pnl), 2) as best_trade,
                ROUND(MIN(pnl), 2) as worst_trade,
                ROUND(AVG(rr_ratio), 2) as avg_rr,
                ROUND(AVG(duration_min), 1) as avg_duration_min
            FROM trades
            WHERE opened_at >= ?
        """, (cutoff,))
        return row or {}

    def get_daily_pnl(self, days: int = 30) -> List[Dict]:
        """Retourne le PnL journalier sur N jours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.fetchall("""
            SELECT
                DATE(opened_at) as trade_date,
                SUM(pnl) as daily_pnl,
                COUNT(*) as trades_count,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
            FROM trades
            WHERE opened_at >= ?
            GROUP BY DATE(opened_at)
            ORDER BY trade_date DESC
        """, (cutoff,))

    def bulk_insert_trades(self, trades: List[Dict[str, Any]]):
        """Insère un lot de trades (migration depuis JSON/broker)."""
        for trade in trades:
            try:
                self.insert_trade(trade)
            except Exception as e:
                log.warning(f"Skip trade (erreur insert) : {e}")
        log.info(f"Bulk insert : {len(trades)} trades insérés")

    # =========================================================================
    # MÉTHODES SESSIONS
    # =========================================================================

    def start_session(self, session_name: str, balance_start: float, pnl_target: float) -> int:
        """Démarre une nouvelle session de trading."""
        today = datetime.now(timezone.utc).date().isoformat()
        with self.transaction() as conn:
            cursor = conn.execute("""
                INSERT INTO sessions (session_date, session_name, started_at, balance_start, pnl_target)
                VALUES (?, ?, ?, ?, ?)
            """, (today, session_name, datetime.now(timezone.utc).isoformat(), balance_start, pnl_target))
            session_id = cursor.lastrowid
        log.info(f"Session '{session_name}' démarrée (ID={session_id}, target={pnl_target}€)")
        return session_id

    def close_session(self, session_id: int, stats: Dict[str, Any]):
        """Clôture une session avec ses statistiques."""
        with self.transaction() as conn:
            conn.execute("""
                UPDATE sessions SET
                    ended_at = ?,
                    balance_end = ?,
                    pnl_total = ?,
                    target_achieved = ?,
                    trades_count = ?,
                    wins = ?,
                    losses = ?,
                    win_rate = ?,
                    avg_rr = ?,
                    max_drawdown = ?,
                    volatility_regime = ?,
                    best_strategy = ?,
                    post_analysis = ?
                WHERE id = ?
            """, (
                datetime.now(timezone.utc).isoformat(),
                stats.get('balance_end'),
                stats.get('pnl_total', 0),
                1 if stats.get('pnl_total', 0) >= stats.get('pnl_target', 200) else 0,
                stats.get('trades_count', 0),
                stats.get('wins', 0),
                stats.get('losses', 0),
                stats.get('win_rate'),
                stats.get('avg_rr'),
                stats.get('max_drawdown'),
                stats.get('volatility_regime'),
                stats.get('best_strategy'),
                json.dumps(stats.get('post_analysis', {})),
                session_id
            ))

    def get_recent_sessions(self, days: int = 7) -> List[Dict]:
        """Retourne les sessions récentes."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        return self.fetchall("""
            SELECT * FROM sessions
            WHERE session_date >= ?
            ORDER BY started_at DESC
        """, (cutoff,))

    # =========================================================================
    # MÉTHODES KNOWLEDGE ITEMS
    # =========================================================================

    def insert_knowledge_item(self, item: Dict[str, Any]) -> bool:
        """
        Insère un item de connaissance.
        Retourne True si inséré, False si déjà existant (déduplication par hash).
        """
        import hashlib
        content_hash = hashlib.md5(
            (item.get('title', '') + item.get('content', '')).encode()
        ).hexdigest()

        existing = self.fetchone("SELECT id FROM knowledge_items WHERE item_hash = ?", (content_hash,))
        if existing:
            return False

        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO knowledge_items
                (item_hash, source_type, source_url, title, content, summary,
                 sentiment, relevance_score, assets_mentioned, fetched_at, published_at, expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                content_hash,
                item.get('source_type', 'rss'),
                item.get('source_url', ''),
                item.get('title', ''),
                item.get('content', ''),
                item.get('summary', ''),
                item.get('sentiment', 0.0),
                item.get('relevance_score', 0.5),
                json.dumps(item.get('assets_mentioned', [])),
                datetime.now(timezone.utc).isoformat(),
                item.get('published_at', ''),
                expires
            ))
        return True

    def get_knowledge_items(
        self,
        source_type: str = None,
        assets: List[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Récupère les items de connaissance récents et pertinents."""
        now = datetime.now(timezone.utc).isoformat()
        conditions = ["(expires_at IS NULL OR expires_at > ?)"]
        params = [now]

        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)

        params.append(limit)
        return self.fetchall(f"""
            SELECT * FROM knowledge_items
            WHERE {' AND '.join(conditions)}
            ORDER BY relevance_score DESC, fetched_at DESC
            LIMIT ?
        """, tuple(params))

    def purge_expired_knowledge(self) -> int:
        """Supprime les items expirés. Retourne le nombre supprimé."""
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            cursor = conn.execute("DELETE FROM knowledge_items WHERE expires_at < ?", (now,))
            deleted = cursor.rowcount
        if deleted > 0:
            log.info(f"Knowledge purge : {deleted} items expirés supprimés")
        return deleted

    # =========================================================================
    # MÉTHODES SYMBOL PROFILES
    # =========================================================================

    def upsert_symbol_profile(self, symbol: str, profile: Dict[str, Any]):
        """Crée ou met à jour le profil d'un symbole."""
        profile['updated_at'] = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO symbol_profiles
                (symbol, asset_class, avg_daily_range, avg_spread, best_session,
                 best_hours_utc, win_rate, avg_rr, total_trades, profitable_days,
                 drawdown_risk, best_strategy, worst_strategy, notes, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    avg_daily_range = excluded.avg_daily_range,
                    avg_spread = excluded.avg_spread,
                    best_session = excluded.best_session,
                    best_hours_utc = excluded.best_hours_utc,
                    win_rate = excluded.win_rate,
                    avg_rr = excluded.avg_rr,
                    total_trades = excluded.total_trades,
                    profitable_days = excluded.profitable_days,
                    drawdown_risk = excluded.drawdown_risk,
                    best_strategy = excluded.best_strategy,
                    worst_strategy = excluded.worst_strategy,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
            """, (
                symbol,
                profile.get('asset_class', 'forex'),
                profile.get('avg_daily_range'),
                profile.get('avg_spread'),
                profile.get('best_session'),
                json.dumps(profile.get('best_hours_utc', [])),
                profile.get('win_rate'),
                profile.get('avg_rr'),
                profile.get('total_trades', 0),
                profile.get('profitable_days', 0),
                profile.get('drawdown_risk'),
                profile.get('best_strategy'),
                profile.get('worst_strategy'),
                profile.get('notes', ''),
                profile['updated_at']
            ))

    def get_symbol_profile(self, symbol: str) -> Optional[Dict]:
        """Récupère le profil d'un symbole."""
        return self.fetchone("SELECT * FROM symbol_profiles WHERE symbol = ?", (symbol,))

    # =========================================================================
    # MÉTHODES PERFORMANCE LOG
    # =========================================================================

    def log_performance(self, metrics: Dict[str, Any]):
        """Enregistre un snapshot de performance."""
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO performance_log
                (logged_at, balance, equity, daily_pnl, daily_target, target_pct,
                 open_positions, cycle_time_avg, win_rate_20, sharpe_ratio,
                 profit_factor, current_drawdown, market_regime, session_name)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                metrics.get('balance'),
                metrics.get('equity'),
                metrics.get('daily_pnl', 0),
                metrics.get('daily_target', 200),
                metrics.get('target_pct', 0),
                metrics.get('open_positions', 0),
                metrics.get('cycle_time_avg'),
                metrics.get('win_rate_20'),
                metrics.get('sharpe_ratio'),
                metrics.get('profit_factor'),
                metrics.get('current_drawdown', 0),
                metrics.get('market_regime'),
                metrics.get('session_name')
            ))

    # =========================================================================
    # MÉTHODES ADAPTIVE PARAMS
    # =========================================================================

    def log_adaptive_adjustment(
        self,
        param_name: str,
        old_value: float,
        new_value: float,
        reason: str,
        trigger: str = 'auto',
        balance: float = 0,
        pnl_trigger: float = 0
    ):
        """Log un ajustement adaptatif de paramètre."""
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO adaptive_params
                (adjusted_at, trigger, param_name, old_value, new_value, reason, balance_at_adj, pnl_trigger)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                trigger, param_name, old_value, new_value, reason, balance, pnl_trigger
            ))

    # =========================================================================
    # MÉTHODES DAILY TARGETS
    # =========================================================================

    def set_daily_target(self, balance: float, target_eur: float):
        """Définit ou met à jour l'objectif du jour."""
        today = datetime.now(timezone.utc).date().isoformat()
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO daily_targets (trade_date, balance_start, target_eur)
                VALUES (?,?,?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    balance_start = excluded.balance_start,
                    target_eur = excluded.target_eur
            """, (today, balance, target_eur))

    def update_daily_achievement(self, achieved_eur: float):
        """Met à jour le PnL réalisé du jour."""
        today = datetime.now(timezone.utc).date().isoformat()
        row = self.fetchone("SELECT target_eur FROM daily_targets WHERE trade_date = ?", (today,))
        target = row['target_eur'] if row else 200.0
        pct = (achieved_eur / target * 100) if target > 0 else 0
        status = 'achieved' if achieved_eur >= target else ('partial' if achieved_eur > 0 else 'pending')
        with self.transaction() as conn:
            conn.execute("""
                UPDATE daily_targets SET achieved_eur=?, achievement_pct=?, status=?
                WHERE trade_date=?
            """, (achieved_eur, pct, status, today))

    def get_today_target(self) -> Optional[Dict]:
        """Retourne l'objectif du jour courant."""
        today = datetime.now(timezone.utc).date().isoformat()
        return self.fetchone("SELECT * FROM daily_targets WHERE trade_date=?", (today,))

    # =========================================================================
    # UTILITAIRES
    # =========================================================================

    def migrate_from_json_history(self, json_path: str) -> int:
        """
        Migration des données JSON existantes vers la DB.
        Compatible avec le format du RiskManager (trade_history).
        """
        if not os.path.exists(json_path):
            log.warning(f"Fichier JSON introuvable : {json_path}")
            return 0

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        trades = data if isinstance(data, list) else data.get('trades', [])
        count = 0
        for t in trades:
            try:
                # Normaliser le format JSON → format DB
                normalized = {
                    'trade_id': t.get('id') or t.get('ticket') or f"migrated_{count}",
                    'symbol': t.get('symbol', ''),
                    'side': t.get('side', ''),
                    'entry_price': t.get('entry_price', 0),
                    'exit_price': t.get('exit_price', 0),
                    'size': t.get('size', 0),
                    'pnl': t.get('pnl', 0),
                    'opened_at': t.get('timestamp', t.get('opened_at', datetime.now(timezone.utc).isoformat())),
                    'closed_at': t.get('closed_at'),
                    'broker': t.get('broker', 'mt5'),
                    'is_paper': t.get('is_paper', True),
                }
                self.insert_trade(normalized)
                count += 1
            except Exception as e:
                log.debug(f"Skip trade migration : {e}")
        log.info(f"Migration JSON → DB : {count}/{len(trades)} trades migrés depuis {json_path}")
        return count

    def vacuum(self):
        """Optimise la base de données (compactage)."""
        conn = self._get_connection()
        conn.execute("VACUUM")
        log.info("DB vacuum effectué")

    def get_db_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur la base de données."""
        stats = {}
        for table in ['trades', 'sessions', 'knowledge_items', 'symbol_profiles',
                      'market_regimes', 'adaptive_params', 'performance_log']:
            row = self.fetchone(f"SELECT COUNT(*) as cnt FROM {table}")
            stats[table] = row['cnt'] if row else 0
        stats['db_path'] = self.db_path
        stats['db_size_mb'] = round(os.path.getsize(self.db_path) / 1024 / 1024, 2) if os.path.exists(self.db_path) else 0
        return stats

    def close(self):
        """Ferme la connexion proprement."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON : Instance globale partagée
# ═══════════════════════════════════════════════════════════════════════════════
_db_instance: Optional[NexQuantDB] = None
_db_lock = threading.Lock()


def get_db(db_path: str = None) -> NexQuantDB:
    """
    Retourne l'instance singleton de la DB.
    Thread-safe via double-checked locking.
    """
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = NexQuantDB(db_path)
    return _db_instance


def init_db(db_path: str = None) -> NexQuantDB:
    """Initialise la DB avec un chemin spécifique (à appeler au démarrage)."""
    global _db_instance
    with _db_lock:
        _db_instance = NexQuantDB(db_path)
    return _db_instance
