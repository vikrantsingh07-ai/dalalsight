import { useId } from "react";
import { num } from "../lib/format";

export function PayoffChart({ prices, expiry, t0, spot, breakevens, height = 260 }: { prices: number[]; expiry: number[]; t0: number[] | null; spot: number; breakevens: number[]; height?: number }) {
  const id = useId().replace(/:/g, "");
  if (prices.length < 2) return null;
  const width = 640;
  const pad = { l: 64, r: 12, t: 14, b: 26 };
  const values = [...expiry, ...(t0 ?? [])];
  const minY = Math.min(0, ...values);
  const maxY = Math.max(0, ...values);
  const minX = prices[0];
  const maxX = prices[prices.length - 1];
  const x = (p: number) => pad.l + ((p - minX) / (maxX - minX || 1)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - minY) / (maxY - minY || 1)) * (height - pad.t - pad.b);
  const path = (series: number[]) => series.map((v, i) => `${i ? "L" : "M"}${x(prices[i]).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const zero = y(0);
  const area = `${path(expiry)}L${x(maxX).toFixed(1)},${zero.toFixed(1)}L${x(minX).toFixed(1)},${zero.toFixed(1)}Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Strategy payoff at expiry and today">
      <defs>
        <clipPath id={`above-${id}`}>
          <rect x={pad.l} y={pad.t} width={width - pad.l - pad.r} height={Math.max(0, zero - pad.t)} />
        </clipPath>
        <clipPath id={`below-${id}`}>
          <rect x={pad.l} y={zero} width={width - pad.l - pad.r} height={Math.max(0, height - pad.b - zero)} />
        </clipPath>
      </defs>
      <path d={area} fill="var(--color-bull)" fillOpacity={0.18} clipPath={`url(#above-${id})`} />
      <path d={area} fill="var(--color-bear)" fillOpacity={0.18} clipPath={`url(#below-${id})`} />
      <line x1={pad.l} x2={width - pad.r} y1={zero} y2={zero} stroke="var(--color-edge)" />
      {spot >= minX && spot <= maxX && (
        <g>
          <line x1={x(spot)} x2={x(spot)} y1={pad.t} y2={height - pad.b} stroke="var(--color-muted)" strokeDasharray="3 3" />
          <text x={x(spot) + 4} y={pad.t + 10} fontSize="10" fill="var(--color-muted)">
            spot {num(spot, 0)}
          </text>
        </g>
      )}
      <path d={path(expiry)} fill="none" stroke="var(--color-accent)" strokeWidth={2} />
      {t0 && <path d={path(t0)} fill="none" stroke="var(--color-info)" strokeWidth={1.5} strokeDasharray="5 4" />}
      {breakevens
        .filter((b) => b >= minX && b <= maxX)
        .map((b) => (
          <g key={b}>
            <circle cx={x(b)} cy={zero} r={3.5} fill="var(--color-text)" />
            <text x={x(b)} y={height - 8} fontSize="10" textAnchor="middle" fill="var(--color-text)">
              {num(b, 0)}
            </text>
          </g>
        ))}
      <text x={pad.l - 6} y={y(maxY) + 4} fontSize="10" textAnchor="end" fill="var(--color-muted)">
        {num(maxY, 0)}
      </text>
      <text x={pad.l - 6} y={zero + 4} fontSize="10" textAnchor="end" fill="var(--color-muted)">
        0
      </text>
      <text x={pad.l - 6} y={y(minY) + 4} fontSize="10" textAnchor="end" fill="var(--color-muted)">
        {num(minY, 0)}
      </text>
      <text x={pad.l} y={height - 8} fontSize="10" fill="var(--color-muted)">
        {num(minX, 0)}
      </text>
      <text x={width - pad.r} y={height - 8} fontSize="10" textAnchor="end" fill="var(--color-muted)">
        {num(maxX, 0)}
      </text>
    </svg>
  );
}

export function LineSpark({ values, height = 140, label }: { values: number[]; height?: number; label: string }) {
  if (values.length < 2) return null;
  const width = 640;
  const pad = 20;
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - pad * 2);
  const y = (v: number) => pad / 2 + (1 - (v - min) / (max - min || 1)) * (height - pad);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const last = values[values.length - 1];
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={label}>
      <line x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} stroke="var(--color-edge)" />
      <path d={d} fill="none" stroke={last >= 0 ? "var(--color-bull)" : "var(--color-bear)"} strokeWidth={2} />
      <text x={width - pad} y={y(last) - 6} fontSize="11" textAnchor="end" fill="var(--color-text)">
        {num(last, 2)}R
      </text>
    </svg>
  );
}
