import { useEffect, useRef, useState } from "react";
import { useApp } from "../context/AppContext";
import { get, post } from "../lib/api";
import { istTime } from "../lib/format";
import { createRecognizer, stopSpeaking, type Recognizer } from "../lib/voice";
import { Button, Checkbox, ErrorNote, Pill, Spinner } from "./ui";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  source?: string;
  ts: string;
  context?: { symbol?: string; timeframe?: string; strike?: number | null; option_type?: string | null };
}

interface HistoryRow {
  ts: string;
  role: string;
  content: string;
  payload: { source?: string; context?: ChatMessage["context"] } | null;
}

interface ChatReply {
  answer: string;
  source: string;
  context: ChatMessage["context"];
  ts: string;
}

const SUGGESTIONS = [
  "What is the setup right now?",
  "Where are support and resistance?",
  "What does the option chain say?",
  "Is there a trade or should I wait for confirmation?",
];

function sessionId(): string {
  try {
    let id = localStorage.getItem("cc_chat_session");
    if (!id) {
      id = `s${Date.now().toString(36)}`;
      localStorage.setItem("cc_chat_session", id);
    }
    return id;
  } catch {
    return "default";
  }
}

function spokenSummary(answer: string): string {
  const direct = answer.split(/\n\s*2\.\s/)[0];
  return direct.replace(/^1\.\s*Direct answer\s*/i, "").slice(0, 400);
}

export default function AssistantPanel() {
  const { symbol, timeframe, setAssistantOpen, say, voiceOn } = useApp();
  const [session] = useState(sessionId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [listening, setListening] = useState(false);
  const [useAi, setUseAi] = useState(true);
  const [speakReplies, setSpeakReplies] = useState(true);
  const recognizer = useRef<Recognizer | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    get<HistoryRow[]>(`/api/assistant/history?session=${session}`)
      .then((rows) =>
        setMessages(
          rows.map((row) => ({
            role: row.role === "user" ? "user" : "assistant",
            content: row.content,
            source: row.payload?.source,
            context: row.payload?.context,
            ts: row.ts,
          })),
        ),
      )
      .catch(() => undefined);
  }, [session]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setMessages((list) => [...list, { role: "user", content: trimmed, ts: new Date().toISOString() }]);
    setText("");
    setBusy(true);
    setError(null);
    try {
      const reply = await post<ChatReply>("/api/assistant/chat", { question: trimmed, context: { symbol, timeframe }, session, use_ai: useAi });
      setMessages((list) => [...list, { role: "assistant", content: reply.answer, source: reply.source, context: reply.context, ts: reply.ts }]);
      if (speakReplies && voiceOn) say(spokenSummary(reply.answer));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function toggleMic() {
    if (listening) {
      recognizer.current?.stop();
      return;
    }
    const instance = createRecognizer("en-IN");
    if (!instance) {
      setError(new Error("Speech recognition is not supported in this browser. Use Google Chrome."));
      return;
    }
    stopSpeaking();
    recognizer.current = instance;
    let finalText = "";
    instance.onresult = (event) => {
      let interim = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      setText(finalText + interim);
    };
    instance.onerror = (event) => setError(new Error(`Voice input: ${event.error}`));
    instance.onend = () => {
      setListening(false);
      if (finalText.trim()) void send(finalText);
    };
    setListening(true);
    instance.start();
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] flex-col border-l border-edge bg-panel shadow-2xl xl:static xl:z-auto xl:shadow-none" aria-label="Trading assistant">
      <header className="flex items-center justify-between gap-2 border-b border-edge px-3 py-2">
        <div>
          <div className="font-display text-sm font-semibold">Trading assistant</div>
          <div className="text-[11px] text-muted">
            Context: <span className="font-mono text-text">{symbol}</span> · {timeframe} · answers only from live engine data
          </div>
        </div>
        <Button variant="ghost" onClick={() => setAssistantOpen(false)} aria-label="Close assistant">
          ✕
        </Button>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted">Ask about the current chart, levels, option chain or a specific strike (for example “23500 CE”). Speak with the mic button.</p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <Button key={suggestion} onClick={() => void send(suggestion)}>
                  {suggestion}
                </Button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) => (
          <div key={`${message.ts}-${index}`} className={message.role === "user" ? "ml-8" : "mr-2"}>
            <div className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${message.role === "user" ? "border-accent/40 bg-accent/10" : "border-edge bg-bg/50"}`}>
              <div className="whitespace-pre-wrap break-words">{message.content}</div>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted">
              <span>{istTime(message.ts, { seconds: true })}</span>
              {message.context?.symbol && message.role === "assistant" && (
                <span className="font-mono">
                  {message.context.symbol} {message.context.timeframe}
                  {message.context.strike ? ` · ${message.context.strike} ${message.context.option_type ?? ""}` : ""}
                </span>
              )}
              {message.source && (
                <Pill tone={message.source.startsWith("ai:") ? "accent" : "muted"} title={message.source}>
                  {message.source.startsWith("ai:") ? `AI · ${message.source.slice(3).split("/").pop()}` : "engine"}
                </Pill>
              )}
            </div>
          </div>
        ))}
        {busy && <Spinner label="Analysing live data" />}
        <ErrorNote error={error} />
        <div ref={bottom} />
      </div>
      <form
        className="space-y-2 border-t border-edge p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void send(text);
        }}
      >
        <textarea
          className="h-20 w-full resize-none rounded border border-edge bg-bg px-2 py-1.5 text-sm text-text outline-none focus:border-accent"
          placeholder={listening ? "Listening…" : "Ask the assistant"}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(text);
            }
          }}
          aria-label="Question"
          maxLength={1000}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-3">
            <Checkbox label="Use AI model" checked={useAi} onChange={setUseAi} />
            <Checkbox label="Speak replies" checked={speakReplies} onChange={setSpeakReplies} />
          </div>
          <div className="flex gap-1.5">
            <Button onClick={toggleMic} variant={listening ? "danger" : "default"} aria-pressed={listening}>
              {listening ? "Stop mic" : "Mic"}
            </Button>
            <Button type="submit" variant="primary" disabled={busy || !text.trim()}>
              Send
            </Button>
          </div>
        </div>
      </form>
    </aside>
  );
}
