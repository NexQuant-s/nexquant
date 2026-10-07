import argparse
import os
import time
import traceback

def main():
    """Point d'entrée principal du SuperBot avec support multi-broker CLI."""
    parser = argparse.ArgumentParser(description="SuperBot Trading Unifié MT5 (Forex & Commodities)")
    parser.add_argument("--broker", type=str, default=None, help="Type de broker (mt5)")
    parser.add_argument("--dashboard-port", type=int, default=None, help="Port pour le dashboard Web local (défaut: 5000)")
    parser.add_argument("--unpause", action="store_true", help="Forcer le déblocage / reprise du bot")
    parser.add_argument("--reset-state", action="store_true", help="Réinitialiser l'état persistant et le solde journalier")
    parser.add_argument("--auto-unpause", action="store_true", help="Relancer automatiquement le bot après mise en pause")
    parser.add_argument("--auto-unpause-delay", type=int, default=180, help="Délai en secondes avant relance automatique (défaut: 180s)")
    args = parser.parse_args()

    broker = args.broker or os.environ.get('BROKER_TYPE', 'mt5')
    os.environ["BROKER_TYPE"] = broker.lower()

    if args.dashboard_port:
        os.environ["DASHBOARD_PORT"] = str(args.dashboard_port)

    from superbot.orchestrator import SuperBot

    broker_name = os.environ.get("BROKER_TYPE", "mt5").upper()
    print(f"SuperBot Trading Unifié [{broker_name}]")
    print("=" * 50)

    # Créer et démarrer le bot
    bot = SuperBot()
    bot.auto_unpause = args.auto_unpause
    bot.auto_unpause_delay = args.auto_unpause_delay

    if args.reset_state:
        print("🔄 Réinitialisation de l'état persistant demandée (--reset-state)...")
        if hasattr(bot, 'state_manager'):
            bot.state_manager.clear_state()
        bot.is_paused = False
        bot.blocked_symbols.clear()
        bot.session_pnl_by_symbol.clear()

    if args.unpause:
        print("▶️ Forçage de la reprise / unpause du bot (--unpause)...")
        bot.is_paused = False
        if hasattr(bot, 'state_manager'):
            bot.state_manager.is_paused = False
            bot._save_cooldowns()

    try:
        bot.start()

        # Boucle principale d'attente
        print(f"SuperBot [{broker_name}] démarré avec succès")
        print("Appuyez sur Ctrl+C pour arrêter le bot")
        print("=" * 50)

        # Attendre jusqu'à interruption
        while bot.running:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nArrêt demandé par l'utilisateur")
    except Exception as e:
        print(f"\nErreur fatale : {e}")
        traceback.print_exc()
    finally:
        print("\nArrêt du SuperBot en cours...")
        if not getattr(bot, '_stopped', False):
            bot.stop()
        print("SuperBot arrêté")
        print("Au revoir !")

if __name__ == "__main__":
    main()