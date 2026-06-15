import { useEffect, useMemo, useState } from 'react';
import { useRuntimeConfig } from '@/app/providers';
import PortalLayout from '@/app/PortalLayout';
import OmniverseViewport from '@/features/viewer/OmniverseViewport';
import BlueprintPanel from '@/features/blueprints/BlueprintPanel';
import SensorPanel from '@/features/sensors/SensorPanel';
import ActuatorPanel from '@/features/actuators/ActuatorPanel';
import GrowthStatusPanel from '@/features/growth/GrowthStatusPanel';
import ResultBar from '@/features/results/ResultBar';
import type {
  ActuatorState,
  ActuatorTarget,
  Blueprint,
  CropState,
  GrowthKpi,
  PlanningRun,
  ScenarioResult,
  SensorTarget,
  StreamStatus,
} from '@/domain/types';
import { createSmartfarmApi, type TwinSensorState, type TwinStateResponse } from '@/services/smartfarmApi';
import {
  BASELINE_ACTUATORS,
  BASELINE_BLUEPRINT,
  BASELINE_SENSORS,
  BLUEPRINTS,
  INITIAL_RUN_LOG,
  TWIN_DAY,
  actuatorsFromBlueprint,
  applyLogEntries,
  findBlueprint,
  resultFromBlueprint,
  sensorsFromTarget,
} from '@/domain/mockData';

/**
 * Owns the portal flow state and wires the feature panels into the layout:
 *
 *   select candidate -> apply to twin -> observe sensor/actuator/result change
 *
 * Twin render state (sensors, actuators) follows the *applied* blueprint, while
 * the forecast in the result bar follows the *selected* candidate — so an
 * operator can compare a plan before committing it to the twin.
 */
