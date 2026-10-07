# 📈 NexQuant SuperBot — Intelligence de Trading Quantitative MT5

**NexQuant SuperBot** est un moteur de trading algorithmique et quantitatif haute performance conçu en **Python**, dédié exclusivement au trading automatisé sur le **Forex et les Matières Premières** via le broker **MetaTrader 5 (MT5)**.

Le système intègre une architecture modulaire robuste, combinant détection de régime de marché multi-timeframes, sélection dynamique de stratégies d'élite, gestion du risque institutionnelle, ingestion de flux fondamentaux/macroéconomiques, et surveillance continue anti-anomalies avec *Kill-Switch*.

---

## 🏛️ Architecture & Structure de Fonctionnement

Le cycle de décision du SuperBot repose sur un pipeline séquentiel et parallèle entièrement automatisé :

```
                               ┌────────────────────────────────────────┐
                               │       Flux Macro & Calendrier          │
                               │  - Ingestion Calendrier ForexFactory   │
                               │  - Sentiment VADER & Fear & Greed      │
                               │  - Filtre anti-annonces économiques    │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
┌────────────────────────┐     ┌────────────────────────────────────────┐     ┌────────────────────────┐
│     Broker MT5 API     │ ──► │                BRAIN V3                │ ──► │  Sélection Stratégie   │
│  - Flux Ticks & OHLCV  │     │  - Détecteur de Régime (7 états)       │     │  - 6 Stratégies Élite  │
│  - Specs & StopLevels  │     │  - SessionManager (London/NY Overlap)  │     │  - Scorer Probabiliste │
│  - Synchro Positions   │     │  - Machine Learning & Calibration WR   │     │  - Calcul R:R & Entry  │
└────────────────────────┘     └──────────────────┬─────────────────────┘     └────────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │           RISK MANAGER V3              │
                               │  - Sizing précis par lot & notionnel   │
                               │  - Filtre d'exposition devises nettes  │
                               │  - Anti-pyramidage & Cooldown symbole  │
                               │  - Trailing Stop & Break-Even ATR      │
                               │  - Trailing Profit Circuit Breaker     │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │         EXÉCUTION & SURVEILLANCE       │
                               │  - Ordres MT5 (Slippage Re-clamping)   │
                               │  - BugWatchdog (Surveillance 60s)      │
                               │  - GhostCleaner (Anti-fantômes)        │
                               │  - Dashboard Web (Port 5000) & Prom    │
                               └────────────────────────────────────────┘
```

---

## 🧩 Modules Clés du Système

### 1. 🧠 Le Cerveau (`superbot/brain/`)
* **`MarketRegimeDetector`** : Détecte en temps réel le régime de chaque actif (*Trending Bull, Trending Bear, Ranging, Breakout, Pre-Breakout, High Volatility, Choppy Noise*) via une combinaison d'indicateurs vectorisés (ADX, Bandes de Bollinger, ATR, RSI, EMAs multi-périodes).
* **`StrategyEngine`** : Route dynamiquement chaque actif vers la stratégie la plus adaptée à son régime et à la session de marché courante.
* **`SessionManager`** : Ajuste les seuils de score et les multiplicateurs de risque selon les sessions mondiales :
  - **ASIAN / TOKYO** : Ranging / Mean-reversion
  - **LONDON** : Breakouts et tendances émergentes
  - **OVERLAP (London + New York)** : Liquidité maximale Forex & Matières Premières
  - **NEW YORK** : Continuation et momentum
* **`KnowledgeFeeder`** : Ingestion asynchrone des flux d'actualités, calendrier économique ForexFactory, flux RSS et sentiment Fear & Greed.

