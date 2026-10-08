# NexQuant SuperBot — guide pour Claude

Bot de trading algorithmique Python pour **MetaTrader 5** (Forex, or/argent, BTC le week-end).
Compte actuel : **FusionMarkets-Demo**, solde ~920 € (oct. 2026). Windows uniquement (API MT5 native).

## ⚠️ Règles de sécurité (à lire en premier)

- **Le bot tourne en direct depuis ce dossier.** `superbot/logs/` (journal des trades, état, logs)
  et `superbot/db/` (SQLite) sont l'état live : ne jamais les modifier, tronquer ou supprimer.
  Pour analyser, copier d'abord dans un dossier temporaire. Un redémarrage est nécessaire pour
  que le bot charge du code modifié.
- **`.env` contient les identifiants MT5 et des tokens** : ne jamais l'afficher ni le committer.
  `.env.example` documente les variables. Le `.env` surcharge les défauts de `config.py`.
- **Tests isolés** : `conftest.py` redirige logs, journal, état, base SQLite, rapports et modèle ML
  vers un dossier temporaire (`NEXQUANT_LOG_DIR`, `NEXQUANT_REPORTS_DIR`, `NEXQUANT_MODEL_PATH`,
  `DB_PATH`) et fixe `INSTRUMENTS`/`NEWS_ASSETS`. `tests/test_isolation.py` le vérifie.
  Tout nouveau chemin d'écriture doit passer par `superbot.config` (jamais `Path(__file__)` en dur).
- Le dépôt git est `nexquant/` (le dossier parent `nexquant_v2/` n'est pas versionné).
  Ne pas committer sans demande explicite ; il y a souvent du travail non commité de l'utilisateur
  (dashboard, `scripts/`, rapports).

## Commandes

```bash
python -m superbot.main                 # lancer le bot (lit .env, BROKER_TYPE=mt5)
python -m superbot.main --unpause       # forcer la reprise après pause
python -m superbot.main --reset-state   # réinitialiser l'état persistant
python -m pytest -q                     # tests (isolés, BACKTEST_MODE=true)
ruff check superbot                     # lint (pyproject.toml, line-length 120)
python -m artifacts.retrain_ml_scorer   # évaluer/réentraîner le modèle ML (voir ML)
```

## Architecture (superbot/)

Cycle (~15 s, bougies 15m) : `orchestrator.SuperBot` → `components/cycle_runner.py`
→ `_process_symbol` : `indicators/technical_indicators.py` → `strategy/strategy.py` (TradingStrategy)
→ `brain/regime_detector.py` + `brain/strategy_engine.py` (UNIFIED_ALPHA, ELDER, MURPHY, VOLMAN,
INTERMARKET, CHAN, LONDON_BREAKOUT) → `components/signal_executor.py` (filtres, ML, sizing, ordre)
→ `risk/risk_manager.py` + `risk/modules/` (position_sizer, stop_manager SL/TP/BE/trailing,
trade_recorder, risk_monitor, profit_circuit_breaker) → `broker/mt5_client.py`.
Clôtures : `components/position_syncer.py`. Autres : `brain/session_manager.py`, `brain/performance_learner.py`,
`news/news_manager.py`, `monitoring/bug_watchdog.py`, `dashboard/`, `db/database.py`, `config.py`.
`backtest/engine.py` rejoue `TradingStrategy` (même StrategyEngine que le live) avec la même logique de sortie.

## Données de trades

- **Source de vérité = deals MT5.** Les positions sont rapprochées par ticket :
  `MT5Client.get_closed_position(position_id)` (`history_deals_get(position=…)`).
- **Heure serveur MT5 (UTC+2/+3)** : les deals sont reconvertis en UTC via
  `MT5Client._server_utc_offset_seconds()` (ne jamais faire `fromtimestamp(deal.time, utc)`).
  Les **bougies restent en heure serveur** (minuit = clôture NY → pivots journaliers propres) et
  portent la colonne `server_utc_offset_s` ; toute logique horaire « UTC » (LondonBreakout, range
  asiatique) doit passer par `knowledge_base.utc_bar_times(df)`.
- `superbot/logs/trades_mt5.jsonl` : une ligne par trade. Champs clés : `position_id`, `verified`
  (True = P&L lu chez le broker, False = estimation), `close_reason` (sl/tp/expert/…/estimated),
  `strategy_name`, features d'entrée (rsi, adx, bb_pos, atr_pct, hour_of_day…).
  `merge_broker_history` (au démarrage) dédoublonne par `position_id` et ne tronque jamais le fichier.
- Lignes anciennes (avant oct. 2026) : doublons bot/broker et horodatages serveur ; utiliser
  `trade_recorder.dedupe_trade_rows` avant toute statistique.

## Paramètres importants (.env / config.py)

- `ML_SHADOW_MODE=true` (défaut) : le modèle ML ne fait que journaliser sa probabilité. Ne repasser
  à `false` qu'après `artifacts/retrain_ml_scorer.py` (≥ `ML_MIN_VERIFIED_TRADES` trades vérifiés,
  AUC hors échantillon ≥ `ML_MIN_AUC`). Au 06/10/2026 : AUC 0,37 → non prédictif.
