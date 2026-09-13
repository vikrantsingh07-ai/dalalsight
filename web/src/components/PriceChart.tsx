import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type LineWidth,
  type LogicalRange,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { ChartData, TradePlan } from "../lib/types";

export interface Overlays {
  ema: boolean;
  vwap: boolean;
  bb: boolean;
  supertrend: boolean;
  levels: boolean;
  plan: boolean;
  rsi: boolean;
  macd: boolean;
}

const ranges = new Map<string, LogicalRange>();

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export default function PriceChart({ data, overlays, plan, height = 480 }: { data: ChartData; overlays: Overlays; plan?: TradePlan | null; height?: number }) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const element = container.current;
    if (!element || !data.candles.length) return;
    const key = `${data.symbol}:${data.timeframe}`;
    const bull = cssColor("--color-bull", "#26a86f");
    const bear = cssColor("--color-bear", "#e5534b");
    const muted = cssColor("--color-muted", "#8894a5");
    const edge = cssColor("--color-edge", "#243042");
    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: cssColor("--color-panel", "#11161e") },
        textColor: muted,
        fontFamily: "IBM Plex Mono, ui-monospace, monospace",
        fontSize: 11,
        panes: { separatorColor: edge, separatorHoverColor: edge },
      },
      grid: { vertLines: { color: "rgba(136,148,165,0.07)" }, horzLines: { color: "rgba(136,148,165,0.07)" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: edge },
      timeScale: { borderColor: edge, timeVisible: data.timeframe !== "1D" && data.timeframe !== "1W", secondsVisible: false, rightOffset: 4 },
      localization: { locale: "en-IN" },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, { upColor: bull, downColor: bear, borderVisible: false, wickUpColor: bull, wickDownColor: bear, priceLineVisible: true });
    candles.setData(data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));

    const line = (keyName: string, color: string, width: LineWidth = 1, style: LineStyle = LineStyle.Solid, pane = 0, title = "") => {
      const points = data.indicators[keyName];
      if (!points?.length) return null;
      const series = chart.addSeries(LineSeries, { color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: !!title, crosshairMarkerVisible: false, title }, pane);
      series.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      return series;
    };

    if (overlays.ema) {
      line("ema_fast", "#5b93ff", 2, LineStyle.Solid, 0, `EMA${data.periods.ema_fast}`);
      line("ema_slow", "#e0952b", 2, LineStyle.Solid, 0, `EMA${data.periods.ema_slow}`);
    }
    if (overlays.vwap) line("vwap", "#b284ff", 2, LineStyle.Dashed, 0, "VWAP");
    if (overlays.bb) {
      line("bb_upper", "rgba(136,148,165,0.7)", 1, LineStyle.Dotted);
      line("bb_lower", "rgba(136,148,165,0.7)", 1, LineStyle.Dotted);
    }
    if (overlays.supertrend) line("supertrend", "#6fcfc0", 1, LineStyle.Solid, 0, "ST");

    const hasVolume = data.candles.some((c) => c.volume !== null && c.volume > 0);
    if (hasVolume) {
      const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", priceLineVisible: false, lastValueVisible: false });
      volume.setData(
        data.candles.map((c) => ({ time: c.time as UTCTimestamp, value: c.volume ?? 0, color: c.close >= c.open ? "rgba(38,168,111,0.35)" : "rgba(229,83,75,0.35)" })),
      );
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    }

    let pane = 1;
    if (overlays.rsi && data.indicators.rsi?.length) {
      const rsi = line("rsi", "#e0952b", 1, LineStyle.Solid, pane, "RSI");
      rsi?.createPriceLine({ price: 70, color: bear, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      rsi?.createPriceLine({ price: 30, color: bull, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      pane += 1;
    }
    if (overlays.macd && data.indicators.macd_hist?.length) {
      const histogram = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      histogram.setData(data.indicators.macd_hist.map((p) => ({ time: p.time as UTCTimestamp, value: p.value, color: p.value >= 0 ? "rgba(38,168,111,0.6)" : "rgba(229,83,75,0.6)" })));
      line("macd", "#5b93ff", 1, LineStyle.Solid, pane, "MACD");
      line("macd_signal", "#e0952b", 1, LineStyle.Solid, pane);
      pane += 1;
    }
    chart.panes().forEach((p, index) => {
      if (index > 0) p.setHeight(90);
    });

    if (overlays.levels) {
      const nearest = new Set([data.levels.nearest_support?.price, data.levels.nearest_resistance?.price]);
      const price = data.levels.price;
      const above = data.levels.levels.filter((level) => level.price > price).sort((a, b) => a.price - b.price).slice(0, 4);
      const below = data.levels.levels.filter((level) => level.price <= price).sort((a, b) => b.price - a.price).slice(0, 4);
      [...above, ...below].forEach((level) =>
          candles.createPriceLine({
            price: level.price,
            color: level.kind === "support" ? bull : bear,
            lineWidth: nearest.has(level.price) ? 2 : 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: level.label.slice(0, 28),
          }),
        );
    }
    if (overlays.plan && plan) {
      const accent = cssColor("--color-accent", "#e0952b");
      candles.createPriceLine({ price: plan.entry_high, color: accent, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "Entry" });
      candles.createPriceLine({ price: plan.entry_low, color: accent, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: false, title: "" });
      candles.createPriceLine({ price: plan.stop, color: bear, lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "Stop" });
      candles.createPriceLine({ price: plan.target1, color: bull, lineWidth: 2, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "T1" });
      candles.createPriceLine({ price: plan.target2, color: bull, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "T2" });
    }
    if (data.markers.length) {
      createSeriesMarkers(
        candles,
        [...data.markers]
          .sort((a, b) => a.time - b.time)
          .map((marker) => ({
            time: marker.time as UTCTimestamp,
            position: marker.direction > 0 ? ("belowBar" as const) : ("aboveBar" as const),
            color: marker.direction > 0 ? bull : bear,
            shape: marker.direction > 0 ? ("arrowUp" as const) : ("arrowDown" as const),
            text: `#${marker.id}`,
          })),
      );
    }

    const saved = ranges.get(key);
    if (saved) chart.timeScale().setVisibleLogicalRange(saved);
    else chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.candles.length - 180), to: data.candles.length + 4 });
    const onRange = (range: LogicalRange | null) => {
      if (range) ranges.set(key, range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      chart.remove();
      chartRef.current = null;
    };
  }, [data, overlays, plan]);

  return <div ref={container} style={{ height }} className="w-full" />;
}