### 2. ♟️ Les 6 Stratégies d'Élite (`superbot/strategy/`)
Toutes les stratégies héritent d'une classe abstraite commune `BaseStrategy` garantissant un format de signal standardisé :
1. **`ElderTripleScreenStrategy`** (Alexander Elder) : Filtrage sur 3 écrans (Tendance H4 par EMA/MACD, Pullback M15 par Force Index/Stochastique, Trigger M5).
2. **`ChanMeanReversionStrategy`** (Ernie Chan) : Retour à la moyenne sur régimes de range et forte volatilité via Bollinger Bands et déviation Z-Score.
3. **`MurphyTrendStrategy`** (John Murphy) : Suivi de tendance pure basé sur les canaux de Donchian, l'alignement des moyennes mobiles et le momentum.
4. **`VolmanPriceActionStrategy`** (Bob Volman) : Détection de compressions de volatilité, cassures de consolidation et rebonds avec validation Price Action.
5. **`LondonBreakoutStrategy`** : Exploitation de la cassure du range asiatique lors de l'ouverture de Londres avec confirmation de volume.
6. **`IntermarketMomentumStrategy`** : Exploitation des corrélations macroéconomiques et dynamiques intermarchés (ex: Dollar Index vs Métaux précieux vs Devises).

### 3. 🛡️ Gestion du Risque & Sécurité (`superbot/risk/`)
* **Dimensionnement institutionnel des lots** : Calcul exact de la taille d'ordre en fonction du risque par trade (% du solde), de la distance du Stop-Loss en ATR, du `contract_size` MT5 et de la valeur du tick.
* **Filtre de corrélation des devises** : Calcul de l'exposition nette sur chaque monnaie (`EUR`, `USD`, `GBP`, `JPY`, etc.) avec blocage automatique en cas de sur-exposition.
* **Filtres de spread et session** : Rejet automatique des ordres si le spread courtier s'élargit au-delà du seuil toléré ou en dehors des fenêtres autorisées.
* **Stop-Loss & Take-Profit dynamiques** : Clamping automatique des SL/TP par rapport aux StopLevels du courtier et au slippage de marché.
* **Break-Even & Trailing Stop** : Rapprochement du SL dès l'atteinte d'un ratio R:R cible pour sécuriser les gains.
* **Trailing Profit Circuit Breaker** : Verrouillage des bénéfices journaliers dès l'atteinte de l'objectif (ex: +200€) pour éviter les retracements de fin de session.

### 4. 🔍 Surveillance Continue (`superbot/monitoring/`)
* **`BugWatchdog`** : Thread de surveillance indépendant inspectant toutes les 60 secondes la cohérence des positions, l'intégrité de la mémoire, les heartbeats de cycle et la connexion courtier.
* **`GhostCleaner`** : Détecte et élimine les ordres ou positions désynchronisés entre la mémoire du bot et MetaTrader 5.

Installation rapide

1) Backend (bot Python)