- `ENTRY_EXHAUSTION_FILTER=false` (défaut, non validé) : refuse achats RSI ≥ RSI_OB / bb_pos > `ENTRY_BB_EXTREME`.
- `DAILY_TARGET_PCT=2` : objectif journalier indicatif (% du solde), sans effet sur le sizing.
- SL/TP live : `RiskManager.get_regime_sl_tp_multipliers` applique des ratios par régime
  (`_REGIME_SL_TP_RATIOS`) à la base `SL_ATR_MULT`/`TP_ATR_MULT` (défauts 1,5 / 3,0).
- `RuntimeConfig` est la source unique de `risk_pct` et `score_min` (multiplicateurs de session via
  `set_session_multipliers`). Score effectif = `StrategyEngine.effective_score_min` =
  min(10, max(`SCORE_MIN`, score runtime)). Le walk-forward (`ml/walk_forward.py`) ne calibre que
  `SCORE_MIN`, sur les trades vérifiés uniquement.
- Risque par trade = news × `PerformanceLearner.get_risk_multiplier()` : mode défensif ×0,3 (3 h),
  protection des gains ×0,5, remis à 1 chaque jour (`reset_daily`). Stratégies bloquées ignorées.
- `MURPHY_EXHAUSTION_GUARD=true` (défaut) : Murphy n'achète pas si RSI ≥ `RSI_OB`, ne vend pas si
  RSI ≤ `RSI_OS`. Validée sur 3 ans H1 broker (oct. 2023→oct. 2026) : PF Murphy 1,49/1,84
  (train/test) avec garde contre 1,42/1,53 sans.
- Étude du 07/10/2026 (H1 broker, coûts 0,01 % A/R ; frais réels mesurés : spread seul ~0,005-0,008 %,
  commission 0) : seul MURPHY_TREND a un avantage (PF ≈ 1,5-1,8 ; SL 2/TP 4 ATR le plus robuste).
  ELDER et UNIFIED_ALPHA perdent (PF ≈ 0,9). En 15m le système perd (PF ≈ 0,9). L'avantage
  **disparaît avec les sorties du live** (SL/TP ATR de `stop_manager`, PF ≈ 1,0) : il vient du SL
  Donchian de Murphy. Très sensible aux coûts (×2 → PF ≈ 1,0-1,2). DD ≈ 35 % à 1 % de risque/trade.
  Filtres testés — juger sur le gain total (R) et la régularité, pas sur le seul PF :
  **`MURPHY_MIN_ADX=25` retenu** (PF 1,70/1,94, gain total ≈ inchangé 698/699 R, 6 mois perdants /37).
  `SCORE_MIN=10` : PF 1,87/1,85 mais −40 % de gain total et 10 mois perdants (à ne pas utiliser).
  Tendance D1 (EMA50) + score 10 : PF 1,96/1,88 mais gain total le plus faible. Plafond hors
  échantillon ≈ 1,9 ; PF ≥ 2 seulement sur l'or.
- Backtest : `_simulate` passe désormais `df_full` (avec indicateurs) à la stratégie — avant le
  07/10/2026 il passait l'OHLCV brut (régimes faux, aucune tendance) : **tous les backtests antérieurs
  sont invalides**. Les sessions suivent l'heure de la bougie (`get_active_sessions(heure UTC)`).
  Le backtest n'applique ni SessionManager, ni PerformanceLearner, ni filtres news → il trade bien
  plus que le live.
- OFF_HOURS : seules les matières premières (or/argent) sont autorisées, hors rollover.
- Parité live/backtest (07/10/2026, défauts = ancien comportement) : `ENABLED_STRATEGIES` (filtre
  `StrategyEngine._build_strategies`), `USE_STRATEGY_SL_TP` (`signal_executor._strategy_sl_tp`),
  `SIGNAL_ON_CLOSED_BAR` (orchestrateur : bougie en formation exclue, une évaluation par bougie).
  Le plancher de risque de `position_sizer` vaut min(0,5 %, 0,3 × RISK_PCT).
- `MIN_LOT_MAX_RISK_PCT` (défaut 1,5 ; 2,0 dans le .env) : risque max accepté quand le lot minimum dépasse
  le risque cible (l'or avec le SL Donchian large était sinon toujours refusé).
- ⚠️ MT5 : toujours appeler les fonctions à argument via lambda dans `_call_api`
  (`lambda req=request: mt5.order_send(req)`). La librairie C refuse `f(*args, **kwargs)` même vide
  (« Unnamed arguments not allowed ») — régression du 07/10/2026 qui bloquait tous les ordres.
- Lancement : `scripts/start_bot.ps1`, `scripts/stop_bot.ps1`, `scripts/install_autostart.ps1` ; une seule
  instance possible (verrou `superbot_mt5.lock`). Pilotage téléphone : voir `docs/LANCEMENT_PC_TELEPHONE.md`.
- L'application web (télémétrie `NEXQUANT_*`) est abandonnée : variables commentées dans le .env.
- `DASHBOARD_HOST` (défaut `0.0.0.0`) ; `127.0.0.1` pour un accès local uniquement (pas d'authentification).
- Garde-fou : un compte `MT5_REAL` exige `ALLOW_LIVE_TRADING=true`.

## Conventions

- Code, commentaires, logs et commits en **français** (commits type `fix(module): ...`).
- Logs avec emojis et préfixes de module (`[OnlineLearner]`, `[GhostCleaner]`…).
- Toute modification de logique de trading doit être validée par backtest A/B avec une règle de
  décision fixée à l'avance (gain agrégé ET sur ≥ 2/3 symboles, ≥ 30 trades).
