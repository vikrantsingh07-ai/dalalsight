export type Priority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export const NO_TRADE = "NO TRADE / WAIT FOR CONFIRMATION";

export interface Unavailable {
  status: "unavailable";
  what: string;
  reason: string;
  source?: string;
  requirement?: string;
}

export function isUnavailable(value: unknown): value is Unavailable {
  return !!value && typeof value === "object" && (value as { status?: unknown }).status === "unavailable";
}

export interface MarketStatus {
  session: string;
  is_trading: boolean;
  label: string;
  now: string;
  session_date: string;
  next_open: string | null;
  reason: string;
  exchange_message: string | null;
}

export interface InstrumentMeta {
  symbol: string;
  name: string;
  kind: string;
  exchange: string;
  yahoo_symbol: string | null;
  tradingview_symbol: string | null;
  nse_index_name: string | null;
  option_type: string | null;
  lot_size: number | null;
  sector: string | null;
  has_volume: boolean;
}

export interface Quote {
  symbol: string;
  price: number;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  timestamp: string;
  provider: string;
  change: number | null;
  change_pct: number | null;
  extra: Record<string, number | string | null>;
}

export interface SignalComponent {
  name: string;
  weight: number;
  available: boolean;
  score: number;
  evidence: string[];
  unavailable_reason: string | null;
  contribution: number;
}

export interface TradePlan {
  direction: number;
  entry_low: number;
  entry_high: number;
  stop: number;
  stop_basis: string;
  target1: number;
  target1_basis: string;
  target2: number;
  target2_basis: string;
  risk_per_unit: number;
  risk_reward: number;
  invalidation: string;
  position_size_units: number | null;
  position_size_basis: string | null;
}

export interface Signal {
  symbol: string;
  timeframe: string;
  bar_time: string;
  price: number;
  label: string;
  direction: number;
  bullish_pct: number;
  bearish_pct: number;
  model_confidence: number;
  coverage: number;
  agreement: number;
  composite: number;
  components: SignalComponent[];
  plan: TradePlan | null;
  reasons: string[];
  risks: string[];
  regime: string;
  data_sources: string[];
  disclaimer: string;
  method: string;
}

export interface Regime {
  code: string;
  label: string;
  direction: number;
  volatility: string;
  adx: number | null;
  atr_pct: number | null;
  atr_percentile: number | null;
  evidence: string[];
}

export interface Level {
  price: number;
  kind: string;
  label: string;
  source: string;
  strength: number;
}

export interface Levels {
  price: number;
  atr: number | null;
  levels: Level[];
  nearest_support: Level | null;
  nearest_resistance: Level | null;
  breakout_level: number | null;
  breakdown_level: number | null;
  trendlines: { kind: string; points: [string, number][]; projection: number }[];
  session: Record<string, number>;
}

export interface TechEvent {
  key: string;
  kind: string;
  direction: number;
  priority: Priority;
  message: string;
  bar_time: string;
  values: Record<string, unknown>;
}

export interface Provenance {
  provider: string | null;
  has_volume: boolean;
  stale: boolean;
  lag_seconds: number | null;
  bars: number;
  first_bar?: string;
  last_bar: string;
  fetched_at: string | null;
  live_ticks_merged?: boolean;
}

export interface Technical {
  close: number;
  atr: number | null;
  atr_pct: number | null;
  ema?: {
    fast: number;
    slow: number;
    fast_period: number;
    slow_period: number;
    relation: string;
    price_vs_fast: string;
    price_vs_slow: string;
    fast_slope_pct_per_bar: number | null;
    distance_from_slow_pct: number;
    distance_from_slow_atr: number | null;
    last_cross_bars_ago: number | null;
    cross_confirmed: boolean;
  };
  vwap: { value: number | null; relation: string | null; unavailable_reason?: string };
  rsi?: { value: number; zone: string; change_3_bars: number | null };
  macd?: { macd: number | null; signal: number | null; histogram: number; relation: string; histogram_trend: string };
  volume: { last?: number | null; average20?: number | null; ratio?: number | null; unavailable_reason?: string };
  volatility: { atr: number | null; atr_ratio: number | null; bb_width: number | null; supertrend_dir: number | null };
  adx: number | null;
}

export interface SnapshotOptions {
  pcr_oi: number | null;
  call_oi_change: number | null;
  put_oi_change: number | null;
  call_wall: number | null;
  put_wall: number | null;
  expiry: string;
  max_pain: number | null;
  atm_iv: number | null;
  expected_range: [number, number] | null;
  timestamp: string;
}