```
nexquant/
├── superbot/                       # 🐍 Moteur de trading Python (SuperBot)
│   ├── brain/                     # Cerveau central (Régimes, Sessions, Stratégies, News)
│   │   ├── regime_detector.py     # Détection des régimes de marché
│   │   ├── session_manager.py     # Gestion des sessions (London, NY, Overlap, Tokyo)
│   │   ├── strategy_engine.py     # Sélection dynamique des stratégies
│   │   └── knowledge_feeder.py    # Ingestion calendrier & sentiment
│   ├── broker/                    # Adaptateur courtier MetaTrader 5
│   │   ├── mt5_client.py          # Client API MT5 haute résilience
│   │   └── symbol_specs.py        # Spécifications & alias des symboles (Forex & Commodities)
│   ├── components/                # Composants d'orchestration et d'exécution
│   │   ├── cycle_runner.py        # Boucle principale de scan parallèle
│   │   ├── signal_executor.py     # Validation, sizing et exécution des ordres
│   │   ├── position_syncer.py     # Synchronisation bidirectionnelle des positions
│   │   ├── forex_filters.py       # Filtres de spread, corrélation et sessions
│   │   └── ghost_cleaner.py       # Nettoyage des positions fantômes
│   ├── strategy/                  # Implémentations des stratégies de trading
│   │   ├── base_strategy.py       # Classe de base pour toutes les stratégies
│   │   ├── elder_triple_screen.py # Stratégie Elder Triple Screen
│   │   ├── chan_mean_reversion.py # Stratégie Chan Mean Reversion
│   │   ├── murphy_trend.py        # Stratégie Murphy Trend Following
│   │   ├── volman_price_action.py # Stratégie Volman Price Action
│   │   ├── london_breakout.py     # Stratégie London Breakout
│   │   ├── intermarket_momentum.py# Stratégie Momentum Intermarchés
│   │   └── knowledge_base.py      # Indicateurs et formules avancées
│   ├── risk/                      # Gestion du risque et dimensionnement
│   │   ├── risk_manager.py        # Gestionnaire de risque central et circuit breaker
│   │   └── modules/               # Modules de sizing, stops, profit lock et recording
│   ├── indicators/                # Indicateurs techniques vectorisés (OHLCV)
│   ├── monitoring/                # Surveillance anti-bugs (BugWatchdog)
│   ├── news/                      # Gestionnaire NLP de nouvelles et sentiment
│   ├── orchestrator.py            # Classe principale SuperBot
│   └── main.py                    # Point d'entrée de l'application
├── tests/                         # 🧪 Suite de tests automatisés (Unit & E2E)
│   ├── test_broker_mt5.py         # Tests du client MT5 et passage d'ordres
│   ├── test_strategies.py         # Tests unitaires de toutes les stratégies
│   ├── test_market_regime_detector.py # Tests de détection de régime
│   ├── test_symbol_specs.py       # Tests de normalisation et calcul de lots
│   └── test_end_to_end_bot.py     # Tests d'intégration de bout en bout
├── resources/                     # Modèles ML pré-entraînés et dictionnaires
├── requirements.txt               # Dépendances Python requises
├── pyproject.toml                 # Configuration du projet Python
└── README.md                      # Documentation du projet
```

---

## 🚀 Installation & Démarrage

### Prérequis Système
1. **Système d'exploitation** : Windows 10/11 ou Windows Server (requis pour l'API native MetaTrader 5).
2. **Python** : Version 3.10 à 3.13 (64-bit).
3. **Terminal MetaTrader 5** : Installé et connecté à un compte de courtier (ex: Fusion Markets, IC Markets, etc.) avec l'option **"Autoriser le trading algorithmique"** activée dans les options de la plateforme.

### 1. Cloner le Dépôt
```bash
git clone https://github.com/NexQuant-s/nexquant.git
cd nexquant
```

### 2. Créer l'Environnement Virtuel & Installer les Dépendances
```bash
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configuration du Fichier `.env`
Créez un fichier `.env` à la racine du dossier `nexquant/` (ou copiez `.env.example`) en vous basant sur le modèle ci-dessous :

```env
# ======================
# SÉLECTION DU BROKER
# ======================
BROKER_TYPE=mt5

# ======================
# METATRADER 5 (Fusion Markets, IC Markets, etc.)
# ======================
MT5_LOGIN=123456
MT5_PASSWORD=votre_mot_de_passe
MT5_SERVER=FusionMarkets-Demo
MT5_PATH=C:\Program Files\MetaTrader 5

# ======================
# PARAMÈTRES DE TRADING
# ======================
INSTRUMENTS_MT5=EURUSD,GBPUSD,USDJPY,USDCAD,NZDUSD,EURJPY,GBPJPY,XAUUSD,XAGUSD,WTIUSD,USDCHF,AUDUSD,EURGBP
GRANULARITY=15m
CYCLE_TIME=15

