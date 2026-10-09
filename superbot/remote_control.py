"""
Contrôle à distance local du bot (pause / reprise), partagé avec le contrôleur Telegram.

Le contrôleur écrit `remote_control.json` dans LOG_DIR ; le bot le relit à chaque cycle.
Fichier absent ou illisible = pas de pause demandée (le bot ne doit jamais se bloquer sur ce fichier).
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("remote_control")


def control_path() -> Path:
    from superbot.config import LOG_DIR
    return Path(LOG_DIR) / "remote_control.json"


def read_remote_pause() -> bool:
    try:
        data = json.loads(control_path().read_text(encoding="utf-8"))
        return bool(data.get("paused", False))
    except (OSError, ValueError):
        return False


def write_remote_pause(paused: bool, source: str = "telegram") -> None:
    path = control_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"paused": bool(paused), "source": source,
                               "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    os.replace(tmp, path)  # écriture atomique : le bot ne lit jamais un fichier à moitié écrit


def apply_remote_pause(bot) -> None:
    """Applique la demande distante sans écraser les autres pauses (drift, circuit breaker…)."""
    requested = read_remote_pause()
    remote_active = getattr(bot, "_remote_paused", False)
    if requested and not remote_active:
        bot._remote_paused = True
        bot.is_paused = True
        log.info("⏸️ [Télécommande] Pause demandée : aucun nouvel ordre (SL/TP des positions conservés chez le broker).")
    elif not requested and remote_active:
        bot._remote_paused = False
        bot.is_paused = False
        log.info("▶️ [Télécommande] Reprise du trading demandée.")


def stop_flag_path() -> Path:
    from superbot.config import LOG_DIR
    return Path(LOG_DIR) / "user_stop.flag"


def user_stop_requested() -> bool:
    return stop_flag_path().exists()


def set_user_stop(stopped: bool) -> None:
    """Arrêt VOLONTAIRE (Telegram /arreter, stop_bot.ps1) : le relais de redémarrage ne doit pas relancer le bot."""
    p = stop_flag_path()
    if stopped:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    else:
        p.unlink(missing_ok=True)
