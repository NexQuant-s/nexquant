"""
Base Broker module for SuperBot Trading Unifié.
Defines the Broker abstract base class and factory.
"""
import abc
import pandas as pd
from typing import Dict, Any, List, Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Broker(abc.ABC):
    """
    Interface abstraite unifiée pour tous les courtiers/échanges.
    Supporte le trading de crypto, forex, ETFs et autres actifs.
    """

    @abc.abstractmethod
    def get_balance(self) -> float:
        """Retourne le solde disponible en quote currency (USDT, USD, etc.)"""
        pass

    @abc.abstractmethod
    def get_account_summary(self) -> Dict[str, Any]:
        """Retourne un résumé complet du compte (solde, marge, PnL non réalisé, etc.)"""
        pass

    @abc.abstractmethod
    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """
        Télécharge les bougies historiques et retourne un DataFrame OHLCV.

        Args:
            symbol: Symbole de l'instrument (ex: 'BTC/USDT', 'EUR/USD', 'SPY')
            timeframe: Intervalle de temps (ex: '1h', '4h', '1d')
            limit: Nombre de bougies à récupérer

        Returns:
            DataFrame avec colonnes ['open', 'high', 'low', 'close', 'volume'] et index datetime
        """
        pass

    @abc.abstractmethod
    def get_position(self, symbol: str) -> Dict[str, Any]:
        """
        Retourne les détails de la position ouverte sur un instrument.

        Returns:
            Dict avec keys: 'side' (None/long/short), 'size', 'entry_price',
            'unrealized_pnl', 'liquidation_price' (si applicable), 'margin_used'
            Retourne dict vide si aucune position
        """
        pass

    @abc.abstractmethod
    def close_position(self, symbol: str, reason: str = "") -> bool:
        """
        Ferme la position ouverte au prix du marché.

        Args:
            symbol: Symbole de l'instrument
            reason: Raison de la fermeture (pour logging)

        Returns:
            True si la fermeture a réussi, False sinon
        """
        pass

    def close_all_positions(self, reason: str = "") -> bool:
        """
        Ferme toutes les positions ouvertes chez le courtier.

        Args:
            reason: Raison de la fermeture d'urgence (pour logging)

        Returns:
            True si toutes les fermetures ont réussi, False sinon
        """
        return False

    @abc.abstractmethod
    def place_order(self, symbol: str, side: str, amount: float,
                   sl: float, tp: float, reduce_only: bool = False,
                   comment: str = "") -> bool:
        """
        Place un ordre de marché avec stop loss et take profit.

        Args:
            symbol: Symbole de l'instrument
            side: 'buy' ou 'sell'
            amount: Quantité à trader (en unités de base)
            sl: Prix du stop loss
            tp: Prix du take profit
            reduce_only: Si True, l'ordre ne fait que réduire une position existante
            comment: Commentaire optionnel pour l'ordre

        Returns:
            True si l'ordre a été placé avec succès, False sinon
        """
        pass

    @abc.abstractmethod
    def modify_sl_tp(self, symbol: str, sl: float, tp: float) -> bool:
        """
        Modifie le stop loss et take profit d'une position existante.

        Args:
            symbol: Symbole de l'instrument
            sl: Nouveau prix du stop loss
            tp: Nouveau prix du take profit

        Returns:
            True si la modification a réussi, False sinon
        """
        pass

    @abc.abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Retourne le dernier prix coté (mid price) pour un instrument."""
        pass

    def get_spread(self, symbol: str) -> float:
        """Retourne le spread actuel (en pips/points) pour un instrument."""
        return 0.0


    @abc.abstractmethod
    def get_min_order_size(self, symbol: str) -> float:
        """Retourne la taille minimale d'ordre autorisée pour un instrument."""
        pass

    @abc.abstractmethod
    def get_step_size(self, symbol: str) -> float:
        """Retourne le pas de taille d'ordre (precision) pour un instrument."""
        pass

    @abc.abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """
        Normalise un symbole selon le format attendu par le courtier.
        Ex: convert 'EUR/USD' -> 'EURUSD' pour certains brokers forex
        """
        pass

    @abc.abstractmethod
    def get_default_instruments(self) -> List[str]:
        """Retourne la liste des instruments par défaut pour ce broker."""
        pass

    @abc.abstractmethod
    def get_default_news_assets(self) -> List[str]:
        """Retourne la liste des actifs de nouvelles par défaut pour ce broker."""
        pass

    @abc.abstractmethod
    def get_asset_type(self) -> str:
        """Retourne le type d'actif tradé par ce broker (ex: 'crypto', 'stock', 'forex')."""
        pass

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        Retourne les informations du symbole (contract_size, tick_size, tick_value).
        Par défaut retourne des valeurs génériques (crypto/action).
        """
        return {
            "contract_size": 1.0,
            "tick_size": 0.01,
            "tick_value": 0.01,
        }
    def get_trade_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Retourne l'historique des trades clôturés sur les N derniers jours.
        Par défaut retourne une liste vide si non supporté par le broker.
        """
        return []

    def get_closed_position(self, position_id: int) -> Optional[Dict[str, Any]]:
        """
        Retourne le trade clôturé correspondant au ticket de position (vérité broker),
        ou None si inconnu / non supporté.
        """
        return None

    def calculate_position_size(self, entry_price: float, sl_price: float,
                               risk_amount: float, leverage: int = 1,
                               symbol: str = "") -> float:
        """
        Calcule la taille de position basée sur le risque en monnaie de compte.

        Args:
            entry_price: Prix d'entrée prévu
            sl_price: Prix du stop loss
            risk_amount: Montant à risque en monnaie de compte (ex: $100)
            leverage: Effet de levier utilisé (défaut: 1 pour aucun levier)

        Returns:
            Taille de position en unités de base de l'actif
        """
        if entry_price == sl_price:
            return 0.0

        risk_per_unit = abs(entry_price - sl_price)
        if risk_per_unit == 0:
            return 0.0

        # Taille de base sans levier
        base_size = risk_amount / risk_per_unit

        # Ajuster pour le levier si applicable
        leveraged_size = base_size * leverage

        return leveraged_size

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Retourne la liste de toutes les positions ouvertes chez le broker.
        Par défaut retourne une liste vide si non implémenté.
        """
        return []

    def cancel_all_orders(self, symbol: str = "") -> bool:
        """
        Annule tous les ordres en attente / conditionnels.
        Par défaut retourne True.
        """
        return True


def create_broker(broker_type: str = None, **kwargs) -> Broker:
    """
    Factory function pour créer une instance de courtier MT5.

    Args:
        broker_type: Type de courtier (seul 'mt5' est supporté)
                    Si None, lit la variable d'environnement BROKER_TYPE
        **kwargs: Arguments supplémentaires passés au constructeur

    Returns:
        Instance de broker MT5 prête à l'emploi

    Raises:
        ValueError: Si le type de courtier n'est pas 'mt5'
    """
    if broker_type is None:
        broker_type = os.getenv("BROKER_TYPE", "mt5").lower()

    broker_type = broker_type.lower()

    if broker_type == "mt5":
        from superbot.broker.mt5_client import MT5Client
        return MT5Client(**kwargs)
    else:
        raise ValueError(
            f"Broker '{broker_type}' non supporté.\n"
            f"Seul le broker 'mt5' (MetaTrader 5) est disponible.\n"
            f"→ Définissez BROKER_TYPE=mt5 dans votre fichier .env"
        )

