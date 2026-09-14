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
    title: "Using the chart",
    body: "It works like the TradingView app. Top bar: Spot or Futures candles, candle size, chart type (Candles, Heikin Ashi, Bars, Line, Area) and Indicators (EMAs, VWAP, Bollinger Bands, Supertrend, RSI and MACD panes). Left bar: draw trend lines (two clicks) and horizontal lines (one click); drawings are saved for this chart. Scroll to zoom, drag to move. Green ▲ BUY and red ▼ SELL arrows mark where the signal turned on a finished candle (yellow = risky). The % on an arrow is how often similar readings went that way first in a past test. Hover a candle to read it. Dotted lines: price floor and ceiling. Solid lines: the current plan. The TradingView button opens the real TradingView chart.",
  },
  chartViews: {
    title: "The real TradingView chart",
    body: "The TradingView button opens TradingView's own chart with its tools and indicators. Outside its website TradingView only allows BSE markets (SENSEX, BANKEX and BSE stock prices) on daily or weekly candles, blocks NSE markets such as NIFTY, and doesn't let other apps draw BUY/SELL arrows or % on it. The main DalalSight chart shows every market and candle size with arrows and %.",
  },
  probability: {
    title: "Worked before % and model score %",
    body: "Worked before: DalalSight replayed this market and candle size on old prices. Out of past readings like this one, this is how often price moved one normal step (1 ATR) the signal's way before moving one step against it. It is a real count from the past, not a promise; around 50% is a coin flip. It shows only when there were at least 30 past cases. Model score: how bullish or bearish the 8 checks look right now. It is not a win chance, because past tests showed high scores did not win more often.",
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
  breadth: {
    title: "Rising vs falling stocks",
    body: "How many of the NIFTY 500 companies (the 500 biggest on NSE) rose, fell or stayed flat today, each counted once. When most rise together, the up-move is broad and healthier; when only a few rise, the index may be carried by a handful of big names.",
  },
  sectors: {
    title: "Sectors",
    body: "Groups of companies from the same industry, such as IT, banks or pharma. Seeing which sectors lead or lag shows where money is flowing today.",
  },
  indexSignals: {
    title: "Signals for the main indices",
    body: "While the market is open, DalalSight checks the main indices every 30 seconds with the same signal as Home. Tap a row to open that market's chart.",
  },
  healthScore: {
    title: "Stock health score",
    body: "A 0–100 score from simple checks on the price trend, strength against NIFTY, trading activity and company numbers. Above 55 looks healthy, below 45 looks weak. It is a starting point for research, not a buy or sell call.",
  },
  fundamentals: {
    title: "Company numbers",
    body: "Numbers from the company's financial reports. P/E compares the share price with yearly profit per share (lower can mean cheaper). Return on equity shows how much profit the company makes on its owners' money. Debt/equity compares borrowing with owners' money (lower is safer).",
  },
  performance: {
    title: "Recent performance",
    body: "How the price behaved recently. 'vs NIFTY' shows whether the stock did better (+) or worse (−) than the index. RSI above 70 means the price rose fast and may be stretched; below 30 means it fell fast. Trend strength (ADX) above 25 means a strong trend. Beta above 1 means it usually moves more than NIFTY.",
  },
  scanner: {
    title: "Find stocks",
    body: "Checks a whole list of stocks at once and shows the ones that match what you are looking for, ranked by the health score. Click any stock to see its details.",
  },
  alertCondition: {
    title: "When to alert",
    body: "What has to happen before DalalSight tells you, for example the price going above a level you choose, or a BUY or SELL setup appearing.",
  },
  alertChannels: {
    title: "How to tell you",
    body: "'On this page' and sound work straight away. Browser pop-ups need your permission (button at the top). Telegram, email and webhook need extra setup on the server.",
  },
  alertRepeat: {
    title: "Wait before repeating",
    body: "After an alert fires, DalalSight waits this long before sending the same alert again, so you aren't flooded.",
  },
  pastSignals: {
    title: "Past signals",
    body: "Every BUY or SELL setup found while the market was open is saved, then checked against what price did next. Win rate is the share of finished signals that made money. R is the result in units of the planned risk: +2R means twice the risk was gained, −1R means the stop loss was hit.",
  },
  practiceTrade: {
    title: "Practice trade",
    body: "Record a pretend buy or sell at the real current price. Nothing is sent to any broker. Use it to practise and see how your ideas would have worked out.",
  },
  backtest: {
    title: "Test on old data",
    body: "Replays the signal on old prices, candle by candle, without peeking at the future, and shows how its trades would have turned out. Good past results don't guarantee future results.",
  },
  results: {
    title: "Reading test results",
    body: "Win rate: share of test trades that made money. R: result in units of the planned risk (+1R gained what was risked, −1R lost it). Profit factor: total gains ÷ total losses (above 1 made money). Worst drop: the biggest fall from a high point, in R.",
  },
} satisfies Record<string, { title: string; body: string }>;

export type HelpTopic = keyof typeof HELP;