export interface Snapshot {
  symbol: string;
  timeframe: string;
  mode: string;
  generated_at: string;
  market: MarketStatus;
  meta: InstrumentMeta;
  quote: Quote | Unavailable | null;
  price: number;
  bar_time: string;
  forming_bar_excluded: boolean;
  provenance: Provenance;
  signal: Signal;
  regime: Regime;
  levels: Levels;
  events: TechEvent[];
  technical: Technical;
  options: SnapshotOptions | null;
  options_status: Unavailable | null;
}

export interface ChartPoint {
  time: number;
  value: number;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface ChartData {
  symbol: string;
  timeframe: string;
  candles: Candle[];
  indicators: Record<string, ChartPoint[]>;
  periods: { ema_fast: number; ema_slow: number };
  levels: Levels;
  markers: { time: number; label: string; direction: number; price: number; id: number }[];
  time_basis: string;
  provenance: Provenance;
}

export interface SignalHistoryMarker {
  time: number;
  bar_time: string;
  label: string;
  direction: number;
  side: "BUY" | "SELL";
  risky: boolean;
  bullish_pct: number;
  confidence: number;
  price: number;
}

export interface SignalHistory {
  symbol: string;
  timeframe: string;
  bars: number;
  markers: SignalHistoryMarker[];
  latest: { bar_time: string; label: string; direction: number; bullish_pct: number; confidence: number; price: number } | null;
  counts: Record<string, number>;
  note: string;
}

export interface OptionLegView {
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  spread_pct: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  oi: number | null;
  oi_change: number | null;
  oi_change_pct: number | null;
  iv: number | null;
  iv_source: string | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  intrinsic: number;
  time_value: number | null;
  buildup: string | null;
}

export interface OptionRowView {
  strike: number;
  ce: OptionLegView | null;
  pe: OptionLegView | null;
}

export interface OiPoint {
  strike: number;
  oi: number | null;
  oi_change: number | null;
}

export interface OptionSummary {
  symbol: string;
  expiry: string;
  days_to_expiry: number;
  spot: number;
  timestamp: string;
  provider: string;
  age_seconds: number;
  stale: boolean;
  lot_size: number | null;
  strike_step: number | null;
  atm_strike: number | null;
  atm_iv: number | null;
  atm_straddle: number | null;
  expected_move_1sd: number | null;
  expected_range: [number, number] | null;
  expected_move_basis: string;
  iv_skew: { put_strike: number; put_iv: number; call_strike: number; call_iv: number; skew_vol_points: number; basis: string } | null;
  iv_percentile: { value: number; observations: number } | null;
  iv_percentile_note: string | null;
  totals: { call_oi: number; put_oi: number; call_volume: number; put_volume: number; call_oi_change: number; put_oi_change: number };
  pcr_oi: number | null;
  pcr_volume: number | null;
  max_pain: number | null;
  call_wall: number | null;
  put_wall: number | null;
  top_call_oi: OiPoint[];
  top_put_oi: OiPoint[];
  top_call_oi_added: OiPoint[];
  top_put_oi_added: OiPoint[];
  table: OptionRowView[];
  interpretation: string[];
  risk_free_rate: number;
}

export interface ContractCandidate {
  strike: number;
  option_type: string;
  premium: number;
  bid: number | null;
  ask: number | null;
  spread_pct: number | null;
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  oi: number | null;
  volume: number | null;
  breakeven_at_expiry: number;
  premium_per_lot: number | null;
  max_loss_per_lot: number | null;
  theta_per_lot_per_day: number | null;
  lots_within_risk_budget: number | null;
  score: number;
}

export interface Recommendations {
  symbol: string;
  expiry: string;
  timeframe: string;
  signal: { label: string; direction: number; bullish_pct: number; bearish_pct: number; model_confidence: number; plan: TradePlan | null; reasons: string[]; risks: string[] };
  spot: number;
  lot_size: number | null;
  risk_capital: number;
  side: string | null;
  candidates: ContractCandidate[];
  rejected: { strike: number; reasons: string[] }[];
  note?: string;
  score_basis?: string;
  risk_note?: string;
}

export interface StrategyLegView {
  option_type: string;
  side: number;
  strike: number;
  lots: number;
  premium: number;
  iv: number | null;
  price_source: string;
  action: string;
}

export interface StrategyResult {
  name: string;
  legs: StrategyLegView[];
  spot: number;
  lot_size: number;
  days_to_expiry: number;
  net_premium: number;
  premium_type: string;
  max_profit: number | string;
  max_loss: number | string;
  reward_to_risk: number | null;
  breakevens: number[];
  probability_of_profit: number | null;
  pop_basis: string;
  net_greeks: Record<string, number> | null;
  greeks_note: string | null;
  capital: { premium_paid: number; premium_received: number; capital_at_risk: number | null; margin: string };
  payoff: { prices: number[]; expiry_pnl: number[]; t0_pnl: number[] | null };
  symbol: string;
  expiry: string;
  chain_timestamp: string;
  provider: string;
  template: string | null;
}

export interface ModelState {
  model: string;
  role: string;
  usable: boolean;
  state: string;
}

export interface MonitorState {
  running: boolean;
  cycles: number;
  last_cycle_at: string | null;
  cycle_seconds: number | null;
  interval: number | null;
  symbol_errors: Record<string, Unavailable>;
  last_error: string | null;
}

export interface ReplayState {
  running: boolean;
  symbol?: string;
  timeframe?: string;
  session_date?: string;
  bars?: number;
  processed?: number;
  interval_seconds?: number;
  provider?: string;
  available_dates?: string[];
  error?: string;
  finished_at?: string;
}

export interface StatusPayload {
  app: { name: string; version: string; started_at: string; now: string };
  market: MarketStatus;
  ai: {
    status: string;
    active_model: string | null;
    last_model_used: string | null;
    calls_today: number;
    daily_budget: number;
    budget_left: number;
    key_configured: boolean;
    models: ModelState[];
    last_error: string | null;
  };
  provider: { name: string; status: string };
  execution: { mode: string; live_execution_enabled: boolean };
  monitor: MonitorState;
  replay: ReplayState;
}

export interface ConfigPayload {
  public: Record<string, string | number | boolean>;
  timeframes: string[];
  strategy_templates: Record<string, { name: string; view: string; risk: string; default_width: number }>;
  scanner_presets: Record<string, { name: string; description: string }>;
  universes: string[];
  agents: Record<string, { name: string; kind: string; est_calls: number; description: string }>;
  indices: Record<string, { name: string; tradingview: string; options: boolean }>;
  disclaimer: string;
}

export interface Settings {
  default_symbol: string;
  default_timeframe: string;
  theme: "dark" | "light";
  ai_model_override: string;
  execution_mode: "analysis" | "paper" | "live";
  watchlist: string[];
  commentary: {
    enabled: boolean;
    min_interval_seconds: number;
    event_cooldown_seconds: number;
    confidence_change_points: number;
    level_test_atr: number;
    llm_min_priority: Priority;
    speak_min_priority: Priority;
    during_market_hours_only: boolean;
  };
  voice: { enabled: boolean; voice_name: string; lang: string; rate: number; pitch: number };
  market_hours: {
    timezone: string;
    pre_open_start: string;
    market_open: string;
    closing_period_start: string;
    market_close: string;
    post_close_end: string;
    extra_holidays: string[];
  };
  signal: {
    weights: Record<string, number>;
    bullish_threshold: number;
    bearish_threshold: number;
    watch_band: number;
    min_confidence: number;
    min_coverage: number;
    min_risk_reward: number;
    ema_fast: number;
    ema_slow: number;
    crossover_confirm_bars: number;
    rsi_period: number;
    rsi_overbought: number;
    rsi_oversold: number;
    volume_spike_mult: number;
    volume_confirm_mult: number;
    atr_period: number;
    supertrend_period: number;
    supertrend_mult: number;
    swing_lookback: number;
    breakout_lookback: number;
  };
  risk: { profile: string; capital: number; risk_per_trade_pct: number; max_stop_atr: number };
  options: {
    risk_free_rate: number;
    strikes_around_atm: number;
    max_spread_pct: number;
    min_oi: number;
    min_volume: number;
    delta_min: number;
    delta_max: number;
    hedge_min_days_to_expiry: number;
  };
  monitor: {
    symbols: string[];
    timeframe: string;
    poll_seconds_open: number;
    poll_seconds_closed: number;
    option_symbols: string[];
    option_poll_seconds: number;
    oi_change_event_pct: number;
  };
  notifications: { browser: boolean; sound: boolean; voice: boolean; telegram: boolean; webhook: boolean; email: boolean };
  agents: { agent_weights: Record<string, number>; max_tool_rounds: number; max_minutes_per_analyst: number };
}

export interface CommentaryEntry {
  id: number;
  ts: string;
  symbol: string;
  timeframe: string;
  priority: Priority;
  text: string;
  text_source: string;
  speak: boolean;
  mode: string;
  facts?: Record<string, unknown>;
}

export interface KeyLevel {
  price: number;
  type: string;
  note: string;
}

export interface AgentResult {
  agent: string;
  name: string;
  timestamp: string;
  symbol: string;
  timeframe: string;
  signal: string;
  confidence: number | null;
  confidence_basis: string;
  reasoning: string;
  key_levels: KeyLevel[];
  risks: string[];
  data_sources: string[];
  report: string;
  model: string | null;
  status: string;
  error: string | null;
  duration_s: number | null;
  warnings: string[];
}

export interface Consensus {
  signal: string;
  direction_view?: string;
  score: number | null;
  agreement_pct: number | null;
  votes: { agent: string; name: string; signal: string; confidence: number; weight: number; basis: string }[];
  conflicts: { agent: string; name: string; signal: string; confidence: number; reasoning: string }[];
  reason: string;
  method: string;
}

export interface AgentRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  kind: string;
  symbol: string;
  timeframe: string;
  status: string;
  model: string | null;
  results?: AgentResult[];
  consensus: Consensus | null;
  error: string | null;
}

