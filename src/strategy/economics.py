"""Fixed execution economics shared by live strategy and replay."""
import math
def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    spans = []
    for prev, bar in zip(candles[-period-1:-1], candles[-period:]):
        high, low, close = float(bar['h']), float(bar['l']), float(prev['c'])
        spans.append(max(high-low, abs(high-close), abs(low-close)))
    return sum(spans)/len(spans)


def bracket_distances(candles, entry, fee_entry=0.00015, fee_exit=0.00045, spread_fraction=0.0001):
    # 1.5 ATR stop with a 15bps noise/cost floor; 2:1 gross reward/risk.
    stop = max(atr(candles)*1.5, entry*0.0015)
    # Solve (target - costs)/(stop + costs) >= 1.5 algebraically.
    # This is a price geometry requirement, not a prediction of win probability.
    costs = entry * (fee_entry + fee_exit + 0.0002 + spread_fraction)
    target = max(stop*2, 1.5*stop + 2.5*costs)
    return target, stop


def viable(signal, bid, ask, fee_entry=0.00015, fee_exit=0.00045):
    entry = signal.entry_price
    if signal.side not in ('long', 'short') or not all(math.isfinite(v) for v in
            (entry, signal.sl_price, signal.tp_price, bid, ask, fee_entry, fee_exit)):
        return False, 'Non-finite price or invalid direction'
    if entry <= 0 or ask < bid or bid <= 0:
        return False, 'Invalid quote'
    if signal.side == 'long':
        valid = signal.sl_price < entry < signal.tp_price and entry < ask
    else:
        valid = signal.tp_price < entry < signal.sl_price and entry > bid
    if not valid:
        return False, 'Bracket geometry or post-only price invalid'
    spread = (ask-bid)/entry
    if spread > 0.0005:
        return False, 'Spread exceeds 5bps'
    costs = entry*(fee_entry+fee_exit+0.0002) + ask-bid
    reward, risk = abs(signal.tp_price-entry), abs(entry-signal.sl_price)
    if reward <= costs*2 or (reward-costs)/(risk+costs) < 1.2:
        return False, 'Insufficient reward after fees, spread and slippage'
    return True, 'Eligible for demo execution'
