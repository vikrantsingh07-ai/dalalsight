export interface VoiceOptions {
  voiceName?: string;
  lang?: string;
  rate?: number;
  pitch?: number;
}

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speak(text: string, options: VoiceOptions = {}): boolean {
  if (!canSpeak()) return false;
  const utterance = new SpeechSynthesisUtterance(text.replace(/[*#_`>|]/g, " "));
  utterance.lang = options.lang || "en-IN";
  utterance.rate = options.rate ?? 1;
  utterance.pitch = options.pitch ?? 1;
  const voice = window.speechSynthesis.getVoices().find((v) => v.name === options.voiceName);
  if (voice) utterance.voice = voice;
  window.speechSynthesis.speak(utterance);
  return true;
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

export function listVoices(): SpeechSynthesisVoice[] {
  return canSpeak() ? window.speechSynthesis.getVoices() : [];
}

interface RecognitionAlternative {
  transcript: string;
}

interface RecognitionResult {
  readonly length: number;
  readonly isFinal: boolean;
  [index: number]: RecognitionAlternative;
}

export interface RecognitionEvent {
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
}

export interface Recognizer {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognizerConstructor = new () => Recognizer;

export function createRecognizer(lang = "en-IN"): Recognizer | null {
  const scope = window as unknown as { SpeechRecognition?: RecognizerConstructor; webkitSpeechRecognition?: RecognizerConstructor };
  const Ctor = scope.SpeechRecognition ?? scope.webkitSpeechRecognition;
  if (!Ctor) return null;
  const recognizer = new Ctor();
  recognizer.lang = lang;
  recognizer.interimResults = true;
  recognizer.continuous = false;
  return recognizer;
}

let audioContext: AudioContext | null = null;

export function beep(priority = "HIGH"): void {
  try {
    const ctx = audioContext ?? new AudioContext();
    audioContext = ctx;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = priority === "CRITICAL" ? 1046 : 784;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    oscillator.connect(gain).connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.4);
  } catch {
    /* audio is blocked until the user interacts with the page */
  }
}
