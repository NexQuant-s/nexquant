"""Source unique de vérité pour les paramètres de runtime (risk_pct, score_min).

Historiquement, `risk_pct` / `score_min` vivaient en quatre exemplaires :
`bot.adaptive_*`, `risk_manager.RISK_PCT`, `strategy.score_min` et
`strategy.risk_per_trade`, avec un pont manuel `_apply_adaptive_params()` qu'il
fallait penser à appeler après chaque écriture — source de bugs silencieux.

`RuntimeConfig` centralise les valeurs et les propage lui-même vers les composants
liés. Les propriétés `SuperBot.adaptive_risk_pct` / `adaptive_score_min` délèguent
ici : écrire sur l'une d'elles met à jour RiskManager et TradingStrategy aussitôt.
"""

from typing import Optional, Any


class RuntimeConfig:
    """Détient risk_pct/score_min et les pousse vers RiskManager et TradingStrategy."""

    def __init__(self, risk_pct: float, score_min: float):
        self._risk_pct: float = float(risk_pct)
        self._score_min: float = float(score_min)
        self._session_risk_multiplier: float = 1.0
        self._session_score_offset: int = 0
        self.risk_manager: Optional[Any] = None
        self.strategy: Optional[Any] = None

    # ─── Accesseurs ─────────────────────────────────────────────────────────

    @property
    def risk_pct(self) -> float:
        return self._risk_pct

    @property
    def score_min(self) -> float:
        return self._score_min

    # ─── API ────────────────────────────────────────────────────────────────

    def bind(self, risk_manager: Optional[Any] = None, strategy: Optional[Any] = None):
        """Lie les composants cibles puis applique les valeurs courantes."""
        if risk_manager is not None:
            self.risk_manager = risk_manager
        if strategy is not None:
            self.strategy = strategy
        self.apply()

    def set(self, risk_pct: Optional[float] = None, score_min: Optional[float] = None) -> bool:
        """Met à jour les valeurs fournies et propage si quelque chose a changé."""
        changed = False
        if risk_pct is not None:
            clamped_risk = max(0.3, min(float(risk_pct), 10.0))
            if clamped_risk != self._risk_pct:
                self._risk_pct = clamped_risk
                changed = True
        if score_min is not None and float(score_min) != self._score_min:
            self._score_min = float(score_min)
            changed = True
        if changed:
            self.apply()
        return changed

    def set_session_multipliers(self, risk_multiplier: float = 1.0, score_offset: int = 0):
        self._session_risk_multiplier = risk_multiplier
        self._session_score_offset = score_offset
        self.apply()

    def apply(self):
        """Pousse les valeurs courantes vers les composants liés."""
        if self.risk_manager is not None:
            self.risk_manager.RISK_PCT = self._risk_pct * self._session_risk_multiplier
        if self.strategy is not None:
            self.strategy.score_min = self._score_min + self._session_score_offset
            self.strategy.risk_per_trade = self._risk_pct * self._session_risk_multiplier
