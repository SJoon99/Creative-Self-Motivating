import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { loadRuntimeConfig } from '@/config/loadRuntimeConfig';
import { AppProviders } from '@/app/providers';
import App from '@/app/App';
import '@/styles.css';

/**
 * Boot sequence: load the runtime config (NUC stream endpoint, facility info)
 * BEFORE the first render so the viewer never flashes a wrong/empty endpoint.
 */
async function bootstrap() {
  const config = await loadRuntimeConfig();

  const container = document.getElementById('root');
  if (!container) throw new Error('Root element #root not found');

  createRoot(container).render(
    <StrictMode>
      <AppProviders config={config}>
        <App />
      </AppProviders>
    </StrictMode>,
  );
}

void bootstrap();
