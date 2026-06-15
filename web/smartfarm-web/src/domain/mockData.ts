/**
 * Deterministic mock data + derivation helpers for the portal prototype.
 *
 * Everything here is a stand-in for two future backends:
 *   - Service API   -> blueprint candidates, forecast, scoring, run history
 *   - Kit twin (NUC) -> live sensor / actuator state over the WebRTC bridge
 *
 * Keeping the derivations pure means the UI flow (select -> apply -> observe)
 * can be validated before either backend exists.
 */

import type {
  ActuatorState,
  Blueprint,
  RunLogEntry,
  ScenarioResult,
  SensorReading,
  SensorTarget,
} from '@/domain/types';

/** Simulated twin clock — day in the current grow cycle. */
export const TWIN_DAY = 34;
export const SCENARIO_SEED = 'smartfarm-v1';
export const BASELINE_SHIPMENT = '2027-01-06';

// ---------------------------------------------------------------------------
// Blueprint candidates: Baseline + 3 Gemma plans
// ---------------------------------------------------------------------------

export const BLUEPRINTS: Blueprint[] = [
  {
    id: 'baseline',
    kind: 'baseline',
    name: 'Baseline',
    tagline: 'Current standing operation — no intervention.',
    horizonDays: 75,
    targetShipmentDate: BASELINE_SHIPMENT,
    sensorTarget: {
      dliMolM2Day: 11.2,
      soilMoisturePercent: 31,
      humidityPercent: 82,
      temperatureC: 24.8,
      co2Ppm: 420,
    },
    actuatorTarget: {
      ledIntensityPercent: 40,
      photoperiodHours: 12,
      waterValveOpen: false,
      irrigationPulsesPerDay: 2,
      fanDutyPercent: 20,
    },
    predicted: {
      shipmentDate: BASELINE_SHIPMENT,
      yieldScore: 72,
      opexDeltaPercent: 0,
      diseaseRisk: 'high',
      riskNote: 'Humidity 82% — botrytis watch. Soil moisture trending dry.',
    },
    recommended: false,
  },
  {
    id: 'plan-a-low-cost',
    kind: 'low_cost',
    name: 'Plan A',
    tagline: 'Minimise OpEx, accept a slower grow curve.',
    horizonDays: 70,
    targetShipmentDate: '2027-01-01',
    sensorTarget: {
      dliMolM2Day: 13.5,
      soilMoisturePercent: 42,
      humidityPercent: 72,
      temperatureC: 23.2,
      co2Ppm: 500,
    },
    actuatorTarget: {
      ledIntensityPercent: 55,
      photoperiodHours: 13,
      waterValveOpen: true,
      irrigationPulsesPerDay: 3,
      fanDutyPercent: 35,
    },
    predicted: {
      shipmentDate: '2027-01-01',
      yieldScore: 79,
      opexDeltaPercent: -6,
      diseaseRisk: 'controlled',
      riskNote: 'Stable envelope, modest yield. Lowest running cost.',
    },
    recommended: false,
  },
  {
    id: 'plan-b-early-shipment',
    kind: 'early_shipment',
    name: 'Plan B',
    tagline: 'Push DLI + CO₂ for the earliest viable harvest.',
    horizonDays: 60,
    targetShipmentDate: '2026-12-22',
    sensorTarget: {
      dliMolM2Day: 17.8,
      soilMoisturePercent: 48,
      humidityPercent: 68,
      temperatureC: 23.6,
      co2Ppm: 650,
    },
    actuatorTarget: {
      ledIntensityPercent: 80,
      photoperiodHours: 16,
      waterValveOpen: true,
      irrigationPulsesPerDay: 3,
      fanDutyPercent: 55,
    },
    predicted: {
      shipmentDate: '2026-12-22',
      yieldScore: 87,
      opexDeltaPercent: 18,
      diseaseRisk: 'controlled',
      riskNote: 'Higher energy load; disease risk held in check by airflow.',
    },
    recommended: true,
  },
  {
    id: 'plan-c-disease-safe',
    kind: 'disease_safe',
    name: 'Plan C',
    tagline: 'Lower humidity, stronger airflow, conservative climate.',
    horizonDays: 66,
    targetShipmentDate: '2026-12-28',
    sensorTarget: {
      dliMolM2Day: 15.4,
      soilMoisturePercent: 45,
      humidityPercent: 62,
      temperatureC: 22.8,
      co2Ppm: 580,
    },
    actuatorTarget: {
      ledIntensityPercent: 70,
      photoperiodHours: 15,
      waterValveOpen: true,
      irrigationPulsesPerDay: 4,
      fanDutyPercent: 70,
    },
    predicted: {
      shipmentDate: '2026-12-28',
      yieldScore: 83,
      opexDeltaPercent: 9,
      diseaseRisk: 'low',
      riskNote: 'Lowest botrytis risk. Slightly later than Plan B.',
    },
    recommended: false,
  },
];

