import type { CropState, GrowthKpi } from '@/domain/types';

interface GrowthStatusPanelProps {
  growthKpi: GrowthKpi | null;
  cropState: CropState | null;
}

function pct(value?: number): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `${Math.round(value)}%`;
}

function fractionPct(value?: number): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `${Math.round(value * 100)}%`;
}

function scoreTone(score?: number): 'ok' | 'warning' | 'critical' {
  if (typeof score !== 'number') return 'warning';
  if (score >= 72) return 'ok';
  if (score >= 55) return 'warning';
  return 'critical';
}

export default function GrowthStatusPanel({ growthKpi, cropState }: GrowthStatusPanelProps) {
  const tone = scoreTone(growthKpi?.healthScore);
  return (
    <div className="panel growth-panel">
      <header className="panel__head">
        <div>
          <h2 className="panel__title">Growth status</h2>
          <p className="panel__sub">sensor + crop-state model</p>
        </div>
        <span className={`growth-score growth-score--${tone}`}>
          {growthKpi?.healthScore ?? '-'}<small>/100</small>
        </span>
      </header>

      <div className="growth-panel__body">
        <div className="growth-hero">
          <span className="growth-hero__label">Growth Health Score</span>
          <div className="growth-hero__track" aria-hidden>
            <span
              className={`growth-hero__fill growth-hero__fill--${tone}`}
              style={{ width: `${Math.max(0, Math.min(100, growthKpi?.healthScore ?? 0))}%` }}
            />
          </div>
          <span className="growth-hero__basis">{growthKpi?.confidence ?? 'model-estimated'}</span>
        </div>

        <dl className="growth-grid">
          <div>
            <dt>Fruit maturity</dt>
            <dd>{pct(growthKpi?.fruitMaturityPercent)}</dd>
          </div>
          <div>
            <dt>Harvest readiness</dt>
            <dd>{pct(growthKpi?.harvestReadinessPercent)}</dd>
          </div>
          <div>
            <dt>Expected ship</dt>
            <dd>{growthKpi?.expectedShip ?? '-'}</dd>
          </div>
          <div>
            <dt>Disease risk</dt>
            <dd>{growthKpi?.diseaseRisk ?? '-'}</dd>
          </div>
          <div>
            <dt>Fruit set</dt>
            <dd>{fractionPct(cropState?.fruitSet)}</dd>
          </div>
          <div>
            <dt>Yield estimate</dt>
            <dd>{cropState?.estimatedYield ?? '-'}<small>/100</small></dd>
          </div>
        </dl>

        <div className="growth-limiter">
          <span>Main limiting factor</span>
          <strong>{growthKpi?.mainLimitingFactor ?? 'Waiting for twin state'}</strong>
        </div>

        {growthKpi?.evidence?.length ? (
          <ul className="growth-evidence">
            {growthKpi.evidence.slice(0, 4).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
