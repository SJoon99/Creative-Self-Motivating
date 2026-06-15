import type { ReactNode } from 'react';
import { useRuntimeConfig } from '@/app/providers';
import type { StreamStatus } from '@/domain/types';

/**
 * Pure layout shell for the single operational dashboard. It owns the header
 * and the dense 3-column + footer grid; feature panels are injected as slots so
 * this file stays free of business logic.
 *
 *   ┌──────────────────────── header ────────────────────────┐
 *   ├─ blueprints ─┬──── viewer (large) ────┬─ sensors/act ──┤
 *   ├──────────────── result bar (footer) ──────────────────┤
 */

const STATUS_LABEL: Record<StreamStatus, string> = {
  idle: 'Stream idle',
  connecting: 'Connecting…',
  connected: 'Stream live',
  error: 'Stream error',
};

interface PortalLayoutProps {
  streamStatus: StreamStatus;
  twinDay: number;
  blueprints: ReactNode;
  viewer: ReactNode;
  sensors: ReactNode;
  actuators: ReactNode;
  result: ReactNode;
  kiosk?: boolean;
}

export default function PortalLayout({
  streamStatus,
  twinDay,
  blueprints,
  viewer,
  sensors,
  actuators,
  result,
  kiosk = false,
}: PortalLayoutProps) {
  const config = useRuntimeConfig();

  if (kiosk) {
    return (
      <div className="portal portal--kiosk">
        <main className="portal-kiosk" aria-label="Fullscreen Omniverse live viewer">
          {viewer}
        </main>
      </div>
    );
  }

  return (
    <div className="portal">
      <header className="portal-header">
        <div className="portal-header__title">
          <span className="portal-header__mark">SF</span>
          <div>
            <h1>Smart Farm · Early-Shipment Digital Twin</h1>
            <p className="portal-header__sub">
              {config.facilityName} · <code>{config.facilityId}</code>
            </p>
          </div>
        </div>

        <div className="portal-header__meta">
          <span className="meta-chip">Grow day {twinDay}</span>
          <span className="meta-chip">{config.stream.server}</span>
          <span className={`status-dot status-dot--${streamStatus}`}>
            <i aria-hidden /> {STATUS_LABEL[streamStatus]}
          </span>
        </div>
      </header>

      <main className="portal-grid">
        <section className="portal-col portal-col--left" aria-label="Blueprint candidates">
          {blueprints}
        </section>

        <section className="portal-col portal-col--center" aria-label="Omniverse live viewer">
          {viewer}
        </section>

        <aside className="portal-col portal-col--right" aria-label="Twin state">
          {sensors}
          {actuators}
        </aside>

        <footer className="portal-footer" aria-label="Scenario result">
          {result}
        </footer>
      </main>
    </div>
  );
}
