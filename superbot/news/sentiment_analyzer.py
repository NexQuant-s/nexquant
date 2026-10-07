# -*- coding: utf-8 -*-
"""
NexQuant SentimentAnalyzer -- Phase 3
======================================
Analyse le sentiment de textes financiers via VADER (primaire, CPU)
avec support optionnel de FinBERT (GPU, haute precision).

VADER (Valence Aware Dictionary and sEntiment Reasoner) :
  - Aucun GPU requis, latence < 1ms par texte
  - Adapte aux textes courts (titres, tweets, nouvelles)
  - Lexique financier enrichi par mots-cles sectoriels (bullish/bearish/crash...)

FinBERT (optionnel, si GPU disponible) :
  - Modele BERT pre-entraine sur des textes financiers (Prosus AI)
  - Precision superieure pour les nuances semantiques financieres
  - Necessite : pip install transformers torch
  - Active automatiquement si detecte

Usage :
    analyzer = SentimentAnalyzer()
    score = analyzer.analyze_text("Bitcoin surges 15% as ETF approval expected")
    # -> 0.72 (tres positif)

    score = analyzer.analyze_text("Markets crash amid recession fears")
    # -> -0.65 (tres negatif)

    # Analyser un batch de NewsEvent
    from superbot.news.news_manager import NewsEvent
    news = [NewsEvent(title="BTC rally", ...), ...]
    score = analyzer.analyze_news_batch(news)
    # -> float entre -1 et +1
"""
import logging
import re
from typing import List, Dict, Any
from datetime import datetime

log = logging.getLogger("news.sentiment_analyzer")

# Mots-cles financiers supplementaires pour booster VADER
# (VADER connait "good"/"bad" mais pas "bullish"/"bearish" dans leur sens financier)
FINANCIAL_BOOSTER = {
    # Tres positifs
    "bullish": 2.5, "rally": 2.0, "surge": 2.0, "soar": 2.0, "breakout": 1.8,
    "ath": 2.5, "all-time high": 2.5, "record high": 2.2, "moon": 1.5,
    "approval": 1.8, "adoption": 1.5, "partnership": 1.3, "upgrade": 1.2,
    "etf approved": 3.0, "institutional": 1.3, "accumulation": 1.5,
    # Negatifs
    "bearish": -2.5, "crash": -2.8, "collapse": -2.8, "plunge": -2.2,
    "dump": -2.0, "selloff": -2.0, "liquidation": -2.5, "hack": -2.8,
    "scam": -2.8, "fraud": -2.8, "ban": -2.0, "regulation": -0.8,
    "recession": -2.0, "inflation": -1.2, "default": -2.5, "bankruptcy": -3.0,
    "delisting": -2.5, "exploit": -2.2, "vulnerability": -1.8, "rug pull": -3.0,
    # Neutres (reduire l'effet de certains mots mal interpretes par VADER)
    "bitcoin": 0.0, "ethereum": 0.0, "crypto": 0.0, "market": 0.0,
}


