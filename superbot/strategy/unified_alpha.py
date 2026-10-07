"""
NexQuant SuperBot — Stratégie Unifiée Intelligente (UnifiedAlphaStrategy)
========================================================================
Fusion synergique des 6 piliers d'élite en une stratégie maîtresse :
1. Analyse Visuelle de Courbe & Géométrie de Marché (Pente normalisée ATR, Courbure d²P/dt², Sommets/Creux HH/LL).
2. Alexander Elder : Marée de fond (Tide HTF) + Entrée sur repli (Wave pullback, interdiction d'acheter au sommet).
3. John J. Murphy : Directionnalité (+DI / -DI), force ADX et confirmation Donchian.
4. Bob Volman : Price Action sur 21 EMA (compression build-up et rejet par mèche).
5. Ernest Chan : Protection anti-extension Z-Score et retour à la moyenne en canal.
6. Momentum Multi-Horizons : Taux de variation (ROC 6/12/24) et consensus directionnel.

Symétrie directionnelle totale Achat / Vente sur l'Or (XAUUSD) et les devises majeures.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import pandas as pd
import numpy as np

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
if TYPE_CHECKING:
    from superbot.brain.regime_detector import RegimeResult

log = logging.getLogger("nexquant.unified_alpha")


class UnifiedAlphaStrategy(BaseStrategy):
    """
    Stratégie unifiée maîtresse combinant l'analyse géométrique de courbe et les 6 piliers.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="UNIFIED_ALPHA", config=config)
        self.sl_atr_mult = float(self.config.get("SL_ATR_MULT", 1.5))
        self.tp_atr_mult = float(self.config.get("TP_ATR_MULT", 3.2))
        self.score_min = float(self.config.get("SCORE_MIN", 6.0))

    def calculate_market_curve(self, df: pd.DataFrame, current_price: float, atr: float) -> Dict[str, Any]:
        """
        Analyse visuelle et calcul géométrique de la courbe du graphique :
        1. Pente de régression linéaire normalisée par l'ATR.
        2. Dérivée seconde (courbure / accélération d²P/dt²) pour détecter les sommets et creux arrondis.
        3. Structure Price Action des sommets et creux (Higher Highs / Lower Lows).
        """
        if len(df) < 15:
            return {
                "slope_norm": 0.0,
                "curvature": 0.0,
                "structure": "NEUTRAL",
                "curve_bias": 0.0,
                "is_concave_top": False,
                "is_convex_bottom": False,
            }

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        n = min(len(closes), 20)
        recent_closes = closes[-n:]
        x = np.arange(n)

        # 1. Pente de régression linéaire normalisée par l'ATR
        norm_atr = max(atr, 1e-5)
        poly1 = np.polyfit(x, recent_closes, 1)
        raw_slope = poly1[0]
        slope_norm = raw_slope / norm_atr  # Variation par barre en multiple d'ATR

        # 2. Dérivée seconde / Courbure polynomiale (degré 2)
        poly2 = np.polyfit(x, recent_closes, 2)
        curvature = 2.0 * poly2[0] / norm_atr  # Accélération / courbure normalisée

        # Détection visuelle d'épuisement de tendance :
        # - Sommet concave : pente positive mais courbure négative (le prix plafonne et s'arrondit vers le bas)
        is_concave_top = (slope_norm > 0.02 and curvature < -0.015) or (recent_closes[-1] < recent_closes[-2] and curvature < -0.02)
        # - Creux convexe : pente négative mais courbure positive (le prix rebondit et s'arrondit vers le haut)
        is_convex_bottom = (slope_norm < -0.02 and curvature > 0.015) or (recent_closes[-1] > recent_closes[-2] and curvature > 0.02)

        # 3. Structure Price Action (Sommets & Creux locaux sur 3 à 5 barres)
        recent_h = highs[-n:]
        recent_l = lows[-n:]
        h_peaks = []
        l_troughs = []
        for i in range(2, n - 2):
            if recent_h[i] > recent_h[i - 1] and recent_h[i] > recent_h[i - 2] and recent_h[i] > recent_h[i + 1] and recent_h[i] > recent_h[i + 2]:
                h_peaks.append(recent_h[i])
            if recent_l[i] < recent_l[i - 1] and recent_l[i] < recent_l[i - 2] and recent_l[i] < recent_l[i + 1] and recent_l[i] < recent_l[i + 2]:
                l_troughs.append(recent_l[i])

        structure = "NEUTRAL"
        if len(h_peaks) >= 2 and len(l_troughs) >= 2:
            if h_peaks[-1] > h_peaks[-2] and l_troughs[-1] > l_troughs[-2]:
                structure = "BULLISH_HH_HL"
            elif h_peaks[-1] < h_peaks[-2] and l_troughs[-1] < l_troughs[-2]:
                structure = "BEARISH_LH_LL"
        else:
            # En cas de tendance directionnelle claire sans replis locaux marqués
            half = n // 2
            first_h, second_h = np.max(recent_h[:half]), np.max(recent_h[half:])
            first_l, second_l = np.min(recent_l[:half]), np.min(recent_l[half:])
            if second_h > first_h and second_l > first_l and slope_norm > 0.1:
                structure = "BULLISH_HH_HL"
            elif second_h < first_h and second_l < first_l and slope_norm < -0.1:
                structure = "BEARISH_LH_LL"

        # Biais directionnel de courbe (-1.0 à +1.0)
        curve_bias = 0.0
        if slope_norm > 0.05 and not is_concave_top:
            curve_bias += 0.5
        elif slope_norm < -0.05 and not is_convex_bottom:
            curve_bias -= 0.5

        if structure == "BULLISH_HH_HL":
            curve_bias += 0.4
        elif structure == "BEARISH_LH_LL":
            curve_bias -= 0.4

        if is_concave_top:
            curve_bias = min(curve_bias, -0.2)  # Dégradation haussière immédiate
        if is_convex_bottom:
            curve_bias = max(curve_bias, +0.2)  # Amélioration haussière immédiate

        curve_bias = float(np.clip(curve_bias, -1.0, 1.0))

        return {
            "slope_norm": float(slope_norm),
            "curvature": float(curvature),
            "structure": structure,
            "curve_bias": curve_bias,
            "is_concave_top": is_concave_top,
            "is_convex_bottom": is_convex_bottom,
        }

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime: RegimeResult,
        asset_class: str,
        current_price: float,
        pip_size: float = 0.0001,
        adapted_params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> SignalResult:
        if df is None or len(df) < 30:
            return SignalResult(strategy_name=self.name, market_regime=getattr(regime, 'regime', 'ranging'))

        # Prise en compte des adaptations post-perte (diagnostics 10 min)
        score_min_eff = self.score_min
        sl_mult_eff = self.sl_atr_mult
        tp_mult_eff = self.tp_atr_mult
        if adapted_params:
            score_min_eff += float(adapted_params.get('score_min_boost', 0.0))
            sl_mult_eff += float(adapted_params.get('sl_atr_mult_boost', 0.0))
            tp_mult_eff += float(adapted_params.get('tp_atr_mult_boost', 0.0))

        last = df.iloc[-1]
        prev = df.iloc[-2]
        close = current_price if current_price > 0 else float(last['close'])

        atr = float(last.get('atr', 0.0))
        if atr <= 0:
            atr = abs(float(last['high']) - float(last['low']))
        atr = max(atr, 1e-5)

        # ── 1. ANALYSE VISUELLE DE COURBE ─────────────────────────────────────
        curve = self.calculate_market_curve(df, close, atr)
        slope_norm = curve["slope_norm"]
        curvature = curve["curvature"]
        curve_bias = curve["curve_bias"]
        is_concave_top = curve["is_concave_top"]
        is_convex_bottom = curve["is_convex_bottom"]

        # ── 2. EXTRACTION DES INDICATEURS CLÉS DES 6 PILIERS ──────────────────
        ema_21 = float(last.get('ema_21', last.get('ema_fast', close)))
        ema_55 = float(last.get('ema_55', last.get('ema_slow', close)))

        rsi = float(last.get('rsi', 50.0))
        adx = float(last.get('adx', 20.0))
        plus_di = float(last.get('plus_di', last.get('adx_pos', 20.0)))
        minus_di = float(last.get('minus_di', last.get('adx_neg', 20.0)))
        if plus_di == minus_di:
            if slope_norm > 0.05 or ema_21 > ema_55:
                plus_di, minus_di = 25.0, 15.0
            elif slope_norm < -0.05 or ema_21 < ema_55:
                plus_di, minus_di = 15.0, 25.0

        macd_hist = float(last.get('macd_hist', last.get('macd_histogram', 0.0)))
        prev_macd_hist = float(prev.get('macd_hist', prev.get('macd_histogram', 0.0)))

        bb_upper = float(last.get('bb_upper', close + 2 * atr))
        bb_middle = float(last.get('bb_middle', close))
        bb_std = (bb_upper - bb_middle) / 2.0 if (bb_upper - bb_middle) > 0 else atr
        z_score = (close - bb_middle) / bb_std if bb_std > 0 else 0.0

        # Donchian 20
        # (fenêtre de 20 barres se terminant sur la barre précédente ; calculée seulement si absente)
        donch_u = prev.get('donchian_upper_20')
        donch_l = prev.get('donchian_lower_20')
        donch_u = float(df['high'].iloc[-21:-1].max() if donch_u is None else donch_u)
        donch_l = float(df['low'].iloc[-21:-1].min() if donch_l is None else donch_l)

        # Momentum Multi-Périodes (ROC 6 et 12)
        roc_6 = (close - df['close'].iloc[-7]) / df['close'].iloc[-7] * 100 if len(df) >= 7 else 0.0
        roc_12 = (close - df['close'].iloc[-13]) / df['close'].iloc[-13] * 100 if len(df) >= 13 else 0.0

        # ── 3. ÉVALUATION SYNERGIQUE DES PILIERS (LONG & SHORT) ───────────────
        long_score = 0.0
        short_score = 0.0
        reasons_long: List[str] = []
        reasons_short: List[str] = []

        # PILIER 1 : Géométrie de Courbe & Pente Visuelle (Poids: 2.5 pts)
        if curve_bias > 0.3:
            pts = 2.5 if curve_bias >= 0.7 else 1.8
            long_score += pts
            reasons_long.append(f"Courbe haussière (pente=+{slope_norm:.2f} ATR/b, structure={curve['structure']})")
        elif curve_bias < -0.3:
            pts = 2.5 if curve_bias <= -0.7 else 1.8
            short_score += pts
            reasons_short.append(f"Courbe baissière (pente={slope_norm:.2f} ATR/b, structure={curve['structure']})")

        # Alerte Epuisement de Sommet / Creux
        if is_concave_top:
            short_score += 1.5
            long_score = max(0.0, long_score - 3.0)  # Pénaliser lourdement les achats sur sommet arrondi
            reasons_short.append(f"Sommet concave / épuisement haussier détecté (d²P/dt²={curvature:.3f})")
        if is_convex_bottom:
            long_score += 1.5
            short_score = max(0.0, short_score - 3.0)
            reasons_long.append(f"Creux convexe / essoufflement baissier détecté (d²P/dt²={curvature:.3f})")

        # PILIER 2 : Elder Tide & Wave Pullback (Poids: 2.0 pts)
        # Règle cardinale Elder : on achète UNIQUEMENT sur repli, JAMAIS en surachat !
        prev_ema_21 = float(prev.get('ema_21', ema_21))
        elder_impulse_bull = (ema_21 > prev_ema_21) and (macd_hist > prev_macd_hist or (macd_hist >= 0 and slope_norm > 0.1))
        elder_impulse_bear = (ema_21 < prev_ema_21) and (macd_hist < prev_macd_hist or (macd_hist <= 0 and slope_norm < -0.1))

        if elder_impulse_bull:
            if (close <= ema_21 + (0.5 * atr) or rsi < 55) and z_score < 2.5:
                long_score += 2.0
                reasons_long.append("Elder: Marée haussière avec repli (Wave dip) favorable")
            else:
                long_score += 1.2
                reasons_long.append("Elder: Marée haussière sans repli marqué")
        elif elder_impulse_bear:
            if (close >= ema_21 - (0.5 * atr) or rsi > 45) and z_score > -2.5:
                short_score += 2.0
                reasons_short.append("Elder: Marée baissière avec rebond (Wave bounce) favorable")
            else:
                short_score += 1.2
                reasons_short.append("Elder: Marée baissière sans rebond marqué")

        # PILIER 3 : Murphy Trend Direction & Force ADX (Poids: 2.0 pts)
        if adx >= 20.0:
            if plus_di > minus_di:
                long_score += 1.5
                if close > donch_u * 0.998:
                    long_score += 0.5
                reasons_long.append(f"Murphy: Tendance confirmée ADX={adx:.1f} (+DI>{minus_di:.1f})")
            elif minus_di > plus_di:
                short_score += 1.5
                if close < donch_l * 1.002:
                    short_score += 0.5
                reasons_short.append(f"Murphy: Tendance confirmée ADX={adx:.1f} (-DI>{plus_di:.1f})")

        # PILIER 4 : Bob Volman Price Action sur 21 EMA (Poids: 1.5 pts)
        recent_bars = df.iloc[-4:]
        bar_spreads = (recent_bars['high'] - recent_bars['low']).values
        avg_spread = np.mean(bar_spreads)
        is_buildup = avg_spread < (0.9 * atr)

        wick_rejection_long = (float(last['close']) > float(last['open'])) and ((float(last['low']) <= ema_21) and (close >= ema_21))
        wick_rejection_short = (float(last['close']) < float(last['open'])) and ((float(last['high']) >= ema_21) and (close <= ema_21))
        flow_bull = close > ema_21 and float(last['close']) >= float(last['open']) and slope_norm > 0.1
        flow_bear = close < ema_21 and float(last['close']) <= float(last['open']) and slope_norm < -0.1

        if wick_rejection_long or (is_buildup and close >= ema_21) or flow_bull:
            long_score += 1.5
            reasons_long.append("Volman: Rejet / Compression / Flux propre sur 21 EMA")
        elif wick_rejection_short or (is_buildup and close <= ema_21) or flow_bear:
            short_score += 1.5
            reasons_short.append("Volman: Rejet / Compression / Flux propre sous 21 EMA")

        # PILIER 5 : Ernest Chan Anti-Extension & Statistique (Poids: 1.0 pt)
        is_range = adx < 25.0 and getattr(regime, 'regime', '') in ['ranging', 'choppy_noise', 'unknown']
        if is_range:
            extreme_bull = (z_score > 2.2 or rsi > 75)
            extreme_bear = (z_score < -2.2 or rsi < 25)
        else:
            extreme_bull = (z_score > 3.2 or (rsi > 95 and z_score > 2.8))
            extreme_bear = (z_score < -3.2 or (rsi < 5 and z_score < -2.8))

        if extreme_bull:
            long_score = max(0.0, long_score - 2.5)  # Blocage achat au sommet extrême
            short_score += 1.0
            reasons_short.append(f"Chan: Sur-extension haussière extrême (Z={z_score:.2f}, RSI={rsi:.1f})")
        elif extreme_bear:
            short_score = max(0.0, short_score - 2.5)  # Blocage vente au creux extrême
            long_score += 1.0
            reasons_long.append(f"Chan: Sur-extension baissière extrême (Z={z_score:.2f}, RSI={rsi:.1f})")
        else:
            if z_score < 0:
                short_score += 0.5
            elif z_score > 0:
                long_score += 0.5

        # PILIER 6 : Momentum Multi-Horizons (Poids: 1.0 pt)
        if roc_6 > 0.1 and roc_12 > 0.2:
            long_score += 1.0
            reasons_long.append(f"Momentum: ROC6=+{roc_6:.2f}%, ROC12=+{roc_12:.2f}%")
        elif roc_6 < -0.1 and roc_12 < -0.2:
            short_score += 1.0
            reasons_short.append(f"Momentum: ROC6={roc_6:.2f}%, ROC12={roc_12:.2f}%")

        # ── 4. SÉLECTION DE LA DIRECTION ET RATIO R:R DYNAMIQUE ───────────────
        best_side = None
        final_score = 0.0
        reasons: List[str] = []

        if long_score >= score_min_eff and long_score > short_score:
            best_side = "LONG"
            final_score = round(min(long_score, 10.0), 1)
            reasons = reasons_long
        elif short_score >= score_min_eff and short_score > long_score:
            best_side = "SHORT"
            final_score = round(min(short_score, 10.0), 1)
            reasons = reasons_short

        if not best_side:
            # Aucun signal à haute conviction
            diag = (
                f"Analyse {symbol} : Score insuffisant (Long={long_score:.1f}, Short={short_score:.1f}, "
                f"requis={score_min_eff:.1f}) | Pente={slope_norm:+.2f} ATR/b, Courbure={curvature:+.3f}. "
                f"Marché en attente de confirmation claire."
            )
            return SignalResult(
                strategy_name=self.name,
                market_regime=getattr(regime, 'regime', 'ranging'),
                total_score=max(long_score, short_score),
                score_min=score_min_eff,
                reason="Consensus multi-facteurs insuffisant",
                decision_rationale=diag,
                should_long=False,
                should_short=False,
                confidence=0.0
            )

        # ── 5. CALCUL DES STOPS ET R:R CONFORME (>= 2.0) ───────────────────────
        sl_mult = sl_mult_eff
        tp_mult = tp_mult_eff

        # Calibrage spécifique selon l'actif
        norm_sym = symbol.upper().replace("/", "").replace(".", "")
        if "XAU" in norm_sym or "GOLD" in norm_sym:
            # Sensibilité Or : swing plus large pour éviter les mèches de liquidité
            sl_mult = max(sl_mult, 1.6)
            tp_mult = max(tp_mult, 3.5)
        elif "JPY" in norm_sym:
            sl_mult = max(sl_mult, 1.6)
            tp_mult = max(tp_mult, 3.2)
        elif "XTI" in norm_sym or "XBR" in norm_sym or "OIL" in norm_sym:
            sl_mult = max(sl_mult, 1.8)
            tp_mult = max(tp_mult, 3.6)

        if best_side == "LONG":
            sl_price = close - (sl_mult * atr)
            tp_price = close + (tp_mult * atr)
            risk = close - sl_price
            reward = tp_price - close
        else:
            sl_price = close + (sl_mult * atr)
            tp_price = close - (tp_mult * atr)
            risk = sl_price - close
            reward = close - tp_price

        rr_ratio = reward / risk if risk > 0 else 0.0

        rationale = (
            f"🎯 [UNIFIED_ALPHA] Signal validé sur {symbol} ({best_side}) | "
            f"Score de consensus : {final_score}/10 (requis: {score_min_eff:.1f}) | "
            f"Géométrie de courbe : pente={slope_norm:+.2f} ATR/b, courbure={curvature:+.3f}, structure={curve['structure']} | "
            f"Rapport R:R : {rr_ratio:.2f} (SL: {sl_price:.5f}, TP: {tp_price:.5f}) | "
            f"Motifs : {'; '.join(reasons)}"
        )

        return SignalResult(
            strategy_name=self.name,
            market_regime=getattr(regime, 'regime', 'trending'),
            should_long=(best_side == "LONG"),
            should_short=(best_side == "SHORT"),
            trigger_long=(best_side == "LONG"),
            trigger_short=(best_side == "SHORT"),
            total_score=final_score,
            confidence=min(final_score / 10.0, 1.0),
            score_min=score_min_eff,
            entry_price=close,
            sl_price=sl_price,
            tp_price=tp_price,
            rr_ratio=rr_ratio,
            reason="Consensus maîtrisé de la Stratégie Unifiée Intelligente",
            decision_rationale=rationale,
            extra_data={
                "curve_slope_norm": slope_norm,
                "curve_curvature": curvature,
                "curve_structure": curve["structure"],
                "curve_bias": curve_bias,
                "is_concave_top": is_concave_top,
                "is_convex_bottom": is_convex_bottom,
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )

