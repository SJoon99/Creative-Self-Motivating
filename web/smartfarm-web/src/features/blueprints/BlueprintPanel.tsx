import type { Blueprint, DiseaseRisk } from '@/domain/types';

/**
 * Left column: the candidate operating prescriptions. Selecting a card previews
 * its forecast in the result bar; applying it commits the plan to the twin.
 */

interface BlueprintPanelProps {
  blueprints: Blueprint[];
  selectedId: string;
  appliedId: string | null;
  planningRunId?: string | null;
  planningBusy?: boolean;
  onSelect: (id: string) => void;
  onApply: (id: string) => void;
  onRunPlanning?: () => void;
}

const RISK_LABEL: Record<DiseaseRisk, string> = {
  high: 'High risk',
  controlled: 'Controlled',
  low: 'Low risk',
};

function opexLabel(percent: number): string {
  if (percent === 0) return '±0%';
  return `${percent > 0 ? '+' : ''}${percent}%`;
}

export default function BlueprintPanel({
  blueprints,
  selectedId,
  appliedId,
  planningRunId,
  planningBusy = false,
  onSelect,
  onApply,
  onRunPlanning,
}: BlueprintPanelProps) {
  return (
    <div className="panel bp-panel">
      <header className="panel__head">
        <div>
          <h2 className="panel__title">Blueprint candidates</h2>
          {planningRunId && <p className="panel__sub">Run {planningRunId}</p>}
        </div>
        <div className="panel__actions">
          {onRunPlanning && (
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              onClick={onRunPlanning}
              disabled={planningBusy}
            >
              {planningBusy ? 'Planning…' : 'Run Daily Planning'}
            </button>
          )}
          <span className="panel__count">{blueprints.length}</span>
        </div>
      </header>

      <ul className="bp-list">
        {blueprints.map((bp) => {
          const selected = bp.id === selectedId;
          const applied = bp.id === appliedId;
          return (
            <li key={bp.id}>
              <article
                className={`bp-card${selected ? ' bp-card--selected' : ''}${
                  applied ? ' bp-card--applied' : ''
                }`}
                onClick={() => onSelect(bp.id)}
                aria-current={selected}
              >
                <div className="bp-card__top">
                  <div className="bp-card__heading">
                    <h3 className="bp-card__name">{bp.name}</h3>
                    <p className="bp-card__tagline">{bp.tagline}</p>
                  </div>
                  <div className="bp-card__flags">
                    {bp.recommended && (
                      <span className="tag tag--reco" title="Scoring engine pick">
                        ★ Recommended
                      </span>
                    )}
                    {applied && <span className="tag tag--applied">● Applied</span>}
                  </div>
                </div>

                <dl className="bp-card__stats">
                  <div className="bp-stat">
                    <dt>Ship</dt>
                    <dd>{bp.predicted.shipmentDate}</dd>
                  </div>
                  <div className="bp-stat">
                    <dt>Yield</dt>
                    <dd>{bp.predicted.yieldScore}</dd>
                  </div>
                  <div className="bp-stat">
                    <dt>OpEx</dt>
                    <dd
                      className={
                        bp.predicted.opexDeltaPercent > 0
                          ? 'is-up'
                          : bp.predicted.opexDeltaPercent < 0
                            ? 'is-down'
                            : ''
                      }
                    >
                      {opexLabel(bp.predicted.opexDeltaPercent)}
                    </dd>
                  </div>
                  <div className="bp-stat">
                    <dt>Disease</dt>
                    <dd>
                      <span className={`risk risk--${bp.predicted.diseaseRisk}`}>
                        {RISK_LABEL[bp.predicted.diseaseRisk]}
                      </span>
                    </dd>
                  </div>
                </dl>

                <div className="bp-card__foot">
                  <span className="bp-card__horizon">
                    {bp.horizonDays}-day horizon
                    {typeof bp.score === 'number' ? ` · score ${bp.score}` : ''}
                  </span>
                  <button
                    type="button"
                    className={`btn btn--sm ${applied ? 'btn--ghost' : 'btn--primary'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onApply(bp.id);
                    }}
                    disabled={applied}
                  >
                    {applied ? 'On twin' : 'Apply'}
                  </button>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
