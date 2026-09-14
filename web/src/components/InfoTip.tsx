import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { HELP, type HelpTopic } from "../lib/help";

/** A small (i) button that opens a plain-language explanation. Closes on outside click or Escape. */
export default function InfoTip({ title, children, align = "left" }: { title: string; children: ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const box = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent | TouchEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("touchstart", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("touchstart", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <span ref={box} className="relative inline-flex align-middle font-body normal-case tracking-normal">
      <button
        type="button"
        aria-label={`Explain: ${title}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border font-serif text-[10px] font-bold italic leading-none transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info ${open ? "border-info bg-info text-bg" : "border-info/60 text-info hover:bg-info/15"}`}
      >
        i
      </button>
      {open && (
        <span
          id={id}
          role="dialog"
          aria-label={title}
          className={`absolute top-6 z-50 block w-72 max-w-[80vw] rounded-lg border border-edge bg-panel p-3 text-left text-xs font-normal leading-relaxed shadow-2xl ${align === "right" ? "right-0" : "left-0"}`}
        >
          <span className="mb-1 block font-display text-[13px] font-semibold text-text">{title}</span>
          <span className="block text-muted">{children}</span>
        </span>
      )}
    </span>
  );
}

export function Help({ topic, align }: { topic: HelpTopic; align?: "left" | "right" }) {
  const entry = HELP[topic];
  return (
    <InfoTip title={entry.title} align={align}>
      {entry.body}
    </InfoTip>
  );
}