# ======================
# GESTION DU RISQUE V3
# ======================
RISK_PCT=1.0                  # % du capital risqué par trade
MAX_DAILY_LOSS_PCT=2.0        # % max de perte journalière avant arrêt
MAX_MONTHLY_LOSS_PCT=5.0      # % max de perte mensuelle
MAX_OPEN_POSITIONS_MT5=3      # Nombre max de positions simultanées
MAX_SPREAD_PIPS=2.5           # Spread maximal toléré
MAX_FOREX_CURRENCY_EXPOSURE=2 # Exposition max par devise
SL_ATR_MULT=1.5               # Multiplicateur ATR Stop Loss
TP_ATR_MULT=3.0               # Multiplicateur ATR Take Profit
TRAIL_ATR_MULT=2.0            # Multiplicateur ATR Trailing Stop
BE_ATR_MULT=1.5               # Multiplicateur ATR Break-Even
BE_DYN_RR=true                # Break-Even dynamique activé

# ======================
# STRATÉGIE
# ======================
SCORE_MIN=6
SCORE_MIN_FOREX=6
EMA_FAST_FOREX=21
EMA_SLOW_FOREX=55
ADX_TREND_FOREX=20
SL_ATR_MULT_FOREX=1.5
TP_ATR_MULT_FOREX=3.0

# ======================
# NOUVELLES & MACRO
# ======================
NEWS_ASSETS_MT5=EUR,USD,GBP,JPY,CAD,CHF,AUD,NZD
NEWS_AVOIDANCE_BEFORE=30      # Minutes d'évitement avant news HIGH impact
NEWS_AVOIDANCE_AFTER=15       # Minutes d'évitement après news HIGH impact

# ======================
# TSMOM (Macro Momentum)
# ======================
TSMOM_ENABLED=true
TSMOM_PLACE_ORDERS=true
TSMOM_TARGET_VOL=0.12
TSMOM_MAX_LEVERAGE=1.5
```

- **`BROKER_TYPE`** — Courtier actif (`mt5`)
- **`MT5_LOGIN`** — Numéro de compte MetaTrader 5
- **`INSTRUMENTS_MT5`** — Liste des actifs surveillés (Forex, Or, Argent, Pétrole)
- **`RISK_PCT`** — Pourcentage de risque alloué par position
- **`MAX_DAILY_LOSS_PCT`** — Limite de perte journalière (déclenche le Kill-Switch)

## 🎮 Lancement du SuperBot

### Démarrage Standard
Lance le bot en reprenant l'état sauvegardé de la session précédente :
```bash
python -m superbot.main
```

### Démarrage Propre / Réinitialisation de Session (`--reset-state`)
Recommandé au début d'une nouvelle journée de trading pour réinitialiser le PnL journalier et repartir sur un état propre :
```bash
python -m superbot.main --reset-state
```

### Forcer la Reprise après une Pause (`--unpause`)
Permet de débloquer manuellement le bot s'il a été mis en pause :
```bash
python -m superbot.main --unpause
```

### Personnaliser le Port du Dashboard Web
```bash
python -m superbot.main --dashboard-port 5000
```

Une fois démarré, le Dashboard local est accessible sur `http://localhost:5000` et les métriques Prometheus sur `http://localhost:8000/metrics`.

### Visualisation des stratégies et des backtests

Le dashboard propose les vues `Performance`, `Journal des trades`, `Comparaison` et `Optimisation` depuis sa navigation. Les vues de performance et de trades utilisent l'historique fermé du bot. Le journal affiche toutes les paires dans le P&L net et permet de sélectionner une paire pour comparer ses prix d'entrée et de sortie. La comparaison et l'optimisation lisent les rapports JSON générés par `BacktestReport.save_json()` dans `superbot/backtest/results/`.

Le dossier de rapports peut être remplacé par la variable `BACKTEST_RESULTS_DIR`. La comparaison requiert au moins deux rapports; les corrélations sont calculées sur leurs mois communs. La sensibilité requiert des valeurs numériques différentes dans `params_used`. Les résultats walk-forward sont affichés lorsqu'ils sont inclus, même sans balayage de paramètres. Sans données suffisantes, les pages indiquent ce qui manque sans afficher de graphiques vides ou factices.

