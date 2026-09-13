import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { ApiError, describe } from "../lib/api";
import { TEXT_TONES, type Tone } from "../lib/tones";
import { isUnavailable, type Unavailable } from "../lib/types";

const TONES: Record<Tone, string> = {
  bull: "border-bull/40 bg-bull/15 text-bull",
  bear: "border-bear/40 bg-bear/15 text-bear",
  warn: "border-warn/40 bg-warn/15 text-warn",
  info: "border-info/40 bg-info/15 text-info",
  muted: "border-edge bg-panel-2 text-muted",
  accent: "border-accent/50 bg-accent/15 text-accent",
};

const BAR_TONES: Record<Tone, string> = {
  bull: "bg-bull",
  bear: "bg-bear",
  warn: "bg-warn",
  info: "bg-info",
  muted: "bg-muted",
  accent: "bg-accent",
};

export function Pill({ tone = "muted", children, title, className = "" }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[11px] uppercase tracking-wide ${TONES[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Card({ title, actions, children, className = "", bodyClass = "p-3" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={`min-w-0 rounded-lg border border-edge bg-panel ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-edge px-3 py-2">
          <h2 className="font-display text-sm font-semibold tracking-wide text-text">{title}</h2>
          {actions && <div className="flex flex-wrap items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

type ButtonVariant = "default" | "primary" | "danger" | "ghost";
const BUTTONS: Record<ButtonVariant, string> = {
  default: "border-edge bg-panel-2 text-text hover:border-muted",
  primary: "border-accent bg-accent text-bg hover:brightness-110",
  danger: "border-bear/60 bg-bear/15 text-bear hover:bg-bear/25",
  ghost: "border-transparent text-muted hover:bg-panel-2 hover:text-text",
};

export function Button({ variant = "default", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded border px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTONS[variant]} ${className}`}
      {...rest}
    />
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`w-full rounded border border-edge bg-bg px-2 py-1.5 text-sm text-text outline-none placeholder:text-muted/70 focus:border-accent ${className}`} {...rest} />;
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={`w-full rounded border border-edge bg-bg px-2 py-1.5 text-sm text-text outline-none focus:border-accent ${className}`} {...rest}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children, className = "" }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 text-xs text-muted ${className}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="text-[11px] leading-snug text-muted/80">{hint}</span>}
    </label>
  );
}

export function Checkbox({ label, checked, onChange, disabled }: { label: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`inline-flex items-center gap-2 text-xs ${disabled ? "opacity-50" : "cursor-pointer"}`}>
      <input type="checkbox" className="accent-[var(--color-accent)]" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-edge border-t-accent" />
      {label}…
    </span>
  );
}

export function UnavailableNote({ info, title = "Data unavailable" }: { info?: Partial<Unavailable> | null; title?: string }) {
  return (
    <div className="rounded border border-dashed border-edge bg-bg/40 px-3 py-2 text-xs text-muted">
      <div className="font-mono uppercase tracking-wide text-warn">{title}</div>
      {info?.what && <div className="mt-0.5 text-text">{info.what}</div>}
      {info?.reason && <div>Reason: {info.reason}</div>}
      {info?.requirement && <div>Requires: {info.requirement}</div>}
      {info?.source && <div className="text-muted/70">Source: {info.source}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const detail = error instanceof ApiError ? error.detail : null;
  if (isUnavailable(detail)) return <UnavailableNote info={detail} />;
  const message = error instanceof Error ? error.message : describe(error);
  return <div className="rounded border border-bear/40 bg-bear/10 px-3 py-2 text-xs text-bear">{message}</div>;
}

export function Stat({ label, value, sub, tone }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: Tone }) {
  return (
    <div className="min-w-0 rounded border border-edge bg-bg/40 px-2.5 py-2">
      <div className="truncate text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`truncate font-mono text-sm ${tone ? TEXT_TONES[tone] : "text-text"}`}>{value}</div>
      {sub && <div className="truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function Meter({ value, max = 100, tone = "accent" }: { value: number | null | undefined; max?: number; tone?: Tone }) {
  const width = value === null || value === undefined ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-edge/60">
      <div className={`h-full rounded ${BAR_TONES[tone]}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="inline-flex rounded border border-edge bg-bg p-0.5" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === value}
          onClick={() => onChange(tab.id)}
          className={`rounded px-2.5 py-1 text-xs transition ${tab.id === value ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded border border-dashed border-edge px-3 py-6 text-center text-xs text-muted">{children}</div>;
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Table({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className={`w-full border-collapse text-xs [&_td]:border-t [&_td]:border-edge/60 [&_td]:px-2 [&_td]:py-1.5 [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-[11px] [&_th]:uppercase [&_th]:tracking-wide [&_th]:text-muted ${className}`}>
        {children}
      </table>
    </div>
  );
}
