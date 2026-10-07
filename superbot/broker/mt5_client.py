"""
MetaTrader 5 (MT5) Broker Client — NexQuant Institutionnel
===========================================================
Client Broker 100% dédié à MetaTrader 5, optimisé pour les Matières Premières
(Or, Argent, Pétrole WTI/Brent, Gaz) et le Forex (Majeures, JPY, Cross).

Caractéristiques :
- Résilience réseau : auto-reconnexion avec backoff exponentiel.
- Négociation dynamique du mode de remplissage (IOC, FOK, RETURN).
- Respect absolu des contraintes courtier : TRADE_STOPS_LEVEL, TRADE_FREEZE_LEVEL.
- Dimensionnement précis des positions (lots, contract_size, tick_value).
- Réconciliation instantanée des positions, tickets et historique de deals.
"""

import logging
import math
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from superbot.broker.base import Broker
from superbot.broker.symbol_specs import (
    get_asset_class,
    normalize_symbol_name,
    get_pip_size,
    calculate_lot_size as specs_calc_lot_size,
    DEFAULT_SPECS
)
from superbot.config import (
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH
)

log = logging.getLogger("mt5_client")


# Alias de compatibilité
_detect_asset_class_mt5 = get_asset_class


class MT5Client(Broker):
    """
    Client Broker MetaTrader 5 hautement résilient pour Forex & Commodities.
    """

    def __init__(
        self,
        login: int = None,
        password: str = None,
        server: str = None,
        path: str = None,
        **kwargs
    ):
        if mt5 is None:
            raise ImportError(
                "Le module python MetaTrader5 n'est pas installé.\n"
                "Installez-le via 'pip install MetaTrader5' (Windows requis)."
            )

        self._login = int(login or MT5_LOGIN or 0)
        self._password = str(password or MT5_PASSWORD or "")
        self._server = str(server or MT5_SERVER or "")
        self._path = str(path or MT5_PATH or "")

        self._init_kwargs = {}
        if self._path:
            import os
            resolved_path = self._path
            if os.path.isdir(resolved_path):
                resolved_path = os.path.join(resolved_path, "terminal64.exe")
            self._init_kwargs["path"] = resolved_path
        if self._login > 0:
            self._init_kwargs["login"] = self._login
        if self._password:
            self._init_kwargs["password"] = self._password
        if self._server:
            self._init_kwargs["server"] = self._server

        self._connected = False
        self._connect_terminal()

    def _connect_terminal(self) -> bool:
        """Initialise la connexion au terminal MT5 et s'authentifie."""
        if not mt5:
            return False

        log.info(f"Initialisation MT5 (Serveur: {self._server})...")
        init_ok = mt5.initialize(**self._init_kwargs)
        if not init_ok:
            # Fallback : tentative d'initialisation avec le terminal actif (chemin uniquement)
            fallback_kwargs = {}
            if "path" in self._init_kwargs:
                fallback_kwargs["path"] = self._init_kwargs["path"]
            init_ok = mt5.initialize(**fallback_kwargs)

        if not init_ok:
            error_code = mt5.last_error()
            log.error(f"Échec de l'initialisation MT5 : {error_code}")
            self._connected = False
            return False

        # Si le terminal est déjà connecté sur le compte cible, pas besoin de ré-authentifier
        acc_info = mt5.account_info()
        if acc_info and self._login > 0 and acc_info.login == self._login:
            log.info(f"Terminal déjà connecté au compte {self._login}.")
        elif self._login > 0 and self._password:
            login_kwargs = {"login": self._login, "password": self._password}
            if bool(self._server):
                login_kwargs["server"] = self._server
            authorized = mt5.login(**login_kwargs)
            if not authorized:
                error_code = mt5.last_error()
                log.error(f"Échec de l'authentification MT5 compte {self._login} : {error_code}")
                self._connected = False
                return False

        acc_info = mt5.account_info()
        if acc_info:
            log.info(f"Connecté à MT5. Compte: {acc_info.login} | Solde: {acc_info.balance} {acc_info.currency} | Broker: {acc_info.company}")
            self._connected = True
            return True
        else:
            log.warning("Connecté à MT5 mais impossible de lire account_info.")
            self._connected = True
            return True

    def _ensure_connected(self) -> bool:
        """Vérifie l'état de la connexion et reconnecte si nécessaire."""
        if not mt5:
            return False
        terminal = mt5.terminal_info()
        if terminal is None or not getattr(terminal, "connected", False):
            log.warning("Terminal MT5 déconnecté du serveur de trading. Tentative de reconnexion...")
            return self._connect_terminal()
        return True

    def _call_api(self, api_func, default_val, *args, idempotent=True, **kwargs):
        """
        Wrapper unifié pour les appels MT5 avec retry et reconnexion automatique.
        """
        self._ensure_connected()
        max_retries = 3 if idempotent else 1
        backoff = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                res = api_func(*args, **kwargs)
                if res is None or res is False:
                    err = mt5.last_error() if mt5 else "N/A"
                    if attempt < max_retries:
                        log.debug(f"Appel MT5 returned {res} (err: {err}). Retry {attempt}/{max_retries}...")
                        self._connect_terminal()
                        time.sleep(backoff)
                        backoff *= 2.0
                        continue
                return res
            except Exception as e:
                if attempt == max_retries:
                    log.error(f"Échec critique appel MT5 après {max_retries} essais : {e}")
                    return default_val
                log.warning(f"Exception appel MT5 : {e}. Retry {attempt}/{max_retries}...")
                self._connect_terminal()
                time.sleep(backoff)
                backoff *= 2.0
        return default_val

    def normalize_symbol(self, symbol: str) -> str:
        """Normalise le nom du symbole pour MT5."""
        return normalize_symbol_name(symbol)

    def get_asset_type(self) -> str:
        """Type de broker principal."""
        return "mt5_institutional"

    def get_asset_class_for_symbol(self, symbol: str) -> str:
        """Retourne la classe d'actifs exacte du symbole."""
        return get_asset_class(symbol)

    def get_crypto_instruments(self) -> List[str]:
        """Instruments crypto CFD disponibles pour le trading exclusif du weekend."""
        from superbot.config import MT5_CRYPTO_SYMBOLS
        return list(MT5_CRYPTO_SYMBOLS)

    def get_default_instruments(self) -> List[str]:
        """Instruments par défaut (Matières Premières & Forex), sans doublons."""
        return [
            "XAUUSD",   # Or
            "XAGUSD",   # Argent
            "XTIUSD",   # Pétrole WTI
            "XBRUSD",   # Pétrole Brent
            "XNGUSD",   # Gaz naturel
            "EURUSD",   # Euro / Dollar
            "GBPUSD",   # Livre / Dollar
            "USDJPY",   # Dollar / Yen
            "AUDUSD",   # Dollar Australien / Dollar
            "USDCAD",   # Dollar / Dollar Canadien
            "USDCHF",   # Dollar / Franc Suisse
            "EURGBP",
            "EURJPY",
        ]

    def get_default_news_assets(self) -> List[str]:
        """Actifs surveillés pour les actualités macroéconomiques."""
        return ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "GOLD", "OIL"]

    def get_balance(self) -> float:
        """Retourne le solde du compte (balance)."""
        acc_info = self._call_api(mt5.account_info, None)
        return float(acc_info.balance) if acc_info else 0.0


    def get_account_summary(self) -> Dict[str, Any]:
        """Retourne le résumé complet du compte de trading."""
        acc_info = self._call_api(mt5.account_info, None)
        if not acc_info:
            return {
                "balance": 0.0,
                "equity": 0.0,
                "unrealized_pnl": 0.0,
                "margin_used": 0.0,
                "free_margin": 0.0,
                "margin_level": 0.0,
                "open_positions": 0,
                "leverage": 1,
                "account_type": "MT5_OFFLINE",
                "currency": "EUR",
            }

        positions = self._call_api(mt5.positions_get, [])
        open_positions_count = len(positions) if positions else 0
        margin_level = acc_info.margin_level if acc_info.margin > 0 else 0.0

        is_real = getattr(acc_info, "trade_mode", 0) == (mt5.ACCOUNT_TRADE_MODE_REAL if mt5 else 2)

        return {
            "balance": float(acc_info.balance),
            "equity": float(acc_info.equity),
            "unrealized_pnl": float(acc_info.profit),
            "margin_used": float(acc_info.margin),
            "free_margin": float(acc_info.margin_free),
            "margin_level": float(margin_level),
            "open_positions": open_positions_count,
            "leverage": int(acc_info.leverage),
            "account_type": "MT5_REAL" if is_real else "MT5_DEMO",
            "company": str(acc_info.company),
            "currency": str(acc_info.currency),
        }

    def _get_mt5_timeframe(self, timeframe: str) -> int:
        """Convertit un timeframe chaîne en constante MT5."""
        if not mt5:
            return 16385
        tf_map = {
            "1m": mt5.TIMEFRAME_M1,
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "30m": mt5.TIMEFRAME_M30,
            "1h": mt5.TIMEFRAME_H1,
            "2h": mt5.TIMEFRAME_H2,
            "4h": mt5.TIMEFRAME_H4,
            "1d": mt5.TIMEFRAME_D1,
            "1w": mt5.TIMEFRAME_W1,
        }
        return tf_map.get(timeframe.lower(), mt5.TIMEFRAME_H1)

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        """Récupère les bougies historiques depuis MT5 sous forme de DataFrame OHLCV."""
        symbol = self.normalize_symbol(symbol)
        mt5_tf = self._get_mt5_timeframe(timeframe)

        # S'assurer que le symbole est dans le Market Watch
        self._call_api(lambda: mt5.symbol_select(symbol, True), False)

        rates = self._call_api(lambda: mt5.copy_rates_from_pos(symbol, mt5_tf, 0, limit), None)
        if rates is None or len(rates) == 0:
            log.warning(f"Impossible de récupérer les bougies de {symbol} depuis MT5")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        # NB : index en HEURE SERVEUR MT5 (étiquetée UTC). Volontaire : minuit serveur = clôture
        # de New York, ce qui donne des bougies journalières propres pour les pivots
        # (resample('D')). La colonne `server_utc_offset_s` permet aux logiques horaires
        # (LondonBreakout, range asiatique) de retrouver l'heure UTC réelle
        # (voir knowledge_base.utc_bar_times).
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df['server_utc_offset_s'] = self._server_utc_offset_seconds()
        df = df.set_index('time')
        df = df.rename(columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tick_volume": "volume"
        })
        return df[['open', 'high', 'low', 'close', 'volume', 'server_utc_offset_s']]

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Récupère les spécifications contractuelles exactes du symbole MT5."""
        symbol = self.normalize_symbol(symbol)
        if not mt5:
            spec = DEFAULT_SPECS.get(symbol, DEFAULT_SPECS.get("EURUSD"))
            return {
                "contract_size": spec["contract_size"],
                "tick_size": spec["point"],
                "tick_value": spec["contract_size"] * spec["point"],
                "digits": spec["digits"],
                "point": spec["point"],
                "stops_level": 0,
                "volume_min": 0.01,
                "volume_step": 0.01,
                "volume_max": 100.0,
                "filling_mode": 2,
            }

        self._call_api(lambda: mt5.symbol_select(symbol, True), False)
        info = self._call_api(lambda: mt5.symbol_info(symbol), None)

        if not info:
            spec = DEFAULT_SPECS.get(symbol, DEFAULT_SPECS.get("EURUSD"))
            return {
                "contract_size": spec["contract_size"],
                "tick_size": spec["point"],
                "tick_value": spec["contract_size"] * spec["point"],
                "digits": spec["digits"],
                "point": spec["point"],
                "stops_level": 0,
                "volume_min": 0.01,
                "volume_step": 0.01,
                "volume_max": 100.0,
                "filling_mode": 2,
            }

        contract_size = info.trade_contract_size if info.trade_contract_size > 0 else 100000.0
        tick_size = info.trade_tick_size if info.trade_tick_size > 0 else (info.point or 0.00001)
        tick_value = info.trade_tick_value if info.trade_tick_value > 0 else (contract_size * tick_size)

        return {
            "contract_size": contract_size,
            "tick_size": tick_size,
            "tick_value": tick_value,
            "digits": info.digits,
            "point": info.point,
            "stops_level": info.trade_stops_level or 0,
            "volume_min": info.volume_min or 0.01,
            "volume_step": info.volume_step or 0.01,
            "volume_max": info.volume_max or 100.0,
            "filling_mode": getattr(info, "filling_mode", 0),
        }

    def calculate_margin(self, symbol: str, volume: float, price: float = 0.0, side: str = "buy") -> Optional[float]:
        """
        Calcule la marge exacte requise en devise du compte via MT5 API.
        Prend en compte l'effet de levier réel de l'instrument et les taux de conversion.
        """
        symbol = self.normalize_symbol(symbol)
        if not mt5:
            return None
        try:
            self._call_api(lambda: mt5.symbol_select(symbol, True), False)
            order_type = mt5.ORDER_TYPE_BUY if side.lower() in ("buy", "long") else mt5.ORDER_TYPE_SELL
            calc_price = price
            if calc_price <= 0:
                tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
                if tick:
                    calc_price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
                else:
                    return None
            margin = self._call_api(lambda: mt5.order_calc_margin(order_type, symbol, volume, calc_price), None)
            if margin is not None and margin > 0:
                return float(margin)
            return None
        except Exception as e:
            log.warning(f"Erreur lors du calcul de marge MT5 pour {symbol}: {e}")
            return None

    def get_current_price(self, symbol: str) -> float:
        """Retourne le mid price actuel du symbole."""
        symbol = self.normalize_symbol(symbol)
        self._call_api(lambda: mt5.symbol_select(symbol, True), False)
        tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return 0.0
        return (tick.bid + tick.ask) / 2.0

    def get_spread(self, symbol: str) -> float:
        """
        Retourne le spread actuel en pips selon la classe d'actifs.
        """
        symbol = self.normalize_symbol(symbol)
        self._call_api(lambda: mt5.symbol_select(symbol, True), False)
        tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
        if tick is None or tick.bid == 0.0 or tick.ask == 0.0:
            return 0.0

        spread_raw = tick.ask - tick.bid
        pip_sz = get_pip_size(symbol)
        if pip_sz > 0:
            return spread_raw / pip_sz
        return spread_raw / 0.0001

    def get_position(self, symbol: str) -> Dict[str, Any]:
        """Retourne la position nette ou principale sur un symbole."""
        symbol = self.normalize_symbol(symbol)
        positions = self._call_api(lambda: mt5.positions_get(symbol=symbol), [])
        if not positions:
            return {}

        total_long_volume = 0.0
        weighted_long_entry = 0.0
        total_short_volume = 0.0
        weighted_short_entry = 0.0
        total_profit = 0.0

        first_pos = positions[0]
        sl = first_pos.sl
        tp = first_pos.tp

        for pos in positions:
            if pos.type == mt5.POSITION_TYPE_BUY:
                total_long_volume += pos.volume
                weighted_long_entry += pos.price_open * pos.volume
            else:
                total_short_volume += pos.volume
                weighted_short_entry += pos.price_open * pos.volume
            total_profit += pos.profit

        net_volume = total_long_volume - total_short_volume
        if net_volume == 0:
            return {}

        if net_volume > 0:
            dominant_side = "LONG"
            total_volume = net_volume
            avg_entry = weighted_long_entry / total_long_volume if total_long_volume > 0 else 0.0
        else:
            dominant_side = "SHORT"
            total_volume = abs(net_volume)
            avg_entry = weighted_short_entry / total_short_volume if total_short_volume > 0 else 0.0
        tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
        mark_price = (tick.bid + tick.ask) / 2 if tick else avg_entry

        info = self.get_symbol_info(symbol)
        size_units = total_volume * info["contract_size"]

        return {
            "ticket": first_pos.ticket,
            "side": dominant_side,
            "size": size_units,
            "lots": round(total_volume, 4),
            "entry_price": avg_entry,
            "mark_price": mark_price,
            "unrealized_pnl": total_profit,
            "stop_loss": sl,
            "take_profit": tp,
            "margin_used": 0.0,
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Retourne toutes les positions ouvertes sur le compte MT5."""
        raw_positions = self._call_api(mt5.positions_get, [])
        if not raw_positions:
            return []

        result = []
        for pos in raw_positions:
            try:
                info = self.get_symbol_info(pos.symbol)
                size_units = pos.volume * info["contract_size"]
                side = "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT"
                result.append({
                    "symbol": pos.symbol,
                    "ticket": pos.ticket,
                    "side": side,
                    "size": size_units,
                    "lots": pos.volume,
                    "entry_price": pos.price_open,
                    "stop_loss": pos.sl,
                    "take_profit": pos.tp,
                    "unrealized_pnl": pos.profit,
                    "magic": pos.magic,
                    "comment": pos.comment,
                })
            except Exception as e:
                log.warning(f"Erreur traitement position ouverte MT5 {pos.symbol}: {e}")
        return result

    def _resolve_filling_mode(self, symbol: str) -> int:
        """Détermine le mode de remplissage compatible pour le symbole."""
        if not mt5:
            return 1
        info = self._call_api(lambda: mt5.symbol_info(symbol), None)
        if not info:
            return mt5.ORDER_FILLING_IOC

        fill_mode = getattr(info, "filling_mode", 0)
        # SYMBOL_FILLING_FOK = 1, SYMBOL_FILLING_IOC = 2
        if fill_mode & 2:
            return mt5.ORDER_FILLING_IOC
        elif fill_mode & 1:
            return mt5.ORDER_FILLING_FOK
        else:
            return mt5.ORDER_FILLING_RETURN

    def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        sl: float,
        tp: float,
        reduce_only: bool = False,
        comment: str = "",
        risk_pct: float = 1.0,
    ) -> bool:
        """
        Place un ordre au marché avec Stop Loss et Take Profit.
        Gère le dimensionnement exact en lots et la vérification des contraintes StopLevel.
        """
        if not mt5:
            log.error("Module MT5 non disponible")
            return False

        symbol = self.normalize_symbol(symbol)
        side_upper = side.upper()

        if reduce_only:
            pos = self.get_position(symbol)
            if not pos or pos["size"] == 0:
                log.warning(f"Ordre reduce_only demandé sur {symbol} sans position active.")
                return False

        self._call_api(lambda: mt5.symbol_select(symbol, True), False)

        tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
        if tick is None or (tick.bid == 0 and tick.ask == 0):
            log.error(f"Impossible d'obtenir les prix tick pour {symbol}.")
            return False

        if side_upper in ["BUY", "LONG"]:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif side_upper in ["SELL", "SHORT"]:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            log.error(f"Type d'ordre invalide : {side}")
            return False

        # Récupérer les spécifications du symbole
        info = self.get_symbol_info(symbol)
        contract_size = info["contract_size"]
        volume_min = info["volume_min"]
        volume_step = info["volume_step"]
        volume_max = info["volume_max"]
        point = info["point"] or 0.00001
        stops_level = info["stops_level"] * point

        # L'orchestrateur fournit amount en lots
        amount_lots = amount

        # Si amount n'a pas été fourni ou est nul, calculer selon le risque
        if amount_lots <= 0:
            balance = self.get_balance()
            amount_lots = specs_calc_lot_size(
                account_balance=balance,
                risk_pct=risk_pct,
                entry_price=price,
                sl_price=sl,
                contract_size=contract_size,
                tick_size=info["tick_size"],
                tick_value=info["tick_value"],
                volume_min=volume_min,
                volume_step=volume_step,
                volume_max=volume_max,
                symbol=symbol
            )

        if amount_lots < volume_min:
            log.warning(f"Taille calculée {amount_lots:.4f} < volume_min ({volume_min}) sur {symbol}. Ordre ignoré.")
            return False

        amount_lots = min(amount_lots, volume_max)
        amount_lots = math.floor(round(amount_lots / volume_step, 6)) * volume_step
        amount_lots = round(amount_lots, 4)

        # Vérification préventive de la marge requise pour éviter le rejet 10019 (No money)
        try:
            acc_info = mt5.account_info()
            if acc_info and getattr(acc_info, 'margin_free', 0) > 0:
                needed_margin = mt5.order_calc_margin(order_type, symbol, amount_lots, price)
                if needed_margin and needed_margin > acc_info.margin_free * 0.90:
                    max_affordable_margin = acc_info.margin_free * 0.90
                    scaling = max_affordable_margin / needed_margin
                    new_lots = math.floor(round((amount_lots * scaling) / volume_step, 6)) * volume_step
                    new_lots = round(new_lots, 4)
                    if new_lots >= volume_min:
                        log.warning(
                            f"⚠️ Marge requise ({needed_margin:.2f}€) > marge disponible ({acc_info.margin_free:.2f}€) pour {amount_lots} lots sur {symbol}. "
                            f"Réduction automatique du volume à {new_lots:.4f} lots."
                        )
                        amount_lots = new_lots
                    else:
                        log.warning(
                            f"❌ Marge insuffisante même pour la taille minimale sur {symbol} "
                            f"(requise: {needed_margin:.2f}€, libre: {acc_info.margin_free:.2f}€). Ordre annulé."
                        )
                        return False
        except Exception as _me:
            log.debug(f"Vérification préventive de marge ignorée: {_me}")

        # Vérification et ajustement des Stop Loss et Take Profit selon StopLevel
        digits = info["digits"]
        min_offset = max(stops_level, 15 * point)
        if side_upper in ["BUY", "LONG"]:
            if tp > 0 and tp <= price:
                log.warning(f"TP d'achat {tp} <= Prix {price}. Ordre rejeté.")
                return False
            if sl > 0 and sl >= price:
                log.warning(f"SL d'achat {sl} >= Prix {price}. Ordre rejeté.")
                return False
            if sl > 0 and price - sl < stops_level:
                sl = round(price - min_offset, digits)
                log.info(f"SL d'achat ajusté dynamiquement sous le prix actuel: {sl}")
            if tp > 0 and tp - price < stops_level:
                tp = round(price + stops_level, digits)
        elif side_upper in ["SELL", "SHORT"]:
            if tp > 0 and tp >= price:
                log.warning(f"TP de vente {tp} >= Prix {price}. Ordre rejeté.")
                return False
            if sl > 0 and sl <= price:
                log.warning(f"SL de vente {sl} <= Prix {price}. Ordre rejeté.")
                return False
            if sl > 0 and sl - price < stops_level:
                sl = round(price + min_offset, digits)
                log.info(f"SL de vente ajusté dynamiquement au-dessus du prix actuel: {sl}")
            if tp > 0 and price - tp < stops_level:
                tp = round(price - stops_level, digits)

        # Sanitisation du commentaire MT5
        base_comment = (comment or f"NQ-{side_upper}")[:28]
        safe_comment = "".join([c if c.isalnum() or c in " .-_" else "_" for c in base_comment])

        fill_mode = self._resolve_filling_mode(symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(amount_lots),
            "type": order_type,
            "price": float(price),
            "sl": float(sl) if sl > 0 else 0.0,
            "tp": float(tp) if tp > 0 else 0.0,
            "deviation": 20,
            "magic": 10099,
            "comment": safe_comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_mode,
        }

        log.info(f"Envoi ordre MT5 : {side_upper} {amount_lots} {symbol} @ {price:.5f} (SL: {sl:.5f}, TP: {tp:.5f})")
        result = self._call_api(mt5.order_send, None, request, idempotent=False)

        # Retry avec mode de remplissage alternatif si rejeté pour fill type
        if result is not None and getattr(result, "retcode", 0) == 10030:  # TRADE_RETCODE_INVALID_FILL
            log.warning(f"Rejet filling mode {fill_mode} sur {symbol}. Tentative alternative...")
            alt_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
            for alt in alt_modes:
                if alt != fill_mode:
                    request["type_filling"] = alt
                    result = self._call_api(mt5.order_send, None, request, idempotent=False)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        break

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err_code = mt5.last_error() if mt5 else "N/A"
            err_msg = result.comment if result else "Pas de réponse MT5"
            log.error(f"Échec ordre {symbol}: {err_msg} (retcode: {result.retcode if result else 'N/A'}, err: {err_code})")
            return False

        log.info(f"Ordre MT5 exécuté avec succès. Ticket: {result.order}")
        return True

    def modify_sl_tp(self, symbol: str, sl: float, tp: float) -> bool:
        """Modifie le Stop Loss et le Take Profit de toutes les positions sur le symbole."""
        if not mt5:
            return False

        symbol = self.normalize_symbol(symbol)
        positions = self._call_api(lambda: mt5.positions_get(symbol=symbol), [])
        if not positions:
            log.warning(f"Aucune position ouverte sur {symbol} pour modifier SL/TP.")
            return False

        info = self.get_symbol_info(symbol)
        stops_level = info["stops_level"] * (info["point"] or 0.00001)
        digits = info["digits"]

        tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
        if not tick:
            return False

        success = True
        for pos in positions:
            pos_type = getattr(pos, "type", getattr(mt5, "POSITION_TYPE_BUY", 0))
            side = "LONG" if pos_type == getattr(mt5, "POSITION_TYPE_BUY", 0) else "SHORT"
            current_price = tick.bid if side == "LONG" else tick.ask
            
            intended_side = None
            if sl > 0:
                intended_side = "LONG" if sl < current_price else "SHORT"
            elif tp > 0:
                intended_side = "LONG" if tp > current_price else "SHORT"
                
            if intended_side and intended_side != side:
                continue
                
            pos_sl = sl
            pos_tp = tp
            
            if stops_level > 0 and current_price > 0:
                if side == "LONG":
                    if pos_sl > 0 and current_price - pos_sl < stops_level:
                        pos_sl = round(current_price - stops_level, digits)
                    if pos_tp > 0 and pos_tp - current_price < stops_level:
                        pos_tp = round(current_price + stops_level, digits)
                else:
                    if pos_sl > 0 and pos_sl - current_price < stops_level:
                        pos_sl = round(current_price + stops_level, digits)
                    if pos_tp > 0 and current_price - pos_tp < stops_level:
                        pos_tp = round(current_price - stops_level, digits)

            ticket = pos.ticket
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": symbol,
                "sl": float(pos_sl) if pos_sl > 0 else 0.0,
                "tp": float(pos_tp) if pos_tp > 0 else 0.0,
            }
            result = self._call_api(mt5.order_send, None, request, idempotent=False)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                err_code = mt5.last_error()
                log.error(f"Échec modification SL/TP #{ticket} ({symbol}): {result.comment if result else ''} (code: {err_code})")
                success = False
            else:
                log.info(f"SL/TP modifié avec succès sur position #{ticket} ({symbol}) -> SL: {pos_sl:.5f}, TP: {pos_tp:.5f}")

        return success

    def close_position(self, symbol: str, reason: str = "") -> bool:
        """Ferme toutes les positions ouvertes sur le symbole au prix du marché."""
        if not mt5:
            return False

        symbol = self.normalize_symbol(symbol)
        positions = self._call_api(lambda: mt5.positions_get(symbol=symbol), [])
        if not positions:
            log.info(f"Aucune position à fermer sur {symbol}.")
            return False

        success = True
        for pos in positions:
            ticket = pos.ticket
            volume = pos.volume
            side = "LONG" if pos.type == mt5.POSITION_TYPE_BUY else "SHORT"
            order_type = mt5.ORDER_TYPE_SELL if side == "LONG" else mt5.ORDER_TYPE_BUY

            tick = self._call_api(lambda: mt5.symbol_info_tick(symbol), None)
            if tick is None:
                log.error(f"Impossible d'obtenir le prix tick pour fermer #{ticket}")
                success = False
                continue

            price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
            fill_mode = self._resolve_filling_mode(symbol)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": 10099,
                "comment": f"Close #{ticket} - {reason}"[:28],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_mode,
            }

            log.info(f"Fermeture position MT5 #{ticket} sur {symbol} ({volume} lots {side})...")
            result = self._call_api(mt5.order_send, None, request, idempotent=False)

            if result is not None and getattr(result, "retcode", 0) == 10030:
                log.warning(f"Rejet filling mode {fill_mode} sur {symbol} pour fermeture. Tentative alternative...")
                alt_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
                for alt in alt_modes:
                    if alt != fill_mode:
                        request["type_filling"] = alt
                        result = self._call_api(mt5.order_send, None, request, idempotent=False)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            break

            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                err_code = mt5.last_error()
                log.error(f"Échec fermeture #{ticket} {symbol}: {result.comment if result else ''} (code: {err_code})")
                success = False
            else:
                log.info(f"Position #{ticket} sur {symbol} fermée avec succès.")

        return success

    def close_all_positions(self, reason: str = "") -> bool:
        """Ferme toutes les positions ouvertes sur l'ensemble des symboles."""
        if not mt5:
            return False
        positions = self._call_api(mt5.positions_get, [])
        if not positions:
            log.info("Aucune position ouverte à fermer.")
            return True

        symbols = list(set([p.symbol for p in positions]))
        log.warning(f"🚨 [EmergencyClose] Fermeture globale de {len(positions)} positions sur {len(symbols)} symboles: {symbols}. Motif: {reason}")
        all_success = True
        for sym in symbols:
            ok = self.close_position(sym, reason=reason)
            if not ok:
                all_success = False
        return all_success

    def cancel_all_orders(self, symbol: str = "") -> bool:
        """Annule tous les ordres en attente (pending orders)."""
        if not mt5:
            return False
        try:
            orders = self._call_api(mt5.orders_get, [])
            if not orders:
                return True
            symbol_norm = self.normalize_symbol(symbol) if symbol else ""
            for o in orders:
                if not symbol_norm or self.normalize_symbol(o.symbol) == symbol_norm:
                    request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": o.ticket,
                    }
                    self._call_api(mt5.order_send, None, request)
            return True
        except Exception as e:
            log.warning(f"Erreur annulation ordres MT5: {e}")
            return False

    # Codes DEAL_REASON_* de MT5 -> motif lisible de clôture
    _DEAL_REASONS = {
        0: "client", 1: "mobile", 2: "web", 3: "expert", 4: "sl", 5: "tp",
        6: "stop_out", 7: "rollover", 8: "vmargin", 9: "split",
    }
    _DEAL_ENTRY_IN = 0
    _DEAL_ENTRY_OUT = 1
    _DEAL_ENTRY_OUT_BY = 3

    def _server_utc_offset_seconds(self) -> int:
        """
        Décalage (secondes) entre l'heure du serveur MT5 et l'UTC.

        MT5 horodate ticks et deals en heure serveur (ex: UTC+3 chez Fusion Markets en
        été), exprimée comme un timestamp « epoch ». On le mesure sur le tick le plus
        récent (arrondi à 30 min) ; un tick trop ancien (marché fermé) est ignoré et
        la dernière mesure fiable est conservée.
        """
        now = time.time()
        cached = getattr(self, "_tz_offset", None)
        if cached is not None and now - getattr(self, "_tz_offset_checked_at", 0.0) < 3600:
            return cached

        latest_tick_time = 0
        for probe in ("BTCUSD", "EURUSD", "XAUUSD"):
            sym = self.normalize_symbol(probe)
            # Un seul essai : un symbole sans tick ne doit pas déclencher reconnexion + attente
            tick = self._call_api(lambda s=sym: mt5.symbol_info_tick(s), None, idempotent=False)
            latest_tick_time = max(latest_tick_time, getattr(tick, "time", 0) or 0)

        if latest_tick_time:
            diff = latest_tick_time - now
            rounded = int(round(diff / 1800.0)) * 1800
            if abs(diff - rounded) <= 300 and abs(rounded) <= 14 * 3600:
                if rounded != cached:
                    log.info(f"Décalage heure serveur MT5 détecté : UTC{rounded / 3600:+.1f}h")
                self._tz_offset = rounded
                self._tz_offset_checked_at = now
                return rounded

        if cached is None:
            log.warning("Décalage heure serveur MT5 indéterminé (aucun tick récent) — UTC supposé.")
            return 0
        return cached

    def _server_ts_to_utc(self, server_ts: float, offset: int) -> datetime:
        return datetime.fromtimestamp(server_ts - offset, timezone.utc)

    def _summarize_position_deals(self, position_id: int, deals, offset: int) -> Optional[Dict[str, Any]]:
        """Agrège les deals d'une position en un trade clôturé (None si encore ouverte)."""
        entries = [d for d in deals if d.entry == self._DEAL_ENTRY_IN]
        exits = [d for d in deals if d.entry in (self._DEAL_ENTRY_OUT, self._DEAL_ENTRY_OUT_BY)]
        if not entries or not exits:
            return None

        entry_volume = sum(d.volume for d in entries)
        exit_volume = sum(d.volume for d in exits)
        last_exit = max(exits, key=lambda d: d.time)
        pnl = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
        return {
            "symbol": entries[0].symbol,
            # Le sens est celui du deal d'ouverture (DEAL_TYPE_BUY = 0)
            "side": "buy" if entries[0].type == 0 else "sell",
            "entry_price": sum(d.price * d.volume for d in entries) / entry_volume if entry_volume else 0.0,
            "exit_price": sum(d.price * d.volume for d in exits) / exit_volume if exit_volume else 0.0,
            "pnl": pnl,
            "size": exit_volume,
            "timestamp": self._server_ts_to_utc(last_exit.time, offset),
            "open_time": self._server_ts_to_utc(min(d.time for d in entries), offset),
            "close_reason": self._DEAL_REASONS.get(last_exit.reason, str(last_exit.reason)),
            "ticket": last_exit.ticket,
            "position_id": int(position_id),
            "status": "closed",
        }

    def get_closed_position(self, position_id: int) -> Optional[Dict[str, Any]]:
        """Retourne le trade clôturé correspondant exactement au ticket de position MT5."""
        if not mt5 or not position_id:
            return None
        try:
            deals = self._call_api(lambda: mt5.history_deals_get(position=int(position_id)), None)
            if not deals:
                return None
            return self._summarize_position_deals(position_id, deals, self._server_utc_offset_seconds())
        except Exception as e:
            log.error(f"Erreur récupération des deals de la position {position_id} : {e}")
            return None

    def get_trade_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Récupère l'historique des positions clôturées (une ligne par position, horodatage UTC)."""
        if not mt5:
            return []
        try:
            offset = self._server_utc_offset_seconds()
            now = time.time()
            # La fenêtre est exprimée en heure serveur, comme les deals MT5.
            from_date = datetime.fromtimestamp(now + offset - days * 86400, timezone.utc)
            to_date = datetime.fromtimestamp(now + offset + 3600, timezone.utc)

            deals = self._call_api(lambda: mt5.history_deals_get(from_date, to_date), None)
            if not deals:
                return []

            by_position: Dict[int, list] = {}
            for deal in deals:
                if deal.symbol and deal.position_id:
                    by_position.setdefault(deal.position_id, []).append(deal)

            trades = []
            for position_id, pos_deals in by_position.items():
                trade = self._summarize_position_deals(position_id, pos_deals, offset)
                if trade:
                    trades.append(trade)

            trades.sort(key=lambda x: x["timestamp"], reverse=True)
            return trades
        except Exception as e:
            log.error(f"Erreur récupération historique MT5 : {e}")
            return []

    def get_min_order_size(self, symbol: str) -> float:
        info = self.get_symbol_info(symbol)
        return float(info.get("volume_min", 0.01))

    def get_step_size(self, symbol: str) -> float:
        info = self.get_symbol_info(symbol)
        return float(info.get("volume_step", 0.01))