export const RECOMMENDED_BLUEPRINT =
  BLUEPRINTS.find((b) => b.recommended) ?? BLUEPRINTS[0];

export const BASELINE_BLUEPRINT = BLUEPRINTS[0];

export function findBlueprint(id: string): Blueprint | undefined {
  return BLUEPRINTS.find((b) => b.id === id);
}

// ---------------------------------------------------------------------------
// Sensor readings derived from a target (5 sensors)
// ---------------------------------------------------------------------------

interface SensorSpec {
  id: SensorReading['id'];
  label: string;
  short: string;
  unit: string;
  optimalMin: number;
  optimalMax: number;
  rangeMin: number;
  rangeMax: number;
  linkedActuator: SensorReading['linkedActuator'];
  pick: (t: SensorTarget) => number;
}

const SENSOR_SPECS: SensorSpec[] = [
  {
    id: 'dli',
    label: 'Daily Light Integral',
    short: 'DLI',
    unit: 'mol/m²·d',
    optimalMin: 14,
    optimalMax: 20,
    rangeMin: 6,
    rangeMax: 24,
    linkedActuator: 'led',
    pick: (t) => t.dliMolM2Day,
  },
  {
    id: 'soil_moisture',
    label: 'Substrate Moisture',
    short: 'SOIL',
    unit: '%',
    optimalMin: 40,
    optimalMax: 55,
    rangeMin: 10,
    rangeMax: 80,
    linkedActuator: 'water_valve',
    pick: (t) => t.soilMoisturePercent,
  },
  {
    id: 'humidity',
    label: 'Relative Humidity',
    short: 'RH',
    unit: '%',
    optimalMin: 60,
    optimalMax: 72,
    rangeMin: 40,
    rangeMax: 95,
    linkedActuator: 'fan',
    pick: (t) => t.humidityPercent,
  },
  {
    id: 'temperature',
    label: 'Air Temperature',
    short: 'TEMP',
    unit: '°C',
    optimalMin: 21,
    optimalMax: 25,
    rangeMin: 14,
    rangeMax: 34,
    linkedActuator: 'fan',
    pick: (t) => t.temperatureC,
  },
  {
    id: 'co2',
    label: 'CO₂ Concentration',
    short: 'CO₂',
    unit: 'ppm',
    optimalMin: 550,
    optimalMax: 800,
    rangeMin: 380,
    rangeMax: 1000,
    linkedActuator: 'led',
    pick: (t) => t.co2Ppm,
  },
];

function statusFor(value: number, spec: SensorSpec): SensorReading['status'] {
  if (value >= spec.optimalMin && value <= spec.optimalMax) return 'ok';
  // Within 15% of the optimal band edge -> warning, else critical.
  const span = spec.optimalMax - spec.optimalMin;
  const slack = span * 0.4;
  if (value >= spec.optimalMin - slack && value <= spec.optimalMax + slack) {
    return 'warning';
  }
  return 'critical';
}

export function sensorsFromTarget(target: SensorTarget): SensorReading[] {
  return SENSOR_SPECS.map((spec) => {
    const value = spec.pick(target);
    return {
      id: spec.id,
      label: spec.label,
      short: spec.short,
      value,
      unit: spec.unit,
      status: statusFor(value, spec),
      optimalMin: spec.optimalMin,
      optimalMax: spec.optimalMax,
      rangeMin: spec.rangeMin,
      rangeMax: spec.rangeMax,
      linkedActuator: spec.linkedActuator,
    };
  });
}