export interface AlertRule {
  type: string;
  symbol: string;
  timeframe: string | null;
  value: number | null;
  label: string | null;
  event_kind: string | null;
}

export interface AlertRow {
  id: number;
  name: string;
  rule: AlertRule;
  channels: string[];
  enabled: boolean;
  cooldown_seconds: number;
  created_at: string;
  last_triggered_at: string | null;
}

export interface AlertEventRow {
  id: number;
  alert_id: number | null;
  ts: string;
  symbol: string | null;
  message: string;
  delivery: Record<string, string>;
}

export interface SignalRow {
  id: number;
  created_at: string;
  source: string;
  symbol: string;
  timeframe: string;
  bar_time: string;
  label: string;
  direction: number;
  price: number;
  bullish_pct: number;
  confidence: number;
  coverage: number;
  entry_low: number;
  entry_high: number;
  stop: number;
  target1: number;
  target2: number;
  rr: number;
  status: string;
  outcome: { status?: string; r_multiple?: number; mfe_r?: number; mae_r?: number } | null;
  closed_at: string | null;
}

export interface TimelineEntry {
  id: number;
  ts: string;
  kind: string;
  symbol: string | null;
  message: string;
}

export interface ErrorRow {
  id: number;
  ts: string;
  level: string;
  source: string;
  message: string;
}