Le visualizer autonome accepte les JSON natifs de `BacktestReport.save_json()` ainsi que les anciens rapports avec sections `metadata`, `metrics` et `stats` :

```powershell
python scripts/backtest_visualizer.py --input "superbot/backtest/results/*.json" --compare --output reports/analysis.html
python scripts/backtest_visualizer.py --input "superbot/backtest/results/*.json" --optimize SCORE_MIN RISK_PCT --output reports/optimization.html
python scripts/backtest_visualizer.py --input reports/in_sample.json reports/out_sample.json --walk-forward --output reports/walk_forward.html
```

Le rapport HTML comprend la courbe d'équité et son drawdown, les rendements mensuels, les métriques roulantes, la distribution des trades et les indicateurs de risque. `--compare` ajoute les tableaux, courbes d'équité comparées et corrélations lorsque plusieurs fichiers sont fournis. `--optimize PARAM1 PARAM2` ajoute l'analyse de sensibilité et, si les deux paramètres varient, la heatmap. `--walk-forward` requiert exactement deux fichiers d'entrée dans l'ordre In-Sample puis Out-of-Sample. Les exports statiques sont optionnels : ajoutez `--png` ou `--pdf` et installez `matplotlib` (`pip install matplotlib`). Les graphiques interactifs utilisent ApexCharts chargé depuis un CDN.

Licence

## 🧪 Validation & Tests Automatisés

Le projet dispose d'une couverture de tests complète validant le client MT5, le dimensionnement des positions, les stratégies, les calculs d'indicateurs et le cycle d'exécution complet :

```bash
# Exécuter l'ensemble des tests
pytest

# Exécuter les tests avec affichage détaillé
pytest -v

# Exécuter un test spécifique
pytest tests/test_end_to_end_bot.py -v
pytest tests/test_strategies.py -v
pytest tests/test_broker_mt5.py -v
```

---

## 📊 Tableau des Classes d'Actifs & Spécifications

| Instrument | Classe | Taille de Contrat Standard | Précision (Digits) | Pip Size |
|---|---|---|---|---|
| **EURUSD, GBPUSD, etc.** | Forex Standard | 100 000 devises | 5 digits | 0.00010 |
| **USDJPY, GBPJPY, EURJPY** | Forex Yen | 100 000 devises | 3 digits | 0.010 |
| **XAUUSD (Or)** | Métal Précieux | 100 oz | 2 digits | 0.01 |
| **XAGUSD (Argent)** | Métal Précieux | 5 000 oz | 3 digits | 0.001 |
| **XTIUSD / WTIUSD (Pétrole WTI)** | Énergie / Pétrole | 1 000 barils | 2-3 digits | 0.01 |
| **XBRUSD (Pétrole Brent)** | Énergie / Pétrole | 1 000 barils | 2-3 digits | 0.01 |

---

## 🛡️ Règles de Sécurité & Résilience

1. **Anti-Slippage Re-Clamping** : Si le prix décale de quelques fractions de pips entre la clôture de bougie et l'envoi de l'ordre, le client MT5 recalcule dynamiquement les distances minimales de Stop-Loss et Take-Profit afin d'éviter tout rejet courtier.
2. **Anti-Pyramidage Strict** : Aucun ordre supplémentaire ne peut être ouvert sur un symbole ayant déjà une position en cours.
3. **Synchronisation Atomique** : L'état des positions est vérifié et réconcilié en permanence entre l'orchestrateur, le RiskManager et le terminal MT5.
4. **Kill-Switch Watchdog** : Toute anomalie critique (gel anormal de thread, altération de mémoire) déclenche l'arrêt d'urgence du bot pour préserver le capital.

---

## 📄 Licence

Propriété exclusive de **NexQuant** — Tous droits réservés. Usage privé et institutionnel.
