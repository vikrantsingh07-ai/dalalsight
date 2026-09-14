/** User drawings (trend lines and horizontal lines) rendered on the chart as a Lightweight Charts series primitive. */
import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
  UTCTimestamp,
} from "lightweight-charts";

export interface DrawingPoint {
  time: number;
  price: number;
}

export interface Drawing {
  id: string;
  kind: "trend" | "hline";
  points: DrawingPoint[];
}

type RenderTarget = Parameters<IPrimitivePaneRenderer["draw"]>[0];

interface Segment {
  kind: Drawing["kind"];
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  price: number;
  preview: boolean;
}

class DrawingsRenderer implements IPrimitivePaneRenderer {
  private readonly segments: Segment[];
  private readonly color: string;

  constructor(segments: Segment[], color: string) {
    this.segments = segments;
    this.color = color;
  }

  draw(target: RenderTarget): void {
    target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      context.save();
      context.lineWidth = Math.max(1, Math.round(1.5 * hr));
      context.strokeStyle = this.color;
      for (const segment of this.segments) {
        context.setLineDash(segment.preview ? [6 * hr, 4 * hr] : []);
        context.beginPath();
        if (segment.kind === "hline") {
          const y = Math.round(segment.y1 * vr) + 0.5;
          context.moveTo(0, y);
          context.lineTo(bitmapSize.width, y);
          context.stroke();
          const text = segment.price.toFixed(2);
          context.font = `${Math.round(11 * vr)}px sans-serif`;
          const width = context.measureText(text).width + 10 * hr;
          context.fillStyle = this.color;
          context.fillRect(6 * hr, y - 9 * vr, width, 17 * vr);
          context.fillStyle = "#ffffff";
          context.fillText(text, 11 * hr, y + 4 * vr);
        } else {
          context.moveTo(segment.x1 * hr, segment.y1 * vr);
          context.lineTo(segment.x2 * hr, segment.y2 * vr);
          context.stroke();
          context.setLineDash([]);
          context.fillStyle = this.color;
          for (const [x, y] of [
            [segment.x1, segment.y1],
            [segment.x2, segment.y2],
          ]) {
            context.beginPath();
            context.arc(x * hr, y * vr, 3.5 * hr, 0, Math.PI * 2);
            context.fill();
          }
        }
      }
      context.restore();
    });
  }
}

export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  private drawings: Drawing[] = [];
  private preview: Drawing | null = null;
  private chart: IChartApiBase<Time> | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;
  private renderer: DrawingsRenderer;
  private readonly color: string;
  private readonly views: readonly IPrimitivePaneView[];

  constructor(color: string) {
    this.color = color;
    this.renderer = new DrawingsRenderer([], color);
    this.views = [{ zOrder: () => "top", renderer: () => this.renderer }];
  }

  attached(param: SeriesAttachedParameter<Time, SeriesType>): void {
    this.chart = param.chart;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  setDrawings(drawings: Drawing[]): void {
    this.drawings = drawings;
    this.requestUpdate?.();
  }

  setPreview(preview: Drawing | null): void {
    this.preview = preview;
    this.requestUpdate?.();
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  updateAllViews(): void {
    const segments: Segment[] = [];
    const { chart, series } = this;
    if (chart && series) {
      const timeScale = chart.timeScale();
      const all = this.preview ? [...this.drawings, this.preview] : this.drawings;
      for (const drawing of all) {
        const preview = drawing === this.preview;
        if (drawing.kind === "hline" && drawing.points[0]) {
          const y = series.priceToCoordinate(drawing.points[0].price);
          if (y !== null) segments.push({ kind: "hline", x1: 0, y1: y, x2: 0, y2: y, price: drawing.points[0].price, preview });
        } else if (drawing.kind === "trend" && drawing.points.length === 2) {
          const [a, b] = drawing.points;
          const x1 = timeScale.timeToCoordinate(a.time as UTCTimestamp);
          const x2 = timeScale.timeToCoordinate(b.time as UTCTimestamp);
          const y1 = series.priceToCoordinate(a.price);
          const y2 = series.priceToCoordinate(b.price);
          if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) segments.push({ kind: "trend", x1, y1, x2, y2, price: b.price, preview });
        }
      }
    }
    this.renderer = new DrawingsRenderer(segments, this.color);
  }
}

export function loadDrawings(key: string): Drawing[] {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Drawing[]) : [];
  } catch {
    return [];
  }
}

export function saveDrawings(key: string, drawings: Drawing[]): void {
  try {
    if (drawings.length) localStorage.setItem(key, JSON.stringify(drawings));
    else localStorage.removeItem(key);
  } catch {
    /* storage unavailable: drawings last for this page load */
  }
}

export function newDrawingId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}
