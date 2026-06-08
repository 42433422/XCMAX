import { ref } from 'vue';

const STORAGE_KEY = 'xcagi.im.soundMode';

export type ImSoundMode = 'all' | 'notify-only' | 'mute';

function readMode(): ImSoundMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'mute' || v === 'notify-only' || v === 'all') return v;
  } catch {
    /* ignore */
  }
  return 'all';
}

const mode = ref<ImSoundMode>(readMode());

let inAudio: HTMLAudioElement | null = null;
let sendAudio: HTMLAudioElement | null = null;

function getAudio(src: string): HTMLAudioElement {
  const a = new Audio(src);
  a.preload = 'auto';
  return a;
}

function beepFallback(kind: 'in' | 'out'): void {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = kind === 'in' ? 880 : 660;
    gain.gain.value = 0.08;
    osc.start();
    osc.stop(ctx.currentTime + 0.12);
    osc.onended = () => void ctx.close();
  } catch {
    /* 无 WebAudio */
  }
}

function playFile(kind: 'in' | 'out'): void {
  if (mode.value === 'mute') return;
  const src = kind === 'in' ? '/sounds/im-in.wav' : '/sounds/im-send.wav';
  const cache = kind === 'in' ? inAudio : sendAudio;
  const audio = cache ?? getAudio(src);
  if (kind === 'in') inAudio = audio;
  else sendAudio = audio;
  audio.currentTime = 0;
  const p = audio.play();
  if (p && typeof p.catch === 'function') {
    p.catch(() => beepFallback(kind));
  }
}

async function ensureNotificationPermission(): Promise<boolean> {
  if (typeof Notification === 'undefined') return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try {
    const result = await Notification.requestPermission();
    return result === 'granted';
  } catch {
    return false;
  }
}

async function showBrowserNotification(title: string, body: string): Promise<void> {
  if (typeof Notification === 'undefined') return;
  const ok = await ensureNotificationPermission();
  if (!ok) return;
  try {
    const n = new Notification(title, { body, tag: 'xcagi-im' });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    /* ignore */
  }
}

export function useImSounds() {
  function setMode(next: ImSoundMode): void {
    mode.value = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }

  async function playIncoming(preview?: string): Promise<void> {
    if (mode.value === 'mute') return;
    if (mode.value === 'notify-only') {
      await showBrowserNotification('新消息', preview || '您有一条新消息');
      if (window.xcagiDesktop?.showNotification) {
        await window.xcagiDesktop.showNotification('新消息', preview || '您有一条新消息');
      }
      return;
    }
    playFile('in');
  }

  function playOutgoing(): void {
    if (mode.value === 'mute' || mode.value === 'notify-only') return;
    playFile('out');
  }

  return { mode, setMode, playIncoming, playOutgoing };
}
