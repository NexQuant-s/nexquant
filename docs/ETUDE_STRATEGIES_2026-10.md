# Étude des stratégies — 09/10/2026

Objectif : trouver des stratégies à espérance positive **après coûts**, adaptées au bot MT5 et à un compte de ~900 €.
Méthode : `research/strategy_lab/` (entrée à l'ouverture suivante, spread réel x1,5, stop >= 1 ATR, apprentissage/test).

## 1. Catalogue des stratégies connues

| Famille | Stratégies | Statut dans l'étude |
|---|---|---|
| **Suivi de tendance** | croisement de moyennes (EMA/SMA, golden cross), canal de Donchian / Turtles, Supertrend, Parabolic SAR, MACD, Ichimoku, ADX/DMI, momentum série temporelle (TSMOM), Keltner / ATR breakout, chandelier exit, Heikin-Ashi | testé (donch20/55, ema20_50, supertrend, keltner, tsmom20/60) |
| **Pullback de tendance** | Elder (triple écran), « Holy Grail » de Raschke, repli sur EMA20 en tendance | testé (`pullback_ema`) — **seul résultat robuste** |
| **Retour à la moyenne** | Bollinger, RSI(2) de Connors, z-score, stochastique, Williams %R, CCI, VWAP, grille (grid) | testé (bb_revert, rsi2, rsi_range, zscore) |
| **Cassure / volatilité** | squeeze Bollinger-Keltner, NR7 / inside bar, opening range, cassure Asie → Londres, volatilité de Larry Williams, gap fill | testé (squeeze, nr7, london, vol_brk) |
| **Price action / structure** | Volman (EMA21), supports/résistances, pivots, supply-demand, SMC/ICT, Fibonacci, Elliott, Wyckoff, figures chartistes, chandeliers | non testé : discrétionnaire, non quantifiable sans biais (Volman est dans le bot) |
| **Quantitatif / statistique** | momentum cross-sectionnel, facteurs (value/carry/qualité), carry FX, risk parity, ciblage de volatilité, saisonnalité (heure/jour/mois), régimes (HMM), filtre de Kalman, arbitrage statistique / paires (cointégration), ML (forêts, boosting, LSTM), apprentissage par renforcement | non testé : carry (historique de swaps indisponible), paires (infra de cointégration), ML (sur-apprentissage avec 3 ans de données) |
| **Événementiel / macro** | trading des news (NFP, FOMC), dérive post-résultats, macro fondamentale, positionnement COT, flux de fin de mois | non testé (données externes) |
| **Gestion du risque** (déterminante) | fraction fixe, Kelly, anti-martingale, ciblage de volatilité, trading de la courbe d'équité, diversification | appliqué (risque fixe par trade) |
| **Hors portée** | options (condor, straddle, delta-hedge), market making, HFT, arbitrage inter-marchés, funding/basis crypto | CFD MT5 : inapplicable |
| **À proscrire** | martingale, grille sans stop, moyennage à la baisse | — |

Stratégies déjà dans le bot : Elder Triple Screen, Chan (retour à la moyenne), Murphy (tendance), Volman, London Breakout,
Intermarket Momentum, Unified Alpha, TSMOM (simulation).

## 2. Résultats (39 combinaisons stratégie × timeframe, 29 symboles, 3 ans)

- **Médiane des PF robustes : 0,82** ; une seule combinaison au-dessus de 1,05 : le **pullback de tendance en D1**.
- Aucune stratégie classique ne bat les coûts en H1 (PF 0,77-0,87) : les coûts + le bruit dominent ; H4 : 0,85-0,96.
- Forex majeur et énergie : **négatifs** pour le pullback D1 (PF 0,76 / 0,63) ; indices 1,55, métaux 1,95, cryptos 1,33.
- Contrôle de robustesse du pullback D1 : **81 variantes de paramètres sur 81 rentables** (PF 1,08-1,33, médiane 1,17).

## 3. Faisabilité sur 900 €

Avec des stops D1 (2 ATR), le lot minimum rend **infaisable** : or (17 % du solde), argent (22 %), platine, cuivre (44 %),
pétrole (8 %), bitcoin (4,5 %). **Faisables** : 8 indices (0,14-1,1 %) et l'ETH (0,19 %).

## 4. Résultat retenu : pullback D1 sur indices + ETH (`swing_runner`)

PF 1,75 (apprentissage 1,97 / test 1,52), 133 trades en 3 ans (≈ 44/an), espérance +0,28 R/trade (IC95 % [0,07 ; 0,48]),
à 0,5 % de risque : ≈ +6 %/an, drawdown max 3 %. **Un jour sur sept** seulement comporte un résultat.

**Réserves** : (1) 77 % des signaux sont des achats et 2023-2026 était haussier pour les indices ; (2) le choix des classes
d'actifs a été fait après coup (biais de sélection) ; (3) 133 trades = petit échantillon. Attendre plutôt PF 1,2-1,4.
**Aucun objectif quotidien fixe n'est atteignable** : l'espérance réelle se mesure en % par mois, pas par jour.

## 5. Ce qui a été invalidé en chemin

Le PF de 1,6-1,9 de Murphy (H1, forex + or) venait de stops quasi nuls (voir CLAUDE.md) ; avec un stop réel de 2 ATR il tombe à ≈ 1,15.
