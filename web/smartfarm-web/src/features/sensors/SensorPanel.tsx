import type { SensorReading } from '@/domain/types';

/**
 * Right column (top): the 5 virtual sensor axes as compact band gauges. Each
 * track shows the display range with the optimal band highlighted and a marker
 * at the current reading; the marker colour follows the sensor's status.
 */

interface SensorPanelProps {
  sensors: SensorReading[];
  /** True once a blueprint is committed — gauges reflect the twin, not baseline. */
  applied: boolean;
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n));
}

/** Position (0–1) of a value within the gauge's display range. */
function frac(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return clamp01((value - min) / (max - min));
}

function formatValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export default function SensorPanel({ sensors, applied }: SensorPanelProps) {
  return (
    <div className="panel sensor-panel">
      <header className="panel__head">
        <h2 className="panel__title">Virtual sensors</h2>
        <span className={`panel__source panel__source--${applied ? 'applied' : 'baseline'}`}>
          {applied ? 'Applied target' : 'Baseline'}
        </span>
      </header>

      <ul className="gauge-list">
        {sensors.map((s) => {
          const value = frac(s.value, s.rangeMin, s.rangeMax);
          const bandStart = frac(s.optimalMin, s.rangeMin, s.rangeMax);
          const bandEnd = frac(s.optimalMax, s.rangeMin, s.rangeMax);
          return (
            <li key={s.id} className="gauge">
              <div className="gauge__head">
                <span className="gauge__short">{s.short}</span>
                <span className="gauge__value">
                  {formatValue(s.value)}
                  <em className="gauge__unit">{s.unit}</em>
                </span>
                <span
                  className={`dot dot--${s.status}`}
                  title={`Status: ${s.status}`}
                  aria-label={`Status ${s.status}`}
                />
              </div>

              <div className="gauge__track">
                <span
                  className="gauge__band"
                  style={{
                    left: `${bandStart * 100}%`,
                    width: `${Math.max(0, bandEnd - bandStart) * 100}%`,
                  }}
                  aria-hidden
                />
                <span
                  className={`gauge__marker gauge__marker--${s.status}`}
                  style={{ left: `${value * 100}%` }}
                  aria-hidden
                />
              </div>

              <div className="gauge__foot">
                <span className="gauge__label">{s.label}</span>
                <span className="gauge__optimal">
                  opt {formatValue(s.optimalMin)}–{formatValue(s.optimalMax)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
