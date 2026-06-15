import { useEffect, useMemo, useRef } from 'react';
import {
  AppStreamer,
  StreamType,
  type DirectConfig,
  type StreamEvent,
  type StreamProps,
} from '@nvidia/omniverse-webrtc-streaming-library';
import type { GrowthKpi, StreamConfig, StreamStatus } from '@/domain/types';

interface OmniverseViewportProps {
  stream: StreamConfig;
  status: StreamStatus;
  onStatusChange: (status: StreamStatus) => void;
  appliedBlueprintName: string | null;
  growthKpi?: GrowthKpi | null;
  autoConnect?: boolean;
  kiosk?: boolean;
}

const SIGNALING_PORT = 49100;
const CONNECT_TIMEOUT_MS = 15_000;
const RECONNECT_COOLDOWN_MS = 250;

const STATUS_COPY: Record<StreamStatus, string> = {
  idle: 'Stream idle - not connected to the NUC',
  connecting: 'Negotiating WebRTC session...',
  connected: 'Live twin stream',
  error: 'Connection failed - check the NUC endpoint',
};

function endpointLabel(stream: StreamConfig): string {
  return `webrtc://${stream.server}:${SIGNALING_PORT}`;
}

function stopStreamer() {
  try {
    AppStreamer.stop();
    // The NVIDIA sample clears this private singleton so a later reconnect
    // starts a fresh peer connection instead of reusing stale state.
    (AppStreamer as unknown as { _stream?: unknown })._stream = null;
  } catch (err) {
    console.warn('[omniverse-stream] stop failed', err);
  }
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function OmniverseViewport({
  stream,
  status,
  onStatusChange,
  appliedBlueprintName,
  growthKpi,
  autoConnect = false,
  kiosk = false,
}: OmniverseViewportProps) {
  const requested = useRef(false);
  const timeoutRef = useRef<number | null>(null);
  const live = status === 'connected';
  const busy = status === 'connecting';
  const endpoint = useMemo(() => endpointLabel(stream), [stream]);

  const clearConnectTimeout = () => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      requested.current = false;
      clearConnectTimeout();
      stopStreamer();
    };
  }, []);

  const connect = async () => {
    if (requested.current) return;
    requested.current = true;
    onStatusChange('connecting');

    // The Kit WebRTC server accepts a single active session. If the browser
    // refreshes, reconnects, or React remounts while the old peer connection is
    // still around, Kit can report NVST_R_BUSY and the UI can remain stuck in
    // "Connecting". Always start from a clean client singleton.
    clearConnectTimeout();
    stopStreamer();
    await delay(RECONNECT_COOLDOWN_MS);

    timeoutRef.current = window.setTimeout(() => {
      if (!requested.current) return;
      console.warn('[omniverse-stream] connect timed out; forcing cleanup');
      requested.current = false;
      stopStreamer();
      onStatusChange('error');
    }, CONNECT_TIMEOUT_MS);

    const streamConfig: DirectConfig = {
      videoElementId: 'remote-video',
      audioElementId: 'remote-audio',
      authenticate: true,
      // Keep retries conservative. Aggressive reconnects can leave the Kit
      // livestream plugin busy even after the UI gives up.
      maxReconnects: 3,
      signalingServer: stream.server,
      signalingPort: SIGNALING_PORT,
      mediaServer: stream.server,
      ...(typeof stream.mediaPort === 'number' ? { mediaPort: stream.mediaPort } : {}),
      nativeTouchEvents: true,
      width: stream.width,
      height: stream.height,
      fps: 60,
      onStart: (message: StreamEvent) => {
        if (message.action === 'start' && message.status === 'success') {
          clearConnectTimeout();
          onStatusChange('connected');
          const player = document.getElementById('remote-video') as HTMLVideoElement | null;
          if (player) {
            player.tabIndex = -1;
            player.playsInline = true;
            player.muted = true;
            void player.play();
          }
        }
        if (message.status === 'error') {
          console.error('[omniverse-stream] start failed', message);
          clearConnectTimeout();
          requested.current = false;
          stopStreamer();
          onStatusChange('error');
        }
      },
      onUpdate: (message: StreamEvent) => {
        if (message.status === 'error') {
          console.error('[omniverse-stream] update failed', message);
          clearConnectTimeout();
          requested.current = false;
          stopStreamer();
          onStatusChange('error');
        }
      },
      onCustomEvent: (message: unknown) => {
        console.info('[omniverse-stream] custom event', message);
      },
      onStop: (message: StreamEvent) => {
        console.info('[omniverse-stream] stopped', message);
        clearConnectTimeout();
        requested.current = false;
        onStatusChange('idle');
      },
      onTerminate: (message: StreamEvent) => {
        console.info('[omniverse-stream] terminated', message);
        clearConnectTimeout();
        requested.current = false;
        onStatusChange('idle');
      },
    };

    try {
      const streamProps: StreamProps = {
        streamConfig,
        streamSource: StreamType.DIRECT,
      };
      await AppStreamer.connect(streamProps);
    } catch (err) {
      console.error('[omniverse-stream] connect failed', err);
      clearConnectTimeout();
      requested.current = false;
      stopStreamer();
      onStatusChange('error');
    }
  };

  useEffect(() => {
    if (!autoConnect || requested.current || status !== 'idle') return;
    void connect();
  }, [autoConnect, status]);

  const disconnect = () => {
    requested.current = false;
    clearConnectTimeout();
    stopStreamer();
    onStatusChange('idle');
  };

  return (
    <div className={`viewer${kiosk ? ' viewer--kiosk' : ''}`}>
      <div className="viewer__bar">
        <span className={`viewer__badge viewer__badge--${status}`}>
          <i aria-hidden /> {STATUS_COPY[status]}
        </span>
        <span className="viewer__source">
          {stream.source.toUpperCase()} · {stream.width}x{stream.height}
        </span>
      </div>

      <div className={`viewer__stage viewer__stage--${status}`}>
        <div id="main-div" className="viewer__video" tabIndex={0}>
          <video id="remote-video" className="viewer__video" tabIndex={-1} playsInline muted autoPlay />
          <audio id="remote-audio" muted />
        </div>

        {live ? (
          <div className="viewer__overlay viewer__overlay--live">
            <span className="viewer__tag">
              {appliedBlueprintName
                ? `Rendering · ${appliedBlueprintName}`
                : 'Rendering baseline twin'}
            </span>
            {growthKpi ? (
              <span className="viewer__tag viewer__tag--growth">
                Growth {growthKpi.healthScore}/100 · Maturity {growthKpi.fruitMaturityPercent}% · Harvest {growthKpi.harvestReadinessPercent}%
              </span>
            ) : null}
          </div>
        ) : (
          <div className="viewer__overlay viewer__overlay--cta">
            <div className="viewer__glyph" aria-hidden>
              ◴
            </div>
            <p className="viewer__headline">
              {busy ? 'Connecting to the twin...' : status === 'error' ? 'Stream connection failed' : 'Omniverse twin stream'}
            </p>
            <p className="viewer__hint">
              Direct WebRTC to <code>{stream.server}</code> · not proxied
            </p>
            {kiosk ? (
              <button
                type="button"
                className="btn btn--primary viewer__connect-cta"
                onClick={connect}
                disabled={busy}
              >
                {busy ? 'Connecting...' : status === 'error' ? 'Retry stream' : 'Connect stream'}
              </button>
            ) : null}
          </div>
        )}
      </div>

      <div className="viewer__foot">
        <code className="viewer__endpoint" title={endpoint}>
          {endpoint}
        </code>
        <div className="viewer__actions">
          {live ? (
            <button type="button" className="btn btn--ghost" onClick={disconnect}>
              Disconnect
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--primary"
              onClick={connect}
              disabled={busy}
            >
              {busy ? 'Connecting...' : 'Connect stream'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
