import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineWidth,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApp } from "../context/AppContext";
import { pastRate, useCalibration } from "../lib/calibration";
import { istTime, num, pct, signed } from "../lib/format";
import { useApi, useEvents, useLocalState } from "../lib/hooks";
import { plainLabel, strengthOf } from "../lib/plain";
import type { Candle, ChartData, Levels, SignalHistory, TradePlan } from "../lib/types";
import { DrawingsPrimitive, loadDrawings, newDrawingId, saveDrawings, type Drawing, type DrawingPoint } from "./chart/drawings";
import { Help } from "./InfoTip";
import { ErrorNote, Spinner } from "./ui";

// Black background with green, red, blue and yellow (the user's colours), laid out like the TradingView app.
const PALETTE = {
  dark: {
    bg: "#000000",
    panel: "#0b0b0b",
    grid: "rgba(38, 38, 38, 0.7)",
    border: "#262626",
    text: "#f5f5f5",
    muted: "#9ca3af",
    hover: "#1a1a1a",
    up: "#22c55e",
    down: "#ef4444",
    blue: "#2962ff",
    yellow: "#facc15",
    lightBlue: "#60a5fa",
    lightYellow: "#fde68a",
    lightGreen: "#86efac",
    white: "#e5e5e5",
  },
  light: {
    bg: "#ffffff",
    panel: "#ffffff",
    grid: "rgba(240, 243, 250, 1)",
    border: "#e0e3eb",
    text: "#131722",
    muted: "#787b86",
    hover: "#f0f3fa",
    up: "#089981",
    down: "#f23645",
    blue: "#2962ff",
    yellow: "#c79100",
    lightBlue: "#1e88e5",
    lightYellow: "#a16207",
    lightGreen: "#15803d",
    white: "#404040",
  },
};
type Palette = (typeof PALETTE)["dark"];
type ChartType = "candles" | "heikin" | "bars" | "line" | "area";
type Tool = "cursor" | "trend" | "hline";
type Feed = "spot" | "futures";

interface Studies {
  signals: boolean;
  levels: boolean;
  plan: boolean;
  volume: boolean;
  ema: boolean;
  ema2050: boolean;
  sma200: boolean;
  vwap: boolean;
  bb: boolean;
  supertrend: boolean;
  rsi: boolean;
  macd: boolean;
}

const DEFAULT_STUDIES: Studies = { signals: true, levels: true, plan: true, volume: true, ema: false, ema2050: false, sma200: false, vwap: false, bb: false, supertrend: false, rsi: false, macd: false };

const TIMEFRAMES: [string, string][] = [
  ["1m", "1m"],
  ["3m", "3m"],
  ["5m", "5m"],
  ["15m", "15m"],
  ["30m", "30m"],
  ["1h", "1H"],
  ["4h", "4H"],
  ["1D", "D"],
  ["1W", "W"],
];

const CHART_TYPES: [ChartType, string][] = [
  ["candles", "Candles"],
  ["heikin", "Heikin Ashi"],
  ["bars", "Bars"],
  ["line", "Line"],
  ["area", "Area"],
];

const STUDY_MENU: [keyof Studies, string][] = [
  ["signals", "BUY / SELL signals"],
  ["levels", "Floor & ceiling"],
  ["plan", "Plan lines"],
  ["volume", "Volume"],
  ["ema", "EMA 9 / 21"],
  ["ema2050", "EMA 20 / 50"],
  ["sma200", "SMA 200"],
  ["vwap", "VWAP"],
  ["bb", "Bollinger Bands"],
  ["supertrend", "Supertrend"],
  ["rsi", "RSI (lower pane)"],
  ["macd", "MACD (lower pane)"],
];

interface Overlay {
  key: string;
  study: keyof Studies;
  label: (data: ChartData | null) => string;
  color: (p: Palette) => string;
  style?: LineStyle;
}

