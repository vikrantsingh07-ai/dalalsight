import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineWidth,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useApp } from "../context/AppContext";
import { num } from "../lib/format";
import { useApi, useEvents, useLocalState } from "../lib/hooks";
import type { ChartData, Levels, SignalHistory, TradePlan } from "../lib/types";
import { Help } from "./InfoTip";
import { Card, Checkbox, ErrorNote, Spinner } from "./ui";

import { TIMEFRAME_LABELS } from "../lib/timeframes";

interface Layers {
  signals: boolean;
  levels: boolean;
  plan: boolean;
  averages: boolean;
}

interface Handles {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick">;
  volume: ISeriesApi<"Histogram">;
  fast: ISeriesApi<"Line">;
  slow: ISeriesApi<"Line">;
  markers: ISeriesMarkersPluginApi<Time>;
  lines: IPriceLine[];
  fitted: boolean;
}

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function palette() {
  return {
    bull: cssColor("--color-bull", "#26a86f"),
    bear: cssColor("--color-bear", "#e5534b"),
    warn: cssColor("--color-warn", "#d6a13a"),
    info: cssColor("--color-info", "#5b93ff"),
    accent: cssColor("--color-accent", "#e0952b"),
    muted: cssColor("--color-muted", "#8894a5"),
    edge: cssColor("--color-edge", "#243042"),
    panel: cssColor("--color-panel", "#11161e"),
  };
}

