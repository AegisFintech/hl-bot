# Closed-bar strategy engine — 2026-10-29

Operator decision (2026-10-29): replace the 1m support/resistance scalper with the best
out-of-sample, fee-inclusive strategy; allow up to ~1% equity risk per trade across several
coins; replace the permanent 5% halt with a drawdown breaker that auto-resets after a
cooldown. Execution stays on **testnet**. Nothing here is a profit guarantee.

## Why the scalper was retired

- Last 2,000 exchange fills (docs/OVERHAUL.md): gross −5.61 USDC, fees 9.19 USDC, net −14.80 USDC.
  Fees exceeded the price loss: a 15 bps stop on 1m bars pays ~6–9 bps of round-trip costs.
- Preserved replays (docs/replay-*.json): 112 of 116 signals rejected by cost geometry, 36 of 48
  later entries expired unfilled, profit factor 0.50 (development) and 0.00 (later segment).
- Operationally it rarely traded: post-only entries expired, any order hiccup flattened the
  account, and the permanent 5% halt never released.

## Design

| Piece | Module | Behaviour |
| --- | --- | --- |
| Indicators | `src/strategy/indicators.py` | Causal EMA, Wilder ATR/RSI, Donchian channels, rate of change |
| Strategies | `src/strategy/library.py` | `donchian`, `ema_trend`, `tsmom`, `rsi_reversion`; pure `decide()` on closed bars |
| Live engine | `src/strategy/engine.py` | Fetches/validates bars at each close, persists stop/extreme/bars-held, adopts unknown positions |
| Execution | `src/executor.py` | IOC entries, one reduce-only stop per position, place-then-cancel stop moves, close-then-cancel exits |
| Sizing | `src/risk/manager.py::position_size` | Stop-out loses `RISK_PER_TRADE_PCT` of equity; per-position and gross leverage caps; shared with the backtester |
| Backtester | `src/validation/backtest.py` | Replays the same `decide()` bar by bar with fees, slippage, funding and the breaker |
| Research | `scripts/fetch_history.py`, `scripts/strategy_research.py` | Public history download; pre-declared candidates; in-sample selection; out-of-sample report |
| Account review | `scripts/account_history.py` | Read-only fills/orders/funding summary for the testnet wallet |

Decisions use closed bars only. Entries/exits execute immediately after the close (the
backtester uses the next bar's open). A position is always protected by an exchange stop; if a
stop cannot be placed the position is closed and entries pause. Stops only tighten.

### Candidates (fixed before results; no fitting)

Donchian 20/10 and 55/20, with and without a 200-bar EMA filter, plus long-only 20/10; EMA
20/100 and 50/200 (and long-only 20/100) with a 3-ATR chandelier stop; time-series momentum
over 72/168/336 bars (and long-only 168) with a 4-ATR trailing stop; RSI(2) reversion in the
200-EMA trend direction (10/90 and 5/95). Each is evaluated on 1h and 4h bars.

### Selection rule

1. Rank candidates by **in-sample** daily Sharpe (first 70% of the timeline) with ≥30 trades and
   in-sample max drawdown ≤25%, at 0.5% risk and the 5%/12h breaker.
2. For the winner, take the highest risk level in {0.25, 0.5, 0.75, 1.0}% with at most one
   breaker trip per 30 in-sample days.
3. Report every candidate's out-of-sample result, the in/out-of-sample rank correlation and the
   deflated Sharpe probability for the number of trials. Settings are printed, never applied
   automatically.

Costs: 4.5 bps taker fee per side, 3 bps entry/exit slippage, 5 bps extra on stop fills (gap
opens fill at the open), actual hourly funding when downloaded (otherwise a stress debit on
both sides).

## Running the research

```bash
python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 1h --since 2021-01 --funding
python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 4h --since 2021-01
python3 scripts/strategy_research.py --source binance --coins BTC,ETH,SOL --intervals 1h,4h
python3 scripts/account_history.py 0xYourMasterWallet --network testnet
```

Hyperliquid's API serves only the latest 5,000 candles per interval (~7 months of 1h), so the
Binance USD-M archives provide multi-year history; their prices track Hyperliquid perps closely
on hourly bars but are a different venue. Results land in `docs/strategy-research.json`.

## Status and limitations

- **Research not yet run.** The development sandbox had no network egress, so the shipped
  default (`donchian` 20/10, 1h, BTC/ETH/SOL, 0.5% risk) is a conventional, literature-based
  starting point, not a selected result. Run the commands above and apply the printed settings
  only after reviewing the out-of-sample section.
- Backtests are simulations from public OHLC data: no queue position, partial-fill or outage
  modelling, and the breaker is evaluated at bar closes (live checks every 5 seconds).
- Trend strategies have long flat or losing stretches; a breaker trip realises the loss and
  pauses trading for the cooldown.
- Testnet books are thin: entries are bounded IOC orders (default 0.3% through the touch) and
  may fill partially or not at all; the stop always covers the actual filled size.