// ---------------------------------------------------------------------------
// Actuator state derived from a blueprint (3 actuators)
// ---------------------------------------------------------------------------

export function actuatorsFromBlueprint(blueprint: Blueprint): ActuatorState[] {
  const a = blueprint.actuatorTarget;
  return [
    {
      id: 'led',
      label: 'Grow LED',
      mode: a.ledIntensityPercent > 0 ? 'on' : 'off',
      level: a.ledIntensityPercent,
      unit: '%',
      detail: `${a.photoperiodHours}h photoperiod`,
    },
    {
      id: 'water_valve',
      label: 'Water Valve',
      mode: a.waterValveOpen ? 'on' : 'off',
      level: a.waterValveOpen ? 100 : 0,
      unit: '%',
      detail: `${a.irrigationPulsesPerDay} pulses/day · target ${blueprint.sensorTarget.soilMoisturePercent}%`,
    },
    {
      id: 'fan',
      label: 'Circulation Fan',
      mode: a.fanDutyPercent > 0 ? 'on' : 'off',
      level: a.fanDutyPercent,
      unit: '%',
      detail: `${a.fanDutyPercent}% duty`,
    },
  ];
}

// ---------------------------------------------------------------------------
// Scenario result derived from a blueprint
// ---------------------------------------------------------------------------

function daysBetween(fromIso: string, toIso: string): number {
  const ms = new Date(fromIso).getTime() - new Date(toIso).getTime();
  return Math.round(ms / 86_400_000);
}

export function resultFromBlueprint(blueprint: Blueprint): ScenarioResult {
  const p = blueprint.predicted;
  const sign = p.opexDeltaPercent > 0 ? '+' : '';
  return {
    blueprintId: blueprint.id,
    blueprintName: blueprint.name,
    baselineShipment: BASELINE_SHIPMENT,
    expectedShipment: p.shipmentDate,
    daysEarlier: daysBetween(BASELINE_SHIPMENT, p.shipmentDate),
    yieldScore: p.yieldScore,
    opexDelta: `${sign}${p.opexDeltaPercent}%`,
    diseaseRisk: p.diseaseRisk,
    riskNote: p.riskNote,
  };
}

// ---------------------------------------------------------------------------
// Baseline twin state + initial run log
// ---------------------------------------------------------------------------

export const BASELINE_SENSORS = sensorsFromTarget(BLUEPRINTS[0].sensorTarget);
export const BASELINE_ACTUATORS = actuatorsFromBlueprint(BLUEPRINTS[0]);

export const INITIAL_RUN_LOG: RunLogEntry[] = [
  {
    id: 'log-0',
    timestamp: '08:00:00',
    level: 'info',
    message: `Twin "${SCENARIO_SEED}" online · grow cycle day ${TWIN_DAY}.`,
  },
  {
    id: 'log-1',
    timestamp: '08:00:02',
    level: 'info',
    message: 'Loaded 4 blueprint candidates from Service API (mock).',
  },
  {
    id: 'log-2',
    timestamp: '08:00:02',
    level: 'warning',
    message: 'Baseline humidity 82% — botrytis risk flagged.',
  },
];

let logSeq = INITIAL_RUN_LOG.length;

/** Build the run-log entries emitted when a blueprint is applied to the twin. */
export function applyLogEntries(blueprint: Blueprint): RunLogEntry[] {
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  const result = resultFromBlueprint(blueprint);
  return [
    {
      id: `log-${logSeq++}`,
      timestamp: ts,
      level: 'command',
      message: `smartfarm.apply_blueprint → ${blueprint.id}`,
    },
    {
      id: `log-${logSeq++}`,
      timestamp: ts,
      level: 'result',
      message: `Twin updated · shipment ${result.expectedShipment} (${
        result.daysEarlier > 0 ? `${result.daysEarlier}d earlier` : 'no change'
      }) · yield ${result.yieldScore}.`,
    },
  ];
}
