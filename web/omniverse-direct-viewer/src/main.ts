import './style.css';
import {
  AppStreamer,
  StreamType,
  type DirectConfig,
  type StreamEvent,
  type StreamProps,
} from '@nvidia/omniverse-webrtc-streaming-library';

type ViewerState = 'idle' | 'connecting' | 'connected' | 'error';

interface ViewerConfig {
  stream: {
    server: string;
    signalingPort?: number;
    mediaPort?: number;
    width?: number;
    height?: number;
    fps?: number;
    authenticate?: boolean;
    fullscreenOnConnect?: boolean;
    maxReconnects?: number;
    connectTimeoutMs?: number;
  };
}

const DEFAULT_CONFIG: ViewerConfig = {
  stream: {
    server: '10.32.214.23',
    signalingPort: 49100,
    mediaPort: 47998,
    width: 1920,
    height: 1080,
    fps: 60,
    authenticate: true,
    fullscreenOnConnect: true,
    maxReconnects: 3,
    connectTimeoutMs: 15_000,
  },
};

const overlay = document.getElementById('overlay') as HTMLDivElement;
const endpoint = document.getElementById('endpoint') as HTMLParagraphElement;
const statusPill = document.getElementById('status-pill') as HTMLParagraphElement;
const connectButton = document.getElementById('connect-button') as HTMLButtonElement;
const disconnectButton = document.getElementById('disconnect-button') as HTMLButtonElement;

let config = DEFAULT_CONFIG;
let requested = false;
let connectTimer: number | undefined;

function mergeConfig(input: Partial<ViewerConfig>): ViewerConfig {
  return {
    stream: {
      ...DEFAULT_CONFIG.stream,
      ...(input.stream ?? {}),
    },
  };
}

async function loadConfig() {
  try {
    const response = await fetch('/config.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    config = mergeConfig(await response.json());
  } catch (error) {
    console.warn('[direct-viewer] using default config', error);
    config = DEFAULT_CONFIG;
  }
  endpoint.textContent = `webrtc://${config.stream.server}:${config.stream.signalingPort ?? 49100} · media ${config.stream.mediaPort ?? 47998}/UDP`;
}

function stateLabel(state: ViewerState): string {
  return state === 'idle'
    ? 'STREAM IDLE'
    : state === 'connecting'
      ? 'CONNECTING'
      : state === 'connected'
        ? 'CONNECTED'
        : 'ERROR';
}

function setState(state: ViewerState, text?: string) {
  document.body.classList.toggle('connected', state === 'connected');
  overlay.classList.toggle('hidden', state === 'connected');
  statusPill.className = `status-pill status-pill--${state}`;
  statusPill.textContent = stateLabel(state);
  connectButton.disabled = state === 'connecting';
  connectButton.textContent = state === 'error' ? 'Retry Stream' : state === 'connecting' ? 'Connecting…' : 'Connect Stream';
  disconnectButton.classList.toggle('hidden', state !== 'connected' && state !== 'connecting');
  if (text) {
    endpoint.textContent = text;
  } else if (state !== 'error') {
    endpoint.textContent = `webrtc://${config.stream.server}:${config.stream.signalingPort ?? 49100} · media ${config.stream.mediaPort ?? 47998}/UDP`;
  }
}

function clearConnectTimer() {
  if (connectTimer !== undefined) {
    window.clearTimeout(connectTimer);
    connectTimer = undefined;
  }
}

function stopStreamer() {
  clearConnectTimer();
  try {
    AppStreamer.stop();
    // Match NVIDIA sample behavior used by the main SmartFarm portal: clear the
    // private singleton so retry starts with a fresh RTCPeerConnection.
    (AppStreamer as unknown as { _stream?: unknown })._stream = null;
  } catch (error) {
    console.warn('[direct-viewer] stop failed', error);
  }
}

async function enterFullscreen() {
  if (!config.stream.fullscreenOnConnect || document.fullscreenElement) return;
  try {
    await document.documentElement.requestFullscreen();
  } catch (error) {
    console.info('[direct-viewer] fullscreen request skipped', error);
  }
}

async function connect() {
  if (requested) return;
  requested = true;
  setState('connecting');
  await enterFullscreen();
  stopStreamer();

  connectTimer = window.setTimeout(() => {
    if (!requested) return;
    requested = false;
    stopStreamer();
    setState('error', `연결 시간이 초과되었습니다: ${config.stream.server}:${config.stream.signalingPort ?? 49100}`);
  }, config.stream.connectTimeoutMs ?? 15_000);

  const streamConfig: DirectConfig = {
    videoElementId: 'remote-video',
    audioElementId: 'remote-audio',
    authenticate: config.stream.authenticate ?? true,
    maxReconnects: config.stream.maxReconnects ?? 3,
    signalingServer: config.stream.server,
    signalingPort: config.stream.signalingPort ?? 49100,
    mediaServer: config.stream.server,
    ...(typeof config.stream.mediaPort === 'number' ? { mediaPort: config.stream.mediaPort } : {}),
    nativeTouchEvents: true,
    width: config.stream.width ?? 1920,
    height: config.stream.height ?? 1080,
    fps: config.stream.fps ?? 60,
    onStart: (event: StreamEvent) => {
      console.info('[direct-viewer] start', event);
      if (event.action === 'start' && event.status === 'success') {
        clearConnectTimer();
        setState('connected');
        const video = document.getElementById('remote-video') as HTMLVideoElement | null;
        if (video) {
          video.tabIndex = -1;
          video.playsInline = true;
          video.muted = true;
          void video.play();
        }
      }
      if (event.status === 'error') {
        requested = false;
        stopStreamer();
        setState('error', 'Omniverse WebRTC start event returned an error.');
      }
    },
    onUpdate: (event: StreamEvent) => {
      if (event.status === 'error') {
        console.error('[direct-viewer] update error', event);
        requested = false;
        stopStreamer();
        setState('error', 'Omniverse WebRTC update event returned an error.');
      }
    },
    onStop: (event: StreamEvent) => {
      console.info('[direct-viewer] stopped', event);
      requested = false;
      setState('idle');
    },
    onTerminate: (event: StreamEvent) => {
      console.info('[direct-viewer] terminated', event);
      requested = false;
      setState('idle');
    },
    onCustomEvent: (event: unknown) => console.info('[direct-viewer] custom event', event),
  };

  try {
    const streamProps: StreamProps = {
      streamSource: StreamType.DIRECT,
      streamConfig,
    };
    await AppStreamer.connect(streamProps);
  } catch (error) {
    console.error('[direct-viewer] connect failed', error);
    requested = false;
    stopStreamer();
    setState('error', error instanceof Error ? error.message : 'Unknown WebRTC connection failure.');
  }
}

function disconnect() {
  requested = false;
  stopStreamer();
  setState('idle');
}

connectButton.addEventListener('click', () => void connect());
disconnectButton.addEventListener('click', disconnect);
window.addEventListener('beforeunload', stopStreamer);

void loadConfig().then(() => setState('idle'));