const OVERLAYS: Overlay[] = [
  { key: "ema_fast", study: "ema", label: (d) => `EMA ${d?.periods.ema_fast ?? 9}`, color: (p) => p.blue },
  { key: "ema_slow", study: "ema", label: (d) => `EMA ${d?.periods.ema_slow ?? 21}`, color: (p) => p.yellow },
  { key: "ema20", study: "ema2050", label: () => "EMA 20", color: (p) => p.lightBlue },
  { key: "ema50", study: "ema2050", label: () => "EMA 50", color: (p) => p.lightYellow },
  { key: "sma200", study: "sma200", label: () => "SMA 200", color: (p) => p.white },
  { key: "vwap", study: "vwap", label: () => "VWAP", color: (p) => p.white, style: LineStyle.Dashed },
  { key: "bb_upper", study: "bb", label: () => "BB upper", color: (p) => p.muted },
  { key: "bb_lower", study: "bb", label: () => "BB lower", color: (p) => p.muted },
  { key: "supertrend", study: "supertrend", label: () => "Supertrend", color: (p) => p.lightGreen },
];

interface Handles {
  chart: IChartApi;
  main: ISeriesApi<SeriesType>;
  volume: ISeriesApi<"Histogram">;
  overlays: Record<string, ISeriesApi<"Line">>;
  rsi: ISeriesApi<"Line"> | null;
  macd: { hist: ISeriesApi<"Histogram">; line: ISeriesApi<"Line">; signal: ISeriesApi<"Line"> } | null;
  markers: ISeriesMarkersPluginApi<Time>;
  drawings: DrawingsPrimitive;
  lines: IPriceLine[];
  fitted: boolean;
}

interface SignalMark {
  side: "BUY" | "SELL";
  label: string;
  direction: number;
  bullish: number | null;
  confidence: number | null;
  risky: boolean;
}

const validCandle = (c: Candle) => [c.open, c.high, c.low, c.close].every((value) => typeof value === "number");

