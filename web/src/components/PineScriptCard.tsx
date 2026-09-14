import { useState } from "react";
import { api } from "../lib/api";
import { Button, Card, ErrorNote } from "./ui";

const STEPS = [
  "In your TradingView app (or tradingview.com), open a chart and the Pine Editor panel.",
  "Click Open → New indicator, select everything (Ctrl+A), paste the copied script (Ctrl+V), then Save and Add to chart.",
  "For the volume and VWAP components on indices, use the futures chart (e.g. NSE:NIFTY1!, NSE:BANKNIFTY1!): spot indices carry no volume.",
  "For alerts: Alerts → Create → Condition “DalalSight” → pick e.g. “DalalSight: Bullish setup” → Trigger “Once per bar close”.",
  "Weights and thresholds are in the indicator's settings (gear icon); defaults match DalalSight.",
];

export default function PineScriptCard() {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function copy() {
    setError(null);
    try {
      const script = await api<string>("/api/tradingview/pine");
      await navigator.clipboard.writeText(script);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 4000);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Card
      title="DalalSight signals inside TradingView"
      actions={
        <Button variant="primary" onClick={() => void copy()}>
          {copied ? "Copied ✓" : "Copy Pine Script"}
        </Button>
      }
    >
      <ol className="list-decimal space-y-1 pl-4 text-xs leading-relaxed">
        {STEPS.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="mt-2 text-[11px] leading-snug text-muted">
        The indicator runs the same signal model (EMA, VWAP, RSI, MACD, Supertrend, support/resistance, regime, weighted score, entry/stop/targets, NO TRADE label) on TradingView&apos;s own data, so its numbers can differ slightly from the panels here, which use the NSE/Yahoo feed. Options positioning is not available in Pine, so that weight counts as unavailable there. File: <span className="font-mono">dalalsight/tradingview/dalalsight_signal_engine.pine</span>
      </p>
      <div className="mt-2">
        <ErrorNote error={error} />
      </div>
    </Card>
  );
}
