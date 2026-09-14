/** Plain-language explanations behind the (i) buttons, written for someone new to trading. */
export const HELP = {
  signal: {
    title: "What does the signal mean?",
    body: "DalalSight checks 8 things on finished candles: trend, momentum, volume, moving averages, VWAP, price pattern, volatility and options data. When most agree, it shows a BUY setup (price may rise) or a SELL setup (price may fall). When they don't agree, it says WAIT. It is a computer estimate for learning and research, not advice.",
  },
  strength: {
    title: "Signal strength",
    body: "How many of the 8 checks agree, reduced when some data is missing. Weak is under 40, medium 40–55, strong 55 and above. In past tests stronger signals were not clearly more accurate, so treat it as a rough guide.",
  },
  trackRecord: {
    title: "Past check",
    body: "DalalSight replayed this market and candle size on past data. This line shows how often price moved one normal-sized step (1 ATR) in the signal's direction before moving one step against it, when the engine gave a similar reading. Around 50% is a coin flip.",
  },
  entry: {
    title: "Buy zone / Sell zone",
    body: "The price range where the setup begins. If price has already moved far away from it, the setup is no longer valid.",
  },
  stop: {
    title: "Stop loss",
    body: "The price that proves the idea wrong. Traders exit there to keep the loss small.",
  },
  target: {
    title: "Targets",
    body: "Prices where the move may pause: the next ceiling for a buy, or the next floor for a sell. Target 2 is further away and less likely.",
  },
  rr: {
    title: "Reward vs risk",
    body: "The possible gain to Target 1 compared with the possible loss to the stop loss. 1 : 2 means about twice as much to gain as to lose.",
  },
  support: {
    title: "Price floor (support)",
    body: "A price where buyers stepped in before. Falls often slow down or bounce there. The ceiling (resistance) is the opposite: a price where sellers stepped in and rises often stall.",
  },
  resistance: {
    title: "Price ceiling (resistance)",
    body: "A price where sellers stepped in before, so rises often slow down or turn back there.",
  },
  levelsBreak: {
    title: "Breakout and breakdown",
    body: "The highest and lowest prices of the last 20 candles. A close above the high (breakout) or below the low (breakdown) often starts a bigger move, but it can also be a fake-out.",
  },
  timeframe: {
    title: "Candle size",
    body: "How much time each candle on the chart covers. 5 min shows quick moves inside the day; 1 day shows the bigger picture. The signal is worked out separately for each candle size, so it can differ.",
  },
  chart: {
    title: "Reading the chart",
    body: "Each candle is one period: green closed higher than it opened, red closed lower. Green ▲ BUY and red ▼ SELL arrows mark where the signal turned on a finished candle; amber arrows are risky setups. Dotted lines are the price floor and ceiling; solid lines are the current plan (zone, stop loss, targets).",
  },
  mood: {
    title: "Market mood",
    body: "How this market is behaving right now: trending up, trending down, moving sideways, or very jumpy. Signals that follow a trend work better in trends than in sideways markets.",
  },
  updates: {
    title: "Latest updates",
    body: "Short notes written when something important happens, such as a breakout or a sharp move. They appear only while the market is open.",
  },
  markets: {
    title: "Choose a market",
    body: "NIFTY is India's top 50 companies, BANKNIFTY the big banks, FINNIFTY financial companies, MIDCPNIFTY mid-sized companies and SENSEX BSE's top 30. You can also type a stock name such as RELIANCE in the search box.",
  },
  marketStatus: {
    title: "Market hours",
    body: "NSE trades Monday to Friday, 09:15–15:30 IST, except exchange holidays. When the market is closed, DalalSight shows the last session's data.",
  },
  practice: {
    title: "Practice mode",
    body: "DalalSight never places real orders. In practice (paper) mode you can record pretend trades at real prices to learn without risking money. View only mode shows analysis without any orders.",
  },
  connection: {
    title: "Connection",
    body: "Live means this page is receiving updates from the DalalSight server and prices are arriving from NSE and Yahoo.",
  },
  advanced: {
    title: "Advanced details",
    body: "The raw numbers behind the simple view: every check's score, all price levels, indicator values and options data. Useful once you are comfortable with the basics.",
  },
} satisfies Record<string, { title: string; body: string }>;

export type HelpTopic = keyof typeof HELP;
