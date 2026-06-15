import type { CropState, GrowthKpi, PlanningRun, RuntimeConfig } from '@/domain/types';

export interface TwinSensorState {
  scenarioSeed: string;
  twinDay: number;
  cropStage: string;
  growthIndex: number;
  dliMolM2Day: number;
  soilMoisturePercent: number;
  humidityPercent: number;
  temperatureC: number;
  co2Ppm: number;
  diseaseRisk: string;
}

export interface TwinStateResponse {
  ok: boolean;
  message: string;
  sceneMode: string;
  hasStage: boolean;
  smartFarmPath: string;
  appliedBlueprintId: string | null;
  sensorState: TwinSensorState;
  cropState?: CropState;
  growthKpi?: GrowthKpi;
  actuatorState?: {
    ledIntensityPercent: number;
    photoperiodHours: number;
    waterValveOpen: boolean;
    irrigationPulsesPerDay: number;
    fanDutyPercent: number;
    co2Ppm: number;
  };
  result?: {
    blueprintId: string;
    blueprintName: string;
    expectedShipment: string;
    yieldScore: number;
    opex: string;
  };
  recommendation?: {
    recommendedBlueprintId: string | null;
    rationale: string;
    scores: Array<{
      blueprintId: string;
      blueprintName: string;
      score: number;
      rationale: string;
    }>;
  };
  planningRun?: PlanningRun | null;
}

export interface PlanningRunResponse {
  ok: boolean;
  message: string;
  planningRun?: PlanningRun | null;
}

function normalizeBaseUrl(config: RuntimeConfig): string {
  if (config.apiBaseUrl) {
    return config.apiBaseUrl.replace(/\/+$/, '');
  }

  return `${config.stream.streamUrl.replace(/\/+$/, '')}/smartfarm`;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`);
  }
  return (await res.json()) as T;
}

function assertTwinOk(state: TwinStateResponse): TwinStateResponse {
  if (state.ok === false) {
    throw new Error(state.message || 'Kit twin rejected the command.');
  }
  return state;
}

function assertPlanningOk(state: PlanningRunResponse): PlanningRunResponse {
  if (state.ok === false) {
    throw new Error(state.message || 'Planning service rejected the command.');
  }
  return state;
}

export function createSmartfarmApi(config: RuntimeConfig) {
  const baseUrl = normalizeBaseUrl(config);
  return {
    baseUrl,
    getState: () =>
      requestJson<TwinStateResponse>(`${baseUrl}/state`, { cache: 'no-store' }).then(assertTwinOk),
    getLatestPlanning: () =>
      requestJson<PlanningRunResponse>(`${baseUrl}/planning/latest`, { cache: 'no-store' }).then(
        assertPlanningOk,
      ),
    runDailyPlanning: () =>
      requestJson<TwinStateResponse>(`${baseUrl}/planning/run`, {
        method: 'POST',
        body: JSON.stringify({ reason: 'operator' }),
      }).then(assertTwinOk),
    createMatureScene: () =>
      requestJson<TwinStateResponse>(`${baseUrl}/scene/mature`, {
        method: 'POST',
        body: '{}',
      }).then(assertTwinOk),
    createGrowthSimulation: () =>
      requestJson<TwinStateResponse>(`${baseUrl}/scene/growth`, {
        method: 'POST',
        body: '{}',
      }).then(assertTwinOk),
    resetGrowthTimeline: () =>
      requestJson<TwinStateResponse>(`${baseUrl}/scene/reset`, {
        method: 'POST',
        body: '{}',
      }).then(assertTwinOk),
    applyBlueprint: (blueprintId: string) =>
      requestJson<TwinStateResponse>(`${baseUrl}/blueprint/apply`, {
        method: 'POST',
        body: JSON.stringify({ blueprintId }),
      }).then(assertTwinOk),
  };
}
