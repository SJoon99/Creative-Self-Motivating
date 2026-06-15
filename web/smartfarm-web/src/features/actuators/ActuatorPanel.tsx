import type { ActuatorMode, ActuatorState } from '@/domain/types';

/**
 * Right column (bottom): the 3 control axes the twin drives. Each row shows the
 * current mode, a duty/level meter, and the secondary detail line. These mirror
 * what `smartfarm.apply_blueprint` pushed to the Kit twin.
 */

interface ActuatorPanelProps {
  actuators: ActuatorState[];
}

const MODE_LABEL: Record<ActuatorMode, string> = {
  off: 'Off',
  on: 'On',
  auto: 'Auto',
};

export default function ActuatorPanel({ actuators }: ActuatorPanelProps) {
  return (
    <div className="panel act-panel">
      <header className="panel__head">
        <h2 className="panel__title">Actuators</h2>
        <span className="panel__count">{actuators.length}</span>
      </header>

      <ul className="act-list">
        {actuators.map((a) => {
          const level = Math.min(100, Math.max(0, a.level));
          return (
            <li key={a.id} className={`act-row act-row--${a.mode}`}>
              <div className="act-row__head">
                <span className="act-row__label">{a.label}</span>
                <span className={`mode mode--${a.mode}`}>{MODE_LABEL[a.mode]}</span>
              </div>

              <div className="act-row__meter">
                <span className="act-row__fill" style={{ width: `${level}%` }} aria-hidden />
                <span className="act-row__level">
                  {a.level}
                  <em>{a.unit}</em>
                </span>
              </div>

              <p className="act-row__detail">{a.detail}</p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
