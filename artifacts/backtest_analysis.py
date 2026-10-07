import sys
import logging

# Set nexquant directory in python path
sys.path.insert(0, r"c:\Users\Pavillon\Desktop\nexquant_v2\nexquant")

# Suppress log clutter during backtest
logging.getLogger("strategy").setLevel(logging.WARNING)
logging.getLogger("root").setLevel(logging.WARNING)
logging.getLogger("webhook").setLevel(logging.WARNING)
logging.getLogger("paper_forex").setLevel(logging.WARNING)

from dotenv import load_dotenv
load_dotenv()

from superbot import config
from superbot.broker import create_broker
from superbot.strategy.strategy import TradingStrategy
from superbot.risk.risk_manager import RiskManager

# Helper to read configurations
config_dict = {k: getattr(config, k) for k in dir(config) if k.isupper()}

def run_backtest_for_broker(broker_type, symbol, limit=250):
    print("\n=======================================================")
    print(f"RUNNING HISTORICAL BACKTEST FOR {broker_type.upper()} ({symbol})")
    print("=======================================================")
    
    try:
        broker = create_broker(broker_type)
        print(f"[*] Fetching last {limit} candles from broker...")
        df = broker.fetch_candles(symbol, "1h", limit)
        if df is None or df.empty or len(df) < 60:
            print(f"[!] Error: Insufficient historical data retrieved (got {len(df) if df is not None else 0} bars).")
            return None
            
        print(f"[*] Retrieved {len(df)} candles.")
        
        # Initialize strategy & risk manager
        strategy = TradingStrategy(config_dict)
        risk_manager = RiskManager(config_dict)
        
        # Pre-compute all indicators once to speed up trailing stop ATR lookups
        print("[*] Pre-computing technical indicators...")
        df_indicators = strategy.indicators.calculate_all_indicators(df.copy())
        
        # Virtual account states
        initial_balance = 10000.0
        balance = initial_balance
        equity_curve = [initial_balance]
        
        # Position states: None or dict
        position = None 
        trades = []
        
        # Loop over history starting from 50 (to have enough bars for indicators)
        for i in range(50, len(df)):
            current_bar = df.iloc[i]
            current_close = current_bar['close']
            current_high = current_bar['high']
            current_low = current_bar['low']
            timestamp = df.index[i]
            
            # Slice dataframe up to current index (preventing future lookahead)
            df_slice = df.iloc[:i+1]
            
            # 1. If position is open, check if SL, TP or Trailing Stop is hit
            if position is not None:
                # Retrieve current ATR from pre-computed indicators
                atr_value = df_indicators.iloc[i].get('atr', 0)
                
                # Check for Trailing Stop
                if config_dict.get('TRAIL_ATR_MULT', 0) > 0 and atr_value > 0:
                    trail_mult = config_dict['TRAIL_ATR_MULT']
                    if position['side'] == 'LONG':
                        new_sl = current_close - (trail_mult * atr_value)
                        if new_sl > position['sl']:
                            position['sl'] = new_sl
                    else: # SHORT
                        new_sl = current_close + (trail_mult * atr_value)
                        if new_sl < position['sl']:
                            position['sl'] = new_sl
                            
                # Check if hit SL or TP on current bar
                hit_sl = False
                hit_tp = False
                
                if position['side'] == 'LONG':
                    if current_low <= position['sl']:
                        hit_sl = True
                        exit_price = position['sl']
                    elif current_high >= position['tp']:
                        hit_tp = True
                        exit_price = position['tp']
                else: # SHORT
                    if current_high >= position['sl']:
                        hit_sl = True
                        exit_price = position['sl']
                    elif current_low <= position['tp']:
                        hit_tp = True
                        exit_price = position['tp']
                        
                if hit_sl or hit_tp:
                    # Close position
                    if position['side'] == 'LONG':
                        pnl = (exit_price - position['entry_price']) * position['size']
                    else:
                        pnl = (position['entry_price'] - exit_price) * position['size']
                    
                    balance += pnl
                    trades.append({
                        'side': position['side'],
                        'entry_time': position['entry_time'],
                        'exit_time': timestamp,
                        'entry_price': position['entry_price'],
                        'exit_price': exit_price,
                        'size': position['size'],
                        'pnl': pnl,
                        'result': 'TP' if hit_tp else 'SL'
                    })
                    
                    position = None
                    equity_curve.append(balance)
                    continue
            
            # 2. Check for entry signals if no position is open
            if position is None:
                signal = strategy.analyze_market(df_slice)
                
                # Check if entry is triggered
                if signal['should_long'] or signal['should_short']:
                    side = 'LONG' if signal['should_long'] else 'SHORT'
                    sl = signal['sl_price']
                    tp = signal['tp_price']
                    
                    # Calculate position size
                    pos_size, size_details = risk_manager.calculate_position_size(
                        account_balance=balance,
                        entry_price=current_close,
                        stop_loss=sl,
                        symbol=symbol,
                        sentiment_factor=1.0
                    )
                    
                    if pos_size > 0:
                        position = {
                            'side': side,
                            'entry_time': timestamp,
                            'entry_price': current_close,
                            'size': pos_size,
                            'sl': sl,
                            'tp': tp,
                            'atr_value': df_indicators.iloc[i].get('atr', 0)
                        }
            
            equity_curve.append(balance)
            
        # Summarize results
        total_trades = len(trades)
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
        total_pnl = balance - initial_balance
        pnl_pct = (total_pnl / initial_balance) * 100
        
        # Profit factor
        gross_profit = sum(t['pnl'] for t in wins)
        gross_loss = abs(sum(t['pnl'] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        # Max drawdown
        peak = initial_balance
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
                
        print(f"[+] Backtest Completed for {broker_type.upper()}")
        print(f" -> Initial Balance: ${initial_balance:,.2f}")
        print(f" -> Final Balance: ${balance:,.2f}")
        print(f" -> Total Return: ${total_pnl:+,.2f} ({pnl_pct:+.2f}%)")
        print(f" -> Total Trades: {total_trades} (Wins: {len(wins)}, Losses: {len(losses)})")
        print(f" -> Win Rate: {win_rate:.2f}%")
        print(f" -> Profit Factor: {profit_factor:.2f}")
        print(f" -> Max Drawdown: {max_dd:.2f}%")
        
        return {
            'broker': broker_type,
            'symbol': symbol,
            'initial_balance': initial_balance,
            'final_balance': balance,
            'total_pnl': total_pnl,
            'pnl_pct': pnl_pct,
            'total_trades': total_trades,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'max_dd': max_dd,
            'trades_list': trades
        }
        
    except Exception as e:
        print(f"[!] Error backtesting broker {broker_type}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    results = {}
    
    # 1. Binance
    results['binance'] = run_backtest_for_broker('binance', 'BTC/USDT', limit=200)
    
    # 2. Alpaca
    results['alpaca'] = run_backtest_for_broker('alpaca', 'SPY', limit=200)
    
    # 3. Paper Forex
    results['paper_forex'] = run_backtest_for_broker('paper_forex', 'EUR/USD', limit=200)
    
    print("\n\n=======================================================")
    print("                 SUMMARY OF RESULTS                    ")
    print("=======================================================")
    for b, res in results.items():
        if res:
            print(f"{b.upper()} ({res['symbol']}): Return: {res['pnl_pct']:+.2f}%, Win Rate: {res['win_rate']:.1f}%, Profit Factor: {res['profit_factor']:.2f}, Max Drawdown: {res['max_dd']:.1f}%")
        else:
            print(f"{b.upper()}: Failed to complete.")