class SentimentAnalyzer:
    """
    Analyseur de sentiment financier en temps reel.

    Cascade de modeles :
      1. FinBERT (si disponible et GPU detecte) -- haute precision
      2. VADER + lexique financier enrichi -- rapide, sans GPU
    """

    def __init__(self, use_finbert: bool = False):
        """
        Args:
            use_finbert: Tenter de charger FinBERT (necessite transformers + torch)
        """
        self._vader = None
        self._finbert = None
        self._finbert_tokenizer = None
        self._use_finbert = False

        # Charger VADER (obligatoire)
        self._load_vader()

        # Charger FinBERT (optionnel)
        if use_finbert:
            self._load_finbert()

    # -- API publique ---------------------------------------------------------

    def analyze_text(self, text: str) -> float:
        """
        Analyse le sentiment d'un texte financier.

        Args:
            text: Texte a analyser (titre, paragraphe, tweet...)

        Returns:
            Score de sentiment entre -1.0 (tres negatif) et +1.0 (tres positif)
            0.0 = neutre
        """
        if not text or not text.strip():
            return 0.0

        text_clean = self._preprocess(text)

        # Priorite FinBERT si disponible
        if self._use_finbert and self._finbert is not None:
            try:
                return self._finbert_score(text_clean)
            except Exception as e:
                log.debug(f"[SentimentAnalyzer] FinBERT erreur ({e}), fallback VADER")

        # VADER + booster financier
        return self._vader_score(text_clean)

    def analyze_news_batch(self, news_items, max_items: int = 20) -> float:
        """
        Calcule un score de sentiment agrege sur un batch de nouvelles.

        Pondere chaque article par :
          - Son impact (HIGH=3x, MEDIUM=2x, LOW=1x)
          - Sa fraicheur (decroissance exponentielle sur 6h)

        Args:
            news_items: Liste de NewsEvent (ou dict avec 'title', 'impact', 'timestamp')
            max_items: Nombre maximum d'articles a analyser

        Returns:
            Score de sentiment aggregate entre -1 et +1
        """
        if not news_items:
            return 0.0

        weighted_scores = []
        now = datetime.now()

        for item in list(news_items)[:max_items]:
            # Extraire les champs (compatibilite NewsEvent et dict)
            if hasattr(item, 'title'):
                title = item.title
                description = getattr(item, 'description', '')
                impact = getattr(item, 'impact', 'MEDIUM').upper()
                timestamp = getattr(item, 'timestamp', now)
            elif isinstance(item, dict):
                title = item.get('title', '')
                description = item.get('description', '')
                impact = item.get('impact', 'MEDIUM').upper()
                timestamp = item.get('timestamp', now)
            else:
                continue

            # Analyser le texte (titre + extrait de description)
            full_text = f"{title}. {description[:150]}" if description else title
            score = self.analyze_text(full_text)

            # Poids selon l'impact
            impact_weight = {'HIGH': 3.0, 'MEDIUM': 2.0, 'LOW': 1.0}.get(impact, 1.5)

            # Poids selon la fraicheur (decroissance sur 6h)
            if isinstance(timestamp, datetime):
                age_hours = (now - timestamp).total_seconds() / 3600
                freshness_weight = max(0.1, 1.0 - age_hours / 6.0)
            else:
                freshness_weight = 0.5

            weighted_scores.append(score * impact_weight * freshness_weight)

        if not weighted_scores:
            return 0.0

        aggregate = sum(weighted_scores) / len(weighted_scores)
        return max(-1.0, min(1.0, aggregate))

    def analyze_rss_items(self, rss_items: List[Dict[str, Any]]) -> float:
        """
        Analyse le sentiment d'une liste d'articles RSS bruts.

        Args:
            rss_items: Liste de dicts {'title': str, 'summary': str, 'published': str}

        Returns:
            Score de sentiment aggregate entre -1 et +1
        """
        if not rss_items:
            return 0.0

        scores = []
        for item in rss_items[:30]:
            title = item.get('title', '')
            summary = item.get('summary', '')[:200]
            text = f"{title}. {summary}" if summary else title
            if text.strip():
                scores.append(self.analyze_text(text))

        return float(sum(scores) / len(scores)) if scores else 0.0

    def get_sentiment_label(self, score: float) -> str:
        """Convertit un score numerique en label lisible."""
        if score >= 0.6:   return "Tres Positif"
        if score >= 0.2:   return "Positif"
        if score >= -0.2:  return "Neutre"
        if score >= -0.6:  return "Negatif"
        return "Tres Negatif"

    # -- Moteurs internes -----------------------------------------------------

    def _load_vader(self):
        """Charge le modele VADER avec le lexique financier enrichi."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
            # Injecter le lexique financier supplementaire
            self._vader.lexicon.update(FINANCIAL_BOOSTER)
            log.info("[SentimentAnalyzer] VADER charge avec lexique financier enrichi.")
        except ImportError:
            log.warning(
                "[SentimentAnalyzer] vaderSentiment non installe. "
                "pip install vaderSentiment"
            )

    def _load_finbert(self):
        """Charge FinBERT (optionnel)."""
        try:
            from transformers import pipeline
            self._finbert = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                max_length=512,
                truncation=True,
            )
            self._use_finbert = True
            log.info("[SentimentAnalyzer] FinBERT charge avec succes (mode haute precision).")
        except ImportError:
            log.info("[SentimentAnalyzer] transformers non installe -- VADER uniquement.")
        except Exception as e:
            log.warning(f"[SentimentAnalyzer] FinBERT indisponible ({e}) -- VADER uniquement.")

    def _vader_score(self, text: str) -> float:
        """Calcule le score VADER + booster financier."""
        if self._vader is None:
            return 0.0
        scores = self._vader.polarity_scores(text)
        # Utiliser le compound score (normalise entre -1 et +1)
        return float(scores['compound'])

    def _finbert_score(self, text: str) -> float:
        """Calcule le score FinBERT."""
        if self._finbert is None:
            return 0.0
        result = self._finbert(text[:512])[0]
        label = result['label'].lower()
        score_raw = result['score']
        if label == 'positive':
            return score_raw
        elif label == 'negative':
            return -score_raw
        return 0.0  # neutral

    def _preprocess(self, text: str) -> str:
        """Nettoie le texte avant l'analyse."""
        # Supprimer les URLs
        text = re.sub(r'http\S+|www\S+', '', text)
        # Supprimer les balises HTML residuelles
        text = re.sub(r'<[^>]+>', '', text)
        # Remplacer les carateres de ponctuation excessifs
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
        # Normaliser les espaces
        text = ' '.join(text.split())
        return text.strip()
