/**
 * Domain contracts for the Smart Farm Digital Twin portal.
 *
 * These mirror the data models in:
 *   docs/Progess/2026-05-26-web-portal-design.md
 *   docs/Progess/2026-05-24-blueprint-scenario-architecture.md
 *
 * The portal is a prototype shell: values are deterministic mocks. When the
 * Service API and Kit WebRTC bridge land, only the data *sources* change — these
 * types remain the contract between the UI, the API, and the Omniverse twin.
 */

// ---------------------------------------------------------------------------
// Runtime configuration (loaded from /config.json at startup, never bundled)
// ---------------------------------------------------------------------------

/** Where the WebRTC stream originates. POC v1 targets `local` (NUC node). */
export type StreamSource = 'local' | 'gfn' | 'nvcf';

/**
 * Omniverse stream endpoint. The browser connects DIRECTLY to the NUC using
 * these values — WebRTC media is never proxied through the K8S ingress.
 */
export interface StreamConfig {
  source: StreamSource;
  /** NUC host or IP running USD Composer / Kit App with the streaming layer. */
  server: string;
  /** Base URL of the NUC stream endpoint, e.g. "http://10.34.20.10:8011". */
  streamUrl: string;
  /** WebRTC signaling path appended to `streamUrl`. */
  signalingPath: string;
  /** Optional media/UDP port hint for the WebRTC client. */
  mediaPort?: number;
  width: number;
  height: number;
}

export interface RuntimeConfig {
  facilityId: string;
  facilityName: string;
  /** Base URL of the Service API (mock for now). Reachable via K8S ingress. */
  apiBaseUrl: string;
  /** Optional startup layout. Use kiosk for stream-only demo mode. */
  defaultView?: 'dashboard' | 'kiosk';
  stream: StreamConfig;
}

// ---------------------------------------------------------------------------
// Omniverse viewer state
// ---------------------------------------------------------------------------

export type StreamStatus = 'idle' | 'connecting' | 'connected' | 'error';

// ---------------------------------------------------------------------------
// Virtual sensors (5 axes)
// ---------------------------------------------------------------------------

export type SensorId = 'dli' | 'soil_moisture' | 'humidity' | 'temperature' | 'co2';

/** Operational health derived from where a reading sits vs its optimal band. */
export type SensorStatus = 'ok' | 'warning' | 'critical';

export interface SensorReading {
  id: SensorId;
  label: string;
  /** Short tag rendered on the gauge, e.g. "DLI", "RH". */
  short: string;
  value: number;
  unit: string;
  status: SensorStatus;
  /** Optimal operating band — drives the gauge fill colour. */
  optimalMin: number;
  optimalMax: number;
  /** Display floor/ceiling for the gauge track. */
  rangeMin: number;
  rangeMax: number;
  /** Actuator this sensor primarily drives. */
  linkedActuator: ActuatorId;
}

export interface CropState {
  day: number;
  vegetativeGrowth: number;
  flowering: number;
  fruitSet: number;
  fruitMaturity: number;
  diseasePressure: number;
  estimatedYield: number;
}

export interface GrowthKpi {
  /** 0-100 model estimate combining crop phenology, stress and disease pressure. */
  healthScore: number;
  stage: string;
  fruitMaturityPercent: number;
  harvestReadinessPercent: number;
  expectedShip: string;
  diseaseRisk: DiseaseRisk | string;
  mainLimitingFactor: string;
  /** Current POC source quality. Upgrade to observed/model-assimilated later. */
  confidence: 'model-estimated' | string;
  basis: string;
  evidence: string[];
}

// ---------------------------------------------------------------------------
// Actuators (3 control axes)
// ---------------------------------------------------------------------------

export type ActuatorId = 'led' | 'water_valve' | 'fan';

export type ActuatorMode = 'off' | 'on' | 'auto';

export interface ActuatorState {
  id: ActuatorId;
  label: string;
  mode: ActuatorMode;
  /** Primary level: LED intensity %, valve flow %, fan duty %. */
  level: number;
  unit: string;
  /** Secondary detail, e.g. "16h photoperiod", "3 pulses/day". */
  detail: string;
}

// ---------------------------------------------------------------------------
// Blueprints (candidate operating prescriptions)
// ---------------------------------------------------------------------------

export type BlueprintKind = 'baseline' | 'low_cost' | 'early_shipment' | 'disease_safe';

export type DiseaseRisk = 'high' | 'controlled' | 'low';

/** Target sensor state the Kit twin should render once the blueprint applies. */
export interface SensorTarget {
  dliMolM2Day: number;
  soilMoisturePercent: number;
  humidityPercent: number;
  temperatureC: number;
  co2Ppm: number;
}

/** Target actuator state pushed to the Kit twin via `smartfarm.apply_blueprint`. */
export interface ActuatorTarget {
  ledIntensityPercent: number;
  photoperiodHours: number;
  waterValveOpen: boolean;
  irrigationPulsesPerDay: number;
  fanDutyPercent: number;
}

/**
 * Forecast over the blueprint horizon. NOTE: per the architecture doc these are
 * computed by the Service API, NOT the Kit twin. The twin only renders state.
 */
export interface BlueprintPrediction {
  shipmentDate: string;
  yieldScore: number;
  opexDeltaPercent: number;
  diseaseRisk: DiseaseRisk;
  riskNote: string;
}

export interface Blueprint {
  id: string;
  kind: BlueprintKind;
  name: string;
  /** One-line operator-facing rationale. */
  tagline: string;
  horizonDays: number;
  targetShipmentDate: string;
  sensorTarget: SensorTarget;
  actuatorTarget: ActuatorTarget;
  predicted: BlueprintPrediction;
  /** True for the candidate the scoring engine currently recommends. */
  recommended: boolean;
  /** Optional scoring/rationale returned by the daily planning service. */
  score?: number;
  rationale?: string;
  simulation?: {
    startDay: number;
    harvestDay: number;
    maxHorizonDays: number;
    dailyStates: Array<{
      day: number;
      fruitMaturity: number;
      diseasePressure: number;
      estimatedYield: number;
    }>;
    finalCropState: CropState;
  };
}

export interface PlanningRun {
  runId: string;
  createdAt: string;
  reason: string;
  currentDay: number;
  source: string;
  gemmaRagStatus: string;
  currentSensorState: {
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
  };
  currentCropState: CropState;
  recommendedBlueprintId: string | null;
  candidates: Blueprint[];
  decisionRationale: string;
}

// ---------------------------------------------------------------------------
// Scenario result + run log
// ---------------------------------------------------------------------------

export interface ScenarioResult {
  blueprintId: string;
  blueprintName: string;
  baselineShipment: string;
  expectedShipment: string;
  /** Whole days pulled forward vs baseline (positive = earlier). */
  daysEarlier: number;
  yieldScore: number;
  /** Signed string, e.g. "+18%" / "-6%". */
  opexDelta: string;
  diseaseRisk: DiseaseRisk;
  riskNote: string;
}

export type RunLogLevel = 'info' | 'command' | 'result' | 'warning';

export interface RunLogEntry {
  id: string;
  timestamp: string;
  level: RunLogLevel;
  message: string;
}
