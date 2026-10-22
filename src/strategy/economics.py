"""Fixed ex-ante execution economics shared by live strategy and replay."""
def atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    spans = []
    for prev, bar in zip(candles[-period-1:-1], candles[-period:]):
        high, low, close = float(bar['h']), float(bar['l']), float(prev['c'])
        spans.append(max(high-low, abs(high-close), abs(low-close)))
    return sum(spans)/len(spans)


def bracket_distances(candles, entry):
    # 1.5 ATR stop with a 15bps noise/cost floor; 2:1 gross reward/risk.
    stop = max(atr(candles)*1.5, entry*0.0015)
    return stop*2, stop


def viable(signal, bid, ask, fee_entry=0.00015, fee_exit=0.00045):
    entry = signal.entry_price
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
