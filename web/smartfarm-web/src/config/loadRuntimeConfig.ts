import type { RuntimeConfig } from '@/domain/types';

/**
 * Runtime configuration loader.
 *
 * `config.json` is served as a static file from the deployed container (it is
 * NOT bundled into the JS). This lets ops repoint the portal at a different NUC
 * stream endpoint per environment — in K8S, mount a ConfigMap over
 * `/usr/share/nginx/html/config.json` — without rebuilding the image.
 *
 * The browser connects DIRECTLY to the NUC WebRTC endpoint. Kit services live
 * on `stream.streamUrl`, while local livestream signaling uses port 49100.
 * WebRTC media is never routed through K8S ingress.
 */

/** Safe default used in dev or if config.json is missing/unreachable. */
export const DEFAULT_CONFIG: RuntimeConfig = {
  facilityId: 'smartfarm-v1',
  facilityName: 'Reference Greenhouse (dev)',
  apiBaseUrl: '/api',
  stream: {
    source: 'local',
    server: '127.0.0.1',
    streamUrl: 'http://127.0.0.1:8011',
    signalingPath: '',
    width: 1920,
    height: 1080,
  },
};

const CONFIG_URL = `${import.meta.env.BASE_URL}config.json`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Shallow validation + merge over defaults so a partial config never crashes the UI. */
function normalize(raw: unknown): RuntimeConfig {
  if (!isRecord(raw)) return DEFAULT_CONFIG;
  const stream = isRecord(raw.stream) ? raw.stream : {};
  const d = DEFAULT_CONFIG.stream;
  return {
    facilityId: typeof raw.facilityId === 'string' ? raw.facilityId : DEFAULT_CONFIG.facilityId,
    facilityName:
      typeof raw.facilityName === 'string' ? raw.facilityName : DEFAULT_CONFIG.facilityName,
    apiBaseUrl: typeof raw.apiBaseUrl === 'string' ? raw.apiBaseUrl : DEFAULT_CONFIG.apiBaseUrl,
    stream: {
      source:
        stream.source === 'gfn' || stream.source === 'nvcf' || stream.source === 'local'
          ? stream.source
          : d.source,
      server: typeof stream.server === 'string' ? stream.server : d.server,
      streamUrl: typeof stream.streamUrl === 'string' ? stream.streamUrl : d.streamUrl,
      signalingPath:
        typeof stream.signalingPath === 'string' ? stream.signalingPath : d.signalingPath,
      mediaPort: typeof stream.mediaPort === 'number' ? stream.mediaPort : undefined,
      width: typeof stream.width === 'number' ? stream.width : d.width,
      height: typeof stream.height === 'number' ? stream.height : d.height,
    },
  };
}

export async function loadRuntimeConfig(): Promise<RuntimeConfig> {
  try {
    const res = await fetch(CONFIG_URL, { cache: 'no-store' });
    if (!res.ok) {
      console.warn(`[config] ${CONFIG_URL} -> ${res.status}; using defaults`);
      return DEFAULT_CONFIG;
    }
    return normalize(await res.json());
  } catch (err) {
    console.warn('[config] failed to load config.json; using defaults', err);
    return DEFAULT_CONFIG;
  }
}

/** Legacy HTTP-style label for older configs; local WebRTC uses port 49100. */
export function signalingUrl(config: RuntimeConfig): string {
  const base = config.stream.streamUrl.replace(/\/+$/, '');
  const path = config.stream.signalingPath.startsWith('/')
    ? config.stream.signalingPath
    : `/${config.stream.signalingPath}`;
  return `${base}${path}`;
}