export default function App() {
  const config = useRuntimeConfig();
  const kioskMode = isKioskMode(config.defaultView);

  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [blueprints, setBlueprints] = useState<Blueprint[]>(BLUEPRINTS);
  const [selectedId, setSelectedId] = useState(BASELINE_BLUEPRINT.id);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const [planningRun, setPlanningRun] = useState<PlanningRun | null>(null);
  const [liveSensorTarget, setLiveSensorTarget] = useState<SensorTarget | null>(null);
  const [liveActuatorTarget, setLiveActuatorTarget] = useState<ActuatorTarget | null>(null);
  const [cropState, setCropState] = useState<CropState | null>(null);
  const [growthKpi, setGrowthKpi] = useState<GrowthKpi | null>(null);
  const [twinDay, setTwinDay] = useState(TWIN_DAY);
  const [runLog, setRunLog] = useState(INITIAL_RUN_LOG);
  const [serviceBusy, setServiceBusy] = useState(false);
  const [planningBusy, setPlanningBusy] = useState(false);
  const smartfarmApi = useMemo(() => createSmartfarmApi(config), [config]);

  const selected = useMemo(
    () => blueprints.find((bp) => bp.id === selectedId) ?? findBlueprint(selectedId) ?? BASELINE_BLUEPRINT,
    [blueprints, selectedId],
  );
  const applied = useMemo(
    () => (appliedId ? (blueprints.find((bp) => bp.id === appliedId) ?? findBlueprint(appliedId) ?? null) : null),
    [appliedId, blueprints],
  );

  const sensors = useMemo(
    () => (liveSensorTarget ? sensorsFromTarget(liveSensorTarget) : applied ? sensorsFromTarget(applied.sensorTarget) : BASELINE_SENSORS),
    [applied, liveSensorTarget],
  );
  const actuators = useMemo(
    () => (liveActuatorTarget ? actuatorsFromTarget(liveActuatorTarget) : applied ? actuatorsFromBlueprint(applied) : BASELINE_ACTUATORS),
    [applied, liveActuatorTarget],
  );
  const result = useMemo(() => resultFromSelected(selected, blueprints), [selected, blueprints]);

  const commitServiceState = (state: TwinStateResponse, options: { selectRecommended?: boolean } = {}) => {
    if (state.sensorState) {
      setLiveSensorTarget(sensorTargetFromTwin(state.sensorState));
      setTwinDay(state.sensorState.twinDay);
    }
    if (state.actuatorState) {
      setLiveActuatorTarget({
        ledIntensityPercent: state.actuatorState.ledIntensityPercent,
        photoperiodHours: state.actuatorState.photoperiodHours,
        waterValveOpen: state.actuatorState.waterValveOpen,
        irrigationPulsesPerDay: state.actuatorState.irrigationPulsesPerDay,
        fanDutyPercent: state.actuatorState.fanDutyPercent,
      });
    }
    if (state.cropState) {
      setCropState(state.cropState);
    }
    if (state.growthKpi) {
      setGrowthKpi(state.growthKpi);
    }
    if (state.appliedBlueprintId) {
      setAppliedId(state.appliedBlueprintId);
    }
    if (state.planningRun) {
      setPlanningRun(state.planningRun);
      setBlueprints(state.planningRun.candidates);
      if (options.selectRecommended && state.planningRun.recommendedBlueprintId) {
        setSelectedId(state.planningRun.recommendedBlueprintId);
      }
    }
  };

  useEffect(() => {
    let cancelled = false;
    smartfarmApi
      .getState()
      .then((state) => {
        if (cancelled) return;
        commitServiceState(state);
        setRunLog((log) => [
          ...log,
          {
            id: `service-state-${Date.now()}`,
            timestamp: new Date().toTimeString().slice(0, 8),
            level: 'info',
            message: `Kit twin service online · ${state.sceneMode} · ${smartfarmApi.baseUrl}`,
          },
        ]);
      })
      .catch((err) => {
        if (cancelled) return;
        console.warn('[smartfarm-api] state load failed; using local fallback', err);
        setRunLog((log) => [
          ...log,
          {
            id: `service-state-error-${Date.now()}`,
            timestamp: new Date().toTimeString().slice(0, 8),
            level: 'warning',
            message: `Kit service state unavailable; UI fallback active (${String(err.message ?? err)})`,
          },
        ]);
      });
    return () => {
      cancelled = true;
    };
  }, [smartfarmApi]);

  const handleRunPlanning = async () => {
    setPlanningBusy(true);
    setRunLog((log) => [
      ...log,
      {
        id: `planning-command-${Date.now()}`,
        timestamp: new Date().toTimeString().slice(0, 8),
        level: 'command',
        message: `POST ${smartfarmApi.baseUrl}/planning/run`,
      },
    ]);

    try {
      const state = await smartfarmApi.runDailyPlanning();
      commitServiceState(state, { selectRecommended: true });
      setRunLog((log) => [
        ...log,
        {
          id: `planning-result-${Date.now()}`,
          timestamp: new Date().toTimeString().slice(0, 8),
          level: 'result',
          message:
            state.message ||
            `Daily planning completed · recommended ${state.planningRun?.recommendedBlueprintId ?? '-'}.`,
        },
      ]);
    } catch (err) {
      console.error('[smartfarm-api] planning failed', err);
      setRunLog((log) => [
        ...log,
        {
          id: `planning-error-${Date.now()}`,
          timestamp: new Date().toTimeString().slice(0, 8),
          level: 'warning',
          message: `Daily planning failed (${String((err as Error).message ?? err)})`,
        },
      ]);
    } finally {
      setPlanningBusy(false);
    }
  };

  const handleApply = async (id: string) => {
    const blueprint = blueprints.find((bp) => bp.id === id) ?? findBlueprint(id);
    if (!blueprint) return;
    setServiceBusy(true);
    setRunLog((log) => [
      ...log,
      {
        id: `service-command-${Date.now()}`,
        timestamp: new Date().toTimeString().slice(0, 8),
        level: 'command',
        message: `POST ${smartfarmApi.baseUrl}/blueprint/apply → ${id}`,
      },
    ]);

    try {
      const state = await smartfarmApi.applyBlueprint(id);
      commitServiceState(state);
      setSelectedId(id);
      setAppliedId(state.appliedBlueprintId ?? id);
      setRunLog((log) => [
        ...log,
        ...applyLogEntries(blueprint),
        {
          id: `service-result-${Date.now()}`,
          timestamp: new Date().toTimeString().slice(0, 8),
          level: 'result',
          message: state.message || `Kit twin accepted ${id}.`,
        },
      ]);
    } catch (err) {
      console.error('[smartfarm-api] apply failed', err);
      setRunLog((log) => [
        ...log,
        {
          id: `service-error-${Date.now()}`,
          timestamp: new Date().toTimeString().slice(0, 8),
          level: 'warning',
          message: `Kit apply failed; UI not committed (${String((err as Error).message ?? err)})`,
        },
      ]);
    } finally {
      setServiceBusy(false);
    }
  };

  return (
    <PortalLayout
      streamStatus={streamStatus}
      twinDay={twinDay}
      blueprints={
        <BlueprintPanel
          blueprints={blueprints}
          selectedId={selectedId}
          appliedId={appliedId}
          planningRunId={planningRun?.runId ?? null}
          planningBusy={planningBusy}
          onSelect={setSelectedId}
          onApply={serviceBusy ? () => undefined : handleApply}
          onRunPlanning={handleRunPlanning}
        />
      }
      viewer={
        <OmniverseViewport
          stream={config.stream}
          status={streamStatus}
          onStatusChange={setStreamStatus}
          appliedBlueprintName={applied?.name ?? null}
          growthKpi={growthKpi}
          autoConnect={kioskMode}
          kiosk={kioskMode}
        />
      }
      sensors={
        <>
          <GrowthStatusPanel growthKpi={growthKpi} cropState={cropState} />
          <SensorPanel sensors={sensors} applied={Boolean(applied)} />
        </>
      }
      actuators={<ActuatorPanel actuators={actuators} />}
      result={<ResultBar result={result} applied={Boolean(applied)} runLog={runLog} />}
      kiosk={kioskMode}
    />
  );
}

