import { createContext, useContext, type ReactNode } from 'react';
import type { RuntimeConfig } from '@/domain/types';

/**
 * App-wide providers. Today this only carries the runtime config (loaded once
 * at boot from /config.json), but it is the seam where a React Query client,
 * the Kit WebRTC bridge context, or a theme provider would be added later.
 */

const RuntimeConfigContext = createContext<RuntimeConfig | null>(null);

interface AppProvidersProps {
  config: RuntimeConfig;
  children: ReactNode;
}

export function AppProviders({ config, children }: AppProvidersProps) {
  return (
    <RuntimeConfigContext.Provider value={config}>{children}</RuntimeConfigContext.Provider>
  );
}

/** Access the runtime config from anywhere in the tree. */
export function useRuntimeConfig(): RuntimeConfig {
  const ctx = useContext(RuntimeConfigContext);
  if (!ctx) {
    throw new Error('useRuntimeConfig must be used within <AppProviders>');
  }
  return ctx;
}