function alpha(hex: string, opacity: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return hex;
  const value = Number.parseInt(match[1], 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${opacity})`;
}

/**
 * Candlestick chart drawn with TradingView Lightweight Charts on DalalSight's own NSE/Yahoo data
 * (TradingView's embed widget refuses NSE/BSE symbols), with the engine's BUY/SELL signals as markers.
 */
export default function LiveChart({ symbol, timeframe, plan, levels, isTrading }: { symbol: string; timeframe: string; plan: TradePlan | null; levels: Levels | null; isTrading: boolean }) {
  const { settings } = useApp();
  const theme = settings?.theme ?? "dark";
  const [layers, setLayers] = useLocalState<Layers>("cc_chart_layers", { signals: true, levels: true, plan: true, averages: false });
  const target = encodeURIComponent(symbol);
  const chart = useApi<ChartData>(`/api/chart/${target}?timeframe=${timeframe}&bars=400`, { interval: isTrading ? 20_000 : 300_000 });
  const history = useApi<SignalHistory>(`/api/signals/history/${target}?timeframe=${timeframe}&bars=250`, { interval: isTrading ? 60_000 : 600_000 });
  useEvents(["signal"], (message) => {
    const data = message.data as { symbol: string; timeframe: string };
    if (data.symbol === symbol && data.timeframe === timeframe) {
      chart.reload();
      history.reload();
    }
  });

  const host = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const [version, setVersion] = useState(0);
  const [hover, setHover] = useState<CandlestickData<Time> | null>(null);

  const data = chart.data?.symbol === symbol && chart.data.timeframe === timeframe ? chart.data : null;
  const past = history.data?.symbol === symbol && history.data.timeframe === timeframe ? history.data : null;

  // One chart per market, candle size and theme; data effects below update it in place.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const colors = palette();
    const instance = createChart(element, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: colors.panel }, textColor: colors.muted, fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
      grid: { vertLines: { color: alpha(colors.muted, 0.08) }, horzLines: { color: alpha(colors.muted, 0.08) } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: colors.edge },
      timeScale: { borderColor: colors.edge, timeVisible: timeframe !== "1D" && timeframe !== "1W", secondsVisible: false, rightOffset: 6 },
      localization: { locale: "en-IN" },
    });
    const candles = instance.addSeries(CandlestickSeries, { upColor: colors.bull, downColor: colors.bear, borderVisible: false, wickUpColor: colors.bull, wickDownColor: colors.bear });
    const volume = instance.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", priceLineVisible: false, lastValueVisible: false });
    instance.priceScale("volume").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const averageOptions = { lineWidth: 1 as LineWidth, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
    const fast = instance.addSeries(LineSeries, { ...averageOptions, color: colors.info });
    const slow = instance.addSeries(LineSeries, { ...averageOptions, color: colors.accent });
    const markers = createSeriesMarkers(candles, []);
    const onMove = (param: MouseEventParams<Time>) => {
      const bar = param.seriesData.get(candles) as CandlestickData<Time> | undefined;
      setHover(bar ?? null);
    };
    instance.subscribeCrosshairMove(onMove);
    handles.current = { chart: instance, candles, volume, fast, slow, markers, lines: [], fitted: false };
    setVersion((value) => value + 1);
    return () => {
      instance.unsubscribeCrosshairMove(onMove);
      instance.remove();
      handles.current = null;
      setHover(null);
    };
  }, [symbol, timeframe, theme]);

  // Candles, volume and optional moving averages.
  useEffect(() => {
    const current = handles.current;
    if (!current || !data) return;
    const colors = palette();
    const candles = data.candles.filter((c) => [c.open, c.high, c.low, c.close].every((value) => typeof value === "number"));
    current.candles.setData(candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    const hasVolume = candles.some((c) => (c.volume ?? 0) > 0);
    current.volume.setData(hasVolume ? candles.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume ?? 0, color: alpha(c.close >= c.open ? colors.bull : colors.bear, 0.3) })) : []);
    const average = (key: string) => (layers.averages ? (data.indicators[key] ?? []).map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) : []);
    current.fast.setData(average("ema_fast"));
    current.slow.setData(average("ema_slow"));
    if (!current.fitted && candles.length) {
      current.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 150), to: candles.length + 6 });
      current.fitted = true;
    }
  }, [data, layers.averages, version]);

  // BUY / SELL markers: signal changes rebuilt on past candles plus setups recorded live by the monitor.
  useEffect(() => {
    const current = handles.current;
    if (!current || !data) return;
    const colors = palette();
    const times = new Set(data.candles.map((c) => c.time));
    const list = new Map<string, SeriesMarker<Time>>();
    const add = (time: number, buy: boolean, risky: boolean) => {
      const key = `${time}:${buy ? "BUY" : "SELL"}`;
      if (!times.has(time) || list.has(key)) return;
      list.set(key, {
        time: time as UTCTimestamp,
        position: buy ? "belowBar" : "aboveBar",
        shape: buy ? "arrowUp" : "arrowDown",
        color: risky ? colors.warn : buy ? colors.bull : colors.bear,
        text: buy ? "BUY" : "SELL",
      });
    };
    if (layers.signals) {
      for (const marker of past?.markers ?? []) add(marker.time, marker.side === "BUY", marker.risky);
      for (const marker of data.markers) add(marker.time, marker.direction > 0, marker.label.startsWith("HIGH-RISK"));
    }
    current.markers.setMarkers([...list.values()].sort((a, b) => Number(a.time) - Number(b.time)));
  }, [data, past, layers.signals, version]);

  // Price floor / ceiling and the current plan as horizontal lines.
  useEffect(() => {
    const current = handles.current;
    if (!current || !data) return;
    const colors = palette();
    current.lines.forEach((line) => current.candles.removePriceLine(line));
    current.lines = [];
    const add = (price: number, color: string, title: string, style: LineStyle, width: LineWidth = 1) =>
      current.lines.push(current.candles.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title }));
    if (layers.levels && levels) {
      if (levels.nearest_support) add(levels.nearest_support.price, colors.bull, "Floor", LineStyle.Dotted);
      if (levels.nearest_resistance) add(levels.nearest_resistance.price, colors.bear, "Ceiling", LineStyle.Dotted);
    }
    if (layers.plan && plan) {
      add((plan.entry_low + plan.entry_high) / 2, colors.accent, plan.direction > 0 ? "Buy zone" : "Sell zone", LineStyle.Solid);
      add(plan.stop, colors.bear, "Stop loss", LineStyle.Solid, 2);
      add(plan.target1, colors.bull, "Target 1", LineStyle.Dashed, 2);
      add(plan.target2, colors.bull, "Target 2", LineStyle.Dashed);
    }
  }, [data, plan, levels, layers.levels, layers.plan, version]);

  const last = data?.candles.at(-1);
  const shown = hover ?? (last ? { open: last.open, high: last.high, low: last.low, close: last.close } : null);
  const toggle = (key: keyof Layers) => (value: boolean) => setLayers({ ...layers, [key]: value });

  return (
    <Card
      title={`Chart · ${symbol} · ${TIMEFRAME_LABELS[timeframe] ?? timeframe} candles`}
      info={<Help topic="chart" />}
      actions={
        <>
          <Checkbox label="BUY/SELL signals" checked={layers.signals} onChange={toggle("signals")} />
          <Checkbox label="Floor & ceiling" checked={layers.levels} onChange={toggle("levels")} />
          <Checkbox label="Plan lines" checked={layers.plan} onChange={toggle("plan")} />
          <Checkbox label="Averages" checked={layers.averages} onChange={toggle("averages")} />
        </>
      }
    >
      <ErrorNote error={chart.error} />
      <div className="relative">
        <div ref={host} className="h-[360px] w-full md:h-[480px]" />
        {shown && (
          <div className="pointer-events-none absolute left-2 top-2 z-10 flex flex-wrap gap-x-3 rounded bg-panel/85 px-2 py-1 font-mono text-[11px]">
            <span className="text-muted">
              Open <span className="text-text">{num(shown.open)}</span>
            </span>
            <span className="text-muted">
              High <span className="text-text">{num(shown.high)}</span>
            </span>
            <span className="text-muted">
              Low <span className="text-text">{num(shown.low)}</span>
            </span>
            <span className="text-muted">
              Close <span className={shown.close >= shown.open ? "text-bull" : "text-bear"}>{num(shown.close)}</span>
            </span>
          </div>
        )}
        {!data && !chart.error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Spinner label="Loading chart" />
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        <span>
          <span className="text-bull">▲ BUY</span> / <span className="text-bear">▼ SELL</span>: where the signal turned
        </span>
        <span>
          <span className="text-warn">▲▼</span> risky setup
        </span>
        <span>dotted: floor / ceiling</span>
        <span>solid: current plan</span>
        {history.loading && !past && <Spinner label="Finding past signals" />}
      </div>
      <div className="mt-1 text-[11px] text-muted/80">
        {past ? `${past.markers.length} signal changes in the last ${past.bars} candles · ` : ""}
        {isTrading ? "Updates every 20 seconds · " : "Market closed: last session shown · "}
        Data: {data?.provenance.provider ?? "…"} · Chart library by TradingView
      </div>
      {history.error ? <div className="mt-1 text-[11px] text-warn">Past signals are unavailable right now.</div> : null}
    </Card>
  );
}