function isKioskMode(defaultView?: 'dashboard' | 'kiosk'): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.get('dashboard') === '1' || params.get('view') === 'dashboard') return false;
  return (
    defaultView === 'kiosk' ||
    params.get('kiosk') === '1' ||
    params.get('kiosk') === 'true' ||
    params.get('view') === 'stream' ||
    params.get('mode') === 'kiosk'
  );
}

function sensorTargetFromTwin(sensor: TwinSensorState): SensorTarget {
  return {
    dliMolM2Day: sensor.dliMolM2Day,
    soilMoisturePercent: sensor.soilMoisturePercent,
    humidityPercent: sensor.humidityPercent,
    temperatureC: sensor.temperatureC,
    co2Ppm: sensor.co2Ppm,
  };
}

function actuatorsFromTarget(target: ActuatorTarget): ActuatorState[] {
  return [
    {
      id: 'led',
      label: 'Grow LED',
      mode: target.ledIntensityPercent > 0 ? 'on' : 'off',
      level: target.ledIntensityPercent,
      unit: '%',
      detail: `${target.photoperiodHours}h photoperiod`,
    },
    {
      id: 'water_valve',
      label: 'Water Valve',
      mode: target.waterValveOpen ? 'on' : 'off',
      level: target.waterValveOpen ? 100 : 0,
      unit: '%',
      detail: `${target.irrigationPulsesPerDay} pulses/day`,
    },
    {
      id: 'fan',
      label: 'Circulation Fan',
      mode: target.fanDutyPercent > 0 ? 'on' : 'off',
      level: target.fanDutyPercent,
      unit: '%',
      detail: `${target.fanDutyPercent}% duty`,
    },
  ];
}

function resultFromSelected(selected: Blueprint, blueprints: Blueprint[]): ScenarioResult {
  const base = resultFromBlueprint(selected);
  const dynamicBaseline = blueprints.find((bp) => bp.id === 'baseline')?.predicted.shipmentDate;
  if (!dynamicBaseline) return base;
  return {
    ...base,
    baselineShipment: dynamicBaseline,
    daysEarlier: daysBetween(dynamicBaseline, selected.predicted.shipmentDate),
  };
}

function daysBetween(fromIso: string, toIso: string): number {
  const ms = new Date(fromIso).getTime() - new Date(toIso).getTime();
  return Math.round(ms / 86_400_000);
}
