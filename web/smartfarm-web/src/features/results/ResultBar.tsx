import type { DiseaseRisk, RunLogEntry, RunLogLevel, ScenarioResult } from '@/domain/types';

/**
 * Footer: the scenario outcome for the *selected* candidate alongside the twin
 * run log. When `applied` is false the metrics are a forecast preview; once the
 * candidate is committed to the twin they read as the active result.
 */

interface ResultBarProps {
  result: ScenarioResult;
  /** True when the selected candidate is the one applied to the twin. */
  applied: boolean;
  runLog: RunLogEntry[];
}

const RISK_LABEL: Record<DiseaseRisk, string> = {
  high: 'High',
  controlled: 'Controlled',
  low: 'Low',
};

const LEVEL_GLYPH: Record<RunLogLevel, string> = {
  info: '·',
  command: '›',
  result: '✓',
  warning: '!',
};

export default function ResultBar({ result, applied, runLog }: ResultBarProps) {
  const earlier = result.daysEarlier;
  const shipmentDelta =
    earlier > 0 ? `${earlier}d earlier` : earlier < 0 ? `${Math.abs(earlier)}d later` : 'no change';

  return (
    <div className="result-bar">
      <div className="result-bar__main">
        <div className="result-bar__title">
          <span className={`result-bar__state result-bar__state--${applied ? 'live' : 'preview'}`}>
            {applied ? 'Applied to twin' : 'Forecast preview'}
          </span>
          <h2>{result.blueprintName}</h2>
        </div>

        <dl className="result-metrics">
          <div className="metric metric--accent">
            <dt>Expected shipment</dt>
            <dd>
              {result.expectedShipment}
              <span className={`metric__delta ${earlier > 0 ? 'is-good' : ''}`}>
                {shipmentDelta}
              </span>
            </dd>
          </div>
          <div className="metric">
            <dt>Baseline</dt>
            <dd>{result.baselineShipment}</dd>
          </div>
          <div className="metric">
            <dt>Yield score</dt>
            <dd>{result.yieldScore}</dd>
          </div>
          <div className="metric">
            <dt>OpEx Δ</dt>
            <dd
              className={
                result.opexDelta.startsWith('+')
                  ? 'is-up'
                  : result.opexDelta.startsWith('-')
                    ? 'is-down'
                    : ''
              }
            >
              {result.opexDelta}
            </dd>
          </div>
          <div className="metric">
            <dt>Disease risk</dt>
            <dd>
              <span className={`risk risk--${result.diseaseRisk}`}>
                {RISK_LABEL[result.diseaseRisk]}
              </span>
            </dd>
          </div>
        </dl>

        <p className="result-bar__note">{result.riskNote}</p>
      </div>

      <div className="result-bar__log" aria-label="Twin run log">
        <div className="run-log__head">Run log</div>
        <ol className="run-log">
          {runLog.map((entry) => (
            <li key={entry.id} className={`run-log__row run-log__row--${entry.level}`}>
              <span className="run-log__time">{entry.timestamp}</span>
              <span className="run-log__glyph" aria-hidden>
                {LEVEL_GLYPH[entry.level]}
              </span>
              <span className="run-log__msg">{entry.message}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