export interface HealthComponent {
  name: string;
  status: string;
  detail: string;
  models?: ModelState[];
  last_error?: string | null;
  last_success?: string | null;
  latency_ms?: number | null;
  capabilities?: string[];
}

export interface HealthReport {
  overall: string;
  generated_at: string;
  components: HealthComponent[];
  recent_errors: ErrorRow[];
}

export interface BacktestTrade {
  label: string;
  direction: number;
  signal_time: string;
  entry_time: string;
  exit_time: string;
  entry: number;
  exit: number;
  stop: number;
  target: number;
  bars_held: number;
  reason: string;
  r_multiple: number;
  pnl_pct: number;
  mfe_r: number | null;
  mae_r: number | null;
}

export interface BacktestSummary {
  symbol: string;
  timeframe: string;
  period: { start: string; end: string; bars: number };
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_r: number | null;
  expectancy_r: number | null;
  total_r: number;
  profit_factor: number | null;
  max_drawdown_r: number;
  avg_bars_held: number | null;
  exit_reasons: Record<string, number>;
  by_label: Record<string, { trades: number; win_rate: number; avg_r: number }>;
  signal_label_counts: Record<string, number>;
  skipped_gap_entries: number;
  entries_not_filled?: number;
  equity_curve_r?: number[];
  calibration?: Calibration;
  assumptions: string[];
  data_source?: string;
}

export interface CalibrationBucket {
  bucket: string;
  samples: number;
  up_first: number;
  down_first: number;
  neither: number;
  ambiguous: number;
  stated_bullish_pct: number | null;
  observed_up_pct: number | null;
  avg_forward_atr: number | null;
  directional_samples: number;
  hit_pct: number | null;
  avg_forward_atr_in_direction: number | null;
}

export interface Calibration {
  samples: number;
  horizon_bars: number;
  touch_atr: number;
  mean_abs_gap_pts: number | null;
  by_bullish_pct: CalibrationBucket[];
  by_label: CalibrationBucket[];
  by_confidence: CalibrationBucket[];
  method: string;
  note: string;
}

export interface BacktestRow {
  id: number;
  created_at: string;
  status: string;
  params: Record<string, unknown>;
  summary: BacktestSummary | null;
  trades?: BacktestTrade[];
  error: string | null;
}