function withAlpha(hex: string, alpha: number): string {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function heikinAshi(candles: Candle[]): Candle[] {
  const out: Candle[] = [];
  let previous: Candle | null = null;
  for (const c of candles) {
    const close = (c.open + c.high + c.low + c.close) / 4;
    const open: number = previous ? (previous.open + previous.close) / 2 : (c.open + c.close) / 2;
    const bar: Candle = { time: c.time, open, high: Math.max(c.high, open, close), low: Math.min(c.low, open, close), close, volume: c.volume };
    out.push(bar);
    previous = bar;
  }
  return out;
}

function Menu({ label, palette, children, align = "left" }: { label: ReactNode; palette: Palette; children: (close: () => void) => ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);
  return (
    <div ref={box} className="relative">
      <ToolbarButton palette={palette} active={open} onClick={() => setOpen((value) => !value)} ariaExpanded={open}>
        {label} <span className="text-[10px] opacity-70">▾</span>
      </ToolbarButton>
      {open && (
        <div className={`absolute top-full z-30 mt-1 min-w-52 rounded-md border p-1 shadow-2xl ${align === "right" ? "right-0" : "left-0"}`} style={{ background: palette.panel, borderColor: palette.border }}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function ToolbarButton({ palette, active, onClick, children, title, ariaExpanded, disabled }: { palette: Palette; active?: boolean; onClick: () => void; children: ReactNode; title?: string; ariaExpanded?: boolean; disabled?: boolean }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      aria-pressed={active}
      aria-expanded={ariaExpanded}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-8 items-center gap-1 rounded px-2 text-[13px] transition hover:brightness-110 disabled:opacity-40"
      style={{ color: active ? palette.yellow : palette.text, background: active ? palette.hover : "transparent" }}
    >
      {children}
    </button>
  );
}

function Divider({ palette }: { palette: Palette }) {
  return <span className="mx-1 h-5 w-px" style={{ background: palette.border }} aria-hidden="true" />;
}

const ICONS: Record<Tool | "undo" | "clear", ReactNode> = {
  cursor: (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M12 3v18M3 12h18" />
    </svg>
  ),
  trend: (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M5 19 19 5" />
      <circle cx="5" cy="19" r="2" fill="currentColor" />
      <circle cx="19" cy="5" r="2" fill="currentColor" />
    </svg>
  ),
  hline: (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M3 12h18" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
    </svg>
  ),
  undo: (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M9 7 4 12l5 5M4 12h11a5 5 0 0 1 0 10h-3" />
    </svg>
  ),
  clear: (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
    </svg>
  ),
};

/**
 * Home's chart, laid out like the TradingView app and drawn with TradingView Lightweight Charts on DalalSight's own data
 * (TradingView's embed widget refuses NSE and allows BSE only on daily candles, and the full Advanced Charts library is
 * only licensed for public websites). BUY/SELL arrows carry the past-check % from the newest backtest. Spot candles come
 * from NSE/Yahoo; futures candles need the Alice Blue feed. The TradingView button opens the real widget
 * (TradingViewPanel.tsx).
 */
export default function TradingChart({
  symbol,
  timeframe,
  plan,
  levels,
  isTrading,
  onOpenTradingView,
}: {
  symbol: string;
  timeframe: string;
  plan: TradePlan | null;
  levels: Levels | null;
  isTrading: boolean;
  onOpenTradingView: () => void;
}) {
  const { settings, setTimeframe } = useApp();
  const theme = settings?.theme === "light" ? "light" : "dark";
  const palette = PALETTE[theme];
  const [feed, setFeed] = useLocalState<Feed>("cc_chart_feed", "spot");
  const [chartType, setChartType] = useLocalState<ChartType>("cc_chart_type", "candles");
  const [storedStudies, setStudies] = useLocalState<Studies>("cc_chart_studies", DEFAULT_STUDIES);
  const studies = useMemo(() => ({ ...DEFAULT_STUDIES, ...storedStudies }), [storedStudies]);
  const [tool, setTool] = useState<Tool>("cursor");
  const [waitingForSecondPoint, setWaitingForSecondPoint] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  const target = encodeURIComponent(symbol);
  const chart = useApi<ChartData>(`/api/chart/${target}?timeframe=${timeframe}&bars=1000${feed === "futures" ? "&feed=futures" : ""}`, { interval: isTrading ? 20_000 : 300_000 });
  const history = useApi<SignalHistory>(feed === "spot" ? `/api/signals/history/${target}?timeframe=${timeframe}&bars=250` : null, { interval: isTrading ? 60_000 : 600_000 });
  const calibration = useCalibration(feed === "spot" ? symbol : null, timeframe);
  useEvents(["signal"], (message) => {
    const data = message.data as { symbol: string; timeframe: string };
    if (data.symbol === symbol && data.timeframe === timeframe) {
      chart.reload();
      history.reload();
    }
  });

  const data = chart.data?.symbol === symbol && chart.data.timeframe === timeframe && !chart.error ? chart.data : null;
  const past = feed === "spot" && history.data?.symbol === symbol && history.data.timeframe === timeframe ? history.data : null;
  const cal = feed === "spot" && calibration.data?.symbol === symbol && calibration.data.timeframe === timeframe ? calibration.data : null;

  const wrapper = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const toolRef = useRef<Tool>("cursor");
  const pending = useRef<DrawingPoint | null>(null);
  const [version, setVersion] = useState(0);

  const drawingKey = `cc_drawings:${symbol}:${timeframe}:${feed}`;
  const [drawings, setDrawings] = useState<Drawing[]>(() => loadDrawings(drawingKey));
  const loadedKey = useRef(drawingKey);
  useEffect(() => {
    if (loadedKey.current !== drawingKey) {
      loadedKey.current = drawingKey;
      setDrawings(loadDrawings(drawingKey));
    }
  }, [drawingKey]);
  useEffect(() => saveDrawings(loadedKey.current, drawings), [drawings]);

  const chooseTool = (next: Tool) => {
    toolRef.current = next;
    pending.current = null;
    handles.current?.drawings.setPreview(null);
    setWaitingForSecondPoint(false);
    setTool(next);
  };

  useEffect(() => {
    if (tool === "cursor") return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      toolRef.current = "cursor";
      pending.current = null;
      handles.current?.drawings.setPreview(null);
      setWaitingForSecondPoint(false);
      setTool("cursor");
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [tool]);

  useEffect(() => {
    const change = () => setFullscreen(document.fullscreenElement === wrapper.current);
    document.addEventListener("fullscreenchange", change);
    return () => document.removeEventListener("fullscreenchange", change);
  }, []);

  // One chart per market, candle size, feed, chart type, theme and lower-pane layout.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const p = PALETTE[theme];
    const daily = timeframe === "1D" || timeframe === "1W";
    const instance = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: p.bg },
        textColor: p.muted,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif",
        fontSize: 12,
        panes: { separatorColor: p.border, separatorHoverColor: p.hover },
      },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: p.border },
      timeScale: { borderColor: p.border, timeVisible: !daily, secondsVisible: false, rightOffset: 8, barSpacing: 7 },
      localization: { locale: "en-IN" },
    });
    let main: ISeriesApi<SeriesType>;
    if (chartType === "bars") main = instance.addSeries(BarSeries, { upColor: p.up, downColor: p.down, thinBars: false });
    else if (chartType === "line") main = instance.addSeries(LineSeries, { color: p.blue, lineWidth: 2 });
    else if (chartType === "area") main = instance.addSeries(AreaSeries, { lineColor: p.blue, topColor: withAlpha(p.blue, 0.28), bottomColor: withAlpha(p.blue, 0.02), lineWidth: 2 });
    else main = instance.addSeries(CandlestickSeries, { upColor: p.up, downColor: p.down, borderVisible: false, wickUpColor: p.up, wickDownColor: p.down });

    const volume = instance.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", priceLineVisible: false, lastValueVisible: false });
    instance.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const overlays: Record<string, ISeriesApi<"Line">> = {};
    for (const overlay of OVERLAYS) {
      overlays[overlay.key] = instance.addSeries(LineSeries, {
        color: overlay.color(p),
        lineWidth: 1 as LineWidth,
        lineStyle: overlay.style ?? LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    }
    let pane = 0;
    let rsi: ISeriesApi<"Line"> | null = null;
    if (studies.rsi) {
      pane += 1;
      rsi = instance.addSeries(LineSeries, { color: p.lightBlue, lineWidth: 1 as LineWidth, priceLineVisible: false, title: "RSI" }, pane);
      rsi.createPriceLine({ price: 70, color: p.muted, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 30, color: p.muted, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
    }
    let macd: Handles["macd"] = null;
    if (studies.macd) {
      pane += 1;
      macd = {
        hist: instance.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane),
        line: instance.addSeries(LineSeries, { color: p.blue, lineWidth: 1 as LineWidth, priceLineVisible: false, lastValueVisible: false, title: "MACD" }, pane),
        signal: instance.addSeries(LineSeries, { color: p.yellow, lineWidth: 1 as LineWidth, priceLineVisible: false, lastValueVisible: false }, pane),
      };
    }
    // Price pane 4 parts, each lower pane 1 part (480 px + 120 px per pane when not full screen).
    instance.panes().forEach((item, index) => item.setStretchFactor(index === 0 ? 4 : 1));

    const markers = createSeriesMarkers(main, []);
    const drawingLayer = new DrawingsPrimitive(p.blue);
    main.attachPrimitive(drawingLayer);

    const pointFrom = (param: MouseEventParams<Time>): DrawingPoint | null => {
      if (!param.point || param.time === undefined) return null;
      const price = main.coordinateToPrice(param.point.y);
      return price === null ? null : { time: Number(param.time), price };
    };
    const finishDrawing = () => {
      toolRef.current = "cursor";
      pending.current = null;
      drawingLayer.setPreview(null);
      setWaitingForSecondPoint(false);
      setTool("cursor");
    };
    const onMove = (param: MouseEventParams<Time>) => {
      setHoverTime(param.time === undefined ? null : Number(param.time));
      const start = pending.current;
      if (toolRef.current === "trend" && start) {
        const point = pointFrom(param);
        if (point) drawingLayer.setPreview({ id: "preview", kind: "trend", points: [start, point] });
      }
    };
    const onClick = (param: MouseEventParams<Time>) => {
      const active = toolRef.current;
      if (active === "cursor") return;
      const point = pointFrom(param);
      if (!point) return;
      if (active === "hline") {
        setDrawings((list) => [...list, { id: newDrawingId(), kind: "hline", points: [point] }]);
        finishDrawing();
      } else if (!pending.current) {
        pending.current = point;
        setWaitingForSecondPoint(true);
      } else {
        const start = pending.current;
        setDrawings((list) => [...list, { id: newDrawingId(), kind: "trend", points: [start, point] }]);
        finishDrawing();
      }
    };
    instance.subscribeCrosshairMove(onMove);
    instance.subscribeClick(onClick);
    handles.current = { chart: instance, main, volume, overlays, rsi, macd, markers, drawings: drawingLayer, lines: [], fitted: false };
    setVersion((value) => value + 1);
    return () => {
      instance.unsubscribeCrosshairMove(onMove);
      instance.unsubscribeClick(onClick);
      instance.remove();
      handles.current = null;
      setHoverTime(null);
    };
  }, [symbol, timeframe, feed, chartType, theme, studies.rsi, studies.macd]);

  const candles = useMemo(() => (data ? data.candles.filter(validCandle) : []), [data]);

  // Price series, volume and indicators.
  useEffect(() => {
    const current = handles.current;
    if (!current) return;
    const p = PALETTE[theme];
    const series = chartType === "heikin" ? heikinAshi(candles) : candles;
    if (chartType === "line" || chartType === "area") {
      (current.main as unknown as ISeriesApi<"Line">).setData(series.map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
    } else {
      (current.main as unknown as ISeriesApi<"Candlestick">).setData(series.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    }
    const hasVolume = candles.some((c) => (c.volume ?? 0) > 0);
    current.volume.setData(
      studies.volume && hasVolume ? candles.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume ?? 0, color: withAlpha(c.close >= c.open ? p.up : p.down, 0.4) })) : [],
    );
    const points = (key: string) => (data?.indicators[key] ?? []).map((point) => ({ time: point.time as UTCTimestamp, value: point.value }));
    for (const overlay of OVERLAYS) current.overlays[overlay.key].setData(studies[overlay.study] ? points(overlay.key) : []);
    current.rsi?.setData(points("rsi"));
    if (current.macd) {
      current.macd.hist.setData((data?.indicators.macd_hist ?? []).map((point) => ({ time: point.time as UTCTimestamp, value: point.value, color: withAlpha(point.value >= 0 ? p.up : p.down, 0.6) })));
      current.macd.line.setData(points("macd"));
      current.macd.signal.setData(points("macd_signal"));
    }
    if (!current.fitted && candles.length) {
      current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 160), to: candles.length + 8 });
      current.fitted = true;
    }
  }, [candles, data, chartType, studies, theme, version]);

  // BUY / SELL markers: signal changes rebuilt on past candles plus setups recorded live by the monitor.
  const signalMarks = useMemo(() => {
    const map = new Map<number, SignalMark>();
    for (const marker of past?.markers ?? []) {
      map.set(marker.time, { side: marker.side, label: marker.label, direction: marker.direction, bullish: marker.bullish_pct, confidence: marker.confidence, risky: marker.risky });
    }
    if (feed === "spot") {
      for (const marker of data?.markers ?? []) {
        if (!map.has(marker.time)) map.set(marker.time, { side: marker.direction > 0 ? "BUY" : "SELL", label: marker.label, direction: marker.direction, bullish: null, confidence: null, risky: marker.label.startsWith("HIGH-RISK") });
      }
    }
    return map;
  }, [past, data, feed]);

  useEffect(() => {
    const current = handles.current;
    if (!current) return;
    const p = PALETTE[theme];
    const times = new Set(candles.map((c) => c.time));
    const list: SeriesMarker<Time>[] = [];
    if (studies.signals) {
      for (const [time, mark] of [...signalMarks.entries()].sort((a, b) => a[0] - b[0])) {
        if (!times.has(time)) continue;
        const buy = mark.side === "BUY";
        const rate = mark.bullish === null ? null : pastRate(cal, mark.bullish, mark.direction);
        list.push({
          time: time as UTCTimestamp,
          position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown",
          color: mark.risky ? p.yellow : buy ? p.up : p.down,
          text: `${buy ? "BUY" : "SELL"}${rate?.enough ? ` ${Math.round(rate.rate)}%` : ""}`,
          size: 1.6,
        });
      }
    }
    current.markers.setMarkers(list);
  }, [candles, signalMarks, studies.signals, cal, theme, version]);

  // Floor / ceiling and the current plan.
  useEffect(() => {
    const current = handles.current;
    if (!current) return;
    const p = PALETTE[theme];
    current.lines.forEach((line) => current.main.removePriceLine(line));
    current.lines = [];
    if (feed !== "spot" || !candles.length) return;
    const add = (price: number, color: string, title: string, style: LineStyle, width: LineWidth = 1) =>
      current.lines.push(current.main.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title }));
    if (studies.levels && levels) {
      if (levels.nearest_support) add(levels.nearest_support.price, p.up, "Floor", LineStyle.Dotted);
      if (levels.nearest_resistance) add(levels.nearest_resistance.price, p.down, "Ceiling", LineStyle.Dotted);
    }
    if (studies.plan && plan) {
      add((plan.entry_low + plan.entry_high) / 2, p.yellow, plan.direction > 0 ? "Buy zone" : "Sell zone", LineStyle.Solid);
      add(plan.stop, p.down, "Stop loss", LineStyle.Solid, 2);
      add(plan.target1, p.up, "Target 1", LineStyle.Dashed, 2);
      add(plan.target2, p.up, "Target 2", LineStyle.Dashed);
    }
  }, [candles, plan, levels, feed, studies.levels, studies.plan, theme, version]);

  useEffect(() => {
    handles.current?.drawings.setDrawings(drawings);
  }, [drawings, version]);

  // Legend: hovered (or last) candle, active indicators and any signal on that candle.
  const indexByTime = useMemo(() => new Map(candles.map((c, index) => [c.time, index])), [candles]);
  const indicatorAt = (key: string, time: number | undefined) => (time === undefined ? undefined : data?.indicators[key]?.find((point) => point.time === time)?.value);
  const shownIndex = hoverTime !== null && indexByTime.has(hoverTime) ? (indexByTime.get(hoverTime) as number) : candles.length - 1;
  const shown = shownIndex >= 0 ? candles[shownIndex] : undefined;
  const previous = shownIndex > 0 ? candles[shownIndex - 1] : undefined;
  const change = shown && previous ? shown.close - previous.close : null;
  const changePct = change !== null && previous ? (change / previous.close) * 100 : null;
  const hoveredSignal = shown ? signalMarks.get(shown.time) : undefined;
  const hoveredPast = hoveredSignal && hoveredSignal.bullish !== null ? pastRate(cal, hoveredSignal.bullish, hoveredSignal.direction) : null;
  const hoveredScore = hoveredSignal && hoveredSignal.bullish !== null ? (hoveredSignal.direction < 0 ? 100 - hoveredSignal.bullish : hoveredSignal.bullish) : null;
  const upColor = (value: number | null) => (value === null ? palette.text : value >= 0 ? palette.up : palette.down);
  const tfLabel = TIMEFRAMES.find(([tf]) => tf === timeframe)?.[1] ?? timeframe;
  const futuresUnavailable = feed === "futures" && Boolean(chart.error);

  const toggleStudy = (key: keyof Studies) => setStudies({ ...studies, [key]: !studies[key] });
  const screenshot = () => {
    const current = handles.current;
    if (!current) return;
    const link = document.createElement("a");
    link.href = current.chart.takeScreenshot().toDataURL("image/png");
    link.download = `${symbol}-${timeframe}-${feed}.png`;
    link.click();
  };
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrapper.current?.requestFullscreen();
  };
  const paneCount = (studies.rsi ? 1 : 0) + (studies.macd ? 1 : 0);

  return (
    <section
      ref={wrapper}
      className={`min-w-0 overflow-hidden rounded-lg border ${fullscreen ? "flex h-screen flex-col rounded-none" : ""}`}
      style={{ background: palette.bg, borderColor: palette.border, color: palette.text }}
      aria-label={`${symbol} chart`}
    >
      <div className="flex flex-wrap items-center gap-0.5 border-b px-2 py-1" style={{ borderColor: palette.border }}>
        <span className="px-2 text-sm font-semibold">{symbol}</span>
        <div className="flex items-center rounded p-0.5" style={{ background: palette.hover }} role="group" aria-label="Candles">
          {(["spot", "futures"] as Feed[]).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={feed === value}
              onClick={() => setFeed(value)}
              className="rounded px-2 py-1 text-[12px]"
              style={{ background: feed === value ? palette.bg : "transparent", color: feed === value ? palette.text : palette.muted }}
            >
              {value === "spot" ? "Spot" : "Futures"}
            </button>
          ))}
        </div>
        <Divider palette={palette} />
        {TIMEFRAMES.map(([tf, label]) => (
          <ToolbarButton key={tf} palette={palette} active={tf === timeframe} onClick={() => setTimeframe(tf)} title={`${label} candles`}>
            {label}
          </ToolbarButton>
        ))}
        <Divider palette={palette} />
        <Menu label={CHART_TYPES.find(([type]) => type === chartType)?.[1] ?? "Candles"} palette={palette}>
          {(close) =>
            CHART_TYPES.map(([type, label]) => (
              <button
                key={type}
                type="button"
                onClick={() => {
                  setChartType(type);
                  close();
                }}
                className="flex w-full items-center justify-between rounded px-3 py-1.5 text-left text-[13px]"
                style={{ color: type === chartType ? palette.yellow : palette.text }}
              >
                {label} {type === chartType && <span>✓</span>}
              </button>
            ))
          }
        </Menu>
        <Menu label="Indicators" palette={palette}>
          {() =>
            STUDY_MENU.map(([key, label]) => (
              <label key={key} className="flex cursor-pointer items-center gap-2 rounded px-3 py-1.5 text-[13px]" style={{ color: palette.text }}>
                <input type="checkbox" checked={studies[key]} onChange={() => toggleStudy(key)} className="accent-[#facc15]" />
                {label}
              </label>
            ))
          }
        </Menu>
        <div className="ml-auto flex items-center gap-0.5">
          {(chart.loading || history.loading) && <Spinner label="Loading" />}
          <ToolbarButton palette={palette} onClick={onOpenTradingView} title="Open the real TradingView chart (BSE markets, daily candles)">
            <span className="rounded px-1 text-[11px] font-bold" style={{ background: palette.blue, color: "#ffffff" }}>
              TV
            </span>
            TradingView
          </ToolbarButton>
          <ToolbarButton palette={palette} onClick={() => handles.current?.chart.timeScale().scrollToRealTime()} title="Go to latest candle">
            Latest
          </ToolbarButton>
          <ToolbarButton palette={palette} onClick={() => handles.current?.chart.timeScale().fitContent()} title="Fit all candles">
            Fit
          </ToolbarButton>
          <ToolbarButton palette={palette} onClick={screenshot} title="Save chart as image">
            Snapshot
          </ToolbarButton>
          <ToolbarButton palette={palette} onClick={toggleFullscreen} title={fullscreen ? "Exit full screen" : "Full screen"}>
            {fullscreen ? "Exit full screen" : "Full screen"}
          </ToolbarButton>
          <span className="px-1">
            <Help topic="chart" align="right" />
          </span>
        </div>
      </div>

      <div className={`flex min-h-0 ${fullscreen ? "flex-1" : ""}`}>
        <div className="flex w-11 shrink-0 flex-col items-center gap-1 border-r py-2" style={{ borderColor: palette.border }} role="toolbar" aria-label="Drawing tools">
          <ToolbarButton palette={palette} active={tool === "cursor"} onClick={() => chooseTool("cursor")} title="Crosshair">
            {ICONS.cursor}
          </ToolbarButton>
          <ToolbarButton palette={palette} active={tool === "trend"} onClick={() => chooseTool("trend")} title="Trend line: click two points">
            {ICONS.trend}
          </ToolbarButton>
          <ToolbarButton palette={palette} active={tool === "hline"} onClick={() => chooseTool("hline")} title="Horizontal line: click a price">
            {ICONS.hline}
          </ToolbarButton>
          <span className="my-1 h-px w-6" style={{ background: palette.border }} aria-hidden="true" />
          <ToolbarButton palette={palette} onClick={() => setDrawings((list) => list.slice(0, -1))} title="Undo last drawing" disabled={!drawings.length}>
            {ICONS.undo}
          </ToolbarButton>
          <ToolbarButton
            palette={palette}
            onClick={() => {
              if (window.confirm(`Remove all ${drawings.length} drawing(s) on this chart?`)) setDrawings([]);
            }}
            title="Remove all drawings"
            disabled={!drawings.length}
          >
            {ICONS.clear}
          </ToolbarButton>
        </div>

        <div className="relative min-w-0 flex-1">
          <div ref={host} className={`w-full ${fullscreen ? "h-full" : ""} ${tool === "cursor" ? "" : "cursor-crosshair"}`} style={fullscreen ? undefined : { height: 480 + paneCount * 120 }} />
          <div className="pointer-events-none absolute left-3 right-20 top-2 z-10 space-y-1 text-[12px]" aria-live="polite">
            <div className="flex flex-wrap items-center gap-x-2">
              <span className="font-semibold" style={{ color: palette.text }}>
                {symbol} · {tfLabel} · {feed === "futures" ? "Futures" : "Spot"}
              </span>
              {shown && (
                <span className="flex flex-wrap gap-x-2 font-mono">
                  {(["open", "high", "low", "close"] as const).map((key) => (
                    <span key={key} style={{ color: palette.muted }}>
                      {key[0].toUpperCase()} <span style={{ color: upColor(shown.close - shown.open) }}>{num(shown[key])}</span>
                    </span>
                  ))}
                  {change !== null && (
                    <span style={{ color: upColor(change) }}>
                      {signed(change)} ({pct(changePct)})
                    </span>
                  )}
                </span>
              )}
            </div>
            {OVERLAYS.filter((overlay) => studies[overlay.study]).map((overlay) => (
              <div key={overlay.key} className="font-mono" style={{ color: overlay.color(palette) }}>
                {overlay.label(data)} {num(indicatorAt(overlay.key, shown?.time))}
              </div>
            ))}
            {hoveredSignal && studies.signals && (
              <div className="inline-block rounded px-2 py-0.5 font-medium" style={{ background: palette.panel, color: hoveredSignal.risky ? palette.yellow : hoveredSignal.side === "BUY" ? palette.up : palette.down, border: `1px solid ${palette.border}` }}>
                {hoveredSignal.side === "BUY" ? "▲" : "▼"} {plainLabel(hoveredSignal.label, hoveredSignal.direction)} on this candle
                {hoveredPast?.enough && ` · worked before ${num(hoveredPast.rate, 0)}% (${hoveredPast.resolved} past cases)`}
                {hoveredScore !== null && ` · model score ${num(hoveredScore, 0)}% ${hoveredSignal.direction < 0 ? "bearish" : "bullish"}`}
                {hoveredSignal.confidence !== null && ` · strength ${strengthOf(hoveredSignal.confidence).label}`}
              </div>
            )}
            {tool !== "cursor" && (
              <div className="inline-block rounded px-2 py-0.5" style={{ background: palette.blue, color: "#ffffff" }}>
                {tool === "trend" ? (waitingForSecondPoint ? "Click the second point" : "Click the first point of the trend line") : "Click a price to draw a horizontal line"} · Esc to cancel
              </div>
            )}
          </div>
          {!data && !chart.error && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Spinner label="Loading chart" />
            </div>
          )}
          {chart.error ? (
            <div className="absolute inset-0 z-20 flex items-center justify-center p-6">
              <div className="max-w-md space-y-2 text-sm" style={{ color: palette.text }}>
                {futuresUnavailable && <div className="font-semibold">Futures candles need the Alice Blue connection</div>}
                <ErrorNote error={chart.error} />
                {feed === "futures" && (
                  <button type="button" onClick={() => setFeed("spot")} className="rounded px-3 py-1.5 text-[13px] font-medium" style={{ background: palette.yellow, color: "#000000" }}>
                    Show spot candles
                  </button>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-3 py-1.5 text-[11px]" style={{ borderColor: palette.border, color: palette.muted }}>
        <span>
          <span style={{ color: palette.up }}>▲ BUY</span> / <span style={{ color: palette.down }}>▼ SELL</span> where the signal turned · <span style={{ color: palette.yellow }}>yellow</span> = risky
        </span>
        {cal &&
          (cal.available ? (
            <span>
              % on an arrow = how often similar readings went that way first in a past test ({istTime(cal.period.start, { date: true })} – {istTime(cal.period.end, { date: true })}); not a promise
            </span>
          ) : (
            <span>
              No past test for {symbol} {tfLabel} yet, so the arrows show no %
            </span>
          ))}
        {past && <span>{past.markers.length} signal changes in the last {past.bars} candles</span>}
        {feed === "futures" && <span>Signals and levels are worked out on the spot index</span>}
        <span>{isTrading ? "Live: updates every 20 seconds" : "Market closed: last session shown"}</span>
        {drawings.length > 0 && <span>{drawings.length} drawing(s) saved for this chart</span>}
        <span className="ml-auto">Data: {data?.provenance.provider ?? "…"} · Chart library by TradingView</span>
      </div>
    </section>
  );
}
