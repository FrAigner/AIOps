import React, { Suspense, lazy } from 'react';
import { AppPlugin, PluginExtensionPoints } from '@grafana/data';
import { LoadingPlaceholder } from '@grafana/ui';
import type { AppConfigProps } from './components/AppConfig/AppConfig';

const App = lazy(() => import('./components/App/App'));
const LazyAppConfig = lazy(() => import('./components/AppConfig/AppConfig'));
const LazySidebarAssistant = lazy(() => import('./components/SidebarAssistant'));

const AppConfig = (props: AppConfigProps) => (
  <Suspense fallback={<LoadingPlaceholder text="" />}>
    <LazyAppConfig {...props} />
  </Suspense>
);

const SidebarAssistant = () => (
  <Suspense fallback={<LoadingPlaceholder text="" />}>
    <LazySidebarAssistant />
  </Suspense>
);

const SIDEBAR_COMPONENT_TITLE = 'AIOps Assistant';

export const plugin = new AppPlugin<{}>()
  .setRootPage(App)
  .addConfigPage({
    title: 'Configuration',
    icon: 'cog',
    body: AppConfig,
    id: 'configuration',
  })
  .addComponent({
    // Derselbe Extension-Point, ueber den auch der offizielle Grafana
    // Assistant seine rechte Sidebar einhaengt (noch v0-alpha, kein
    // stabiler Export in @grafana/data - daher der rohe String).
    targets: 'grafana/extension-sidebar/v0-alpha',
    title: SIDEBAR_COMPONENT_TITLE,
    description: 'KI-Analyse-Chat fuer die AIOps-Plattform',
    component: SidebarAssistant,
  })
  .addLink({
    // Der permanente Sparkle-Icon-Slot oben rechts (neben Hilfe/Sign-in) ist
    // Grafana-Core-exklusiv fuer grafana-assistant-app reserviert - kein
    // generischer Extension-Point, ueber den Drittanbieter-Plugins dort
    // andocken koennen (verifiziert durch Analyse des offiziellen
    // Plugin-Bundles). Die Command Palette (Cmd/Ctrl+K) ist der echte,
    // von-ueberall-erreichbare Trigger, den auch der offizielle Assistant
    // zusaetzlich zu seinem Sonderrecht nutzt.
    targets: PluginExtensionPoints.CommandPalette,
    title: '✨ AIOps Assistant öffnen',
    description: 'KI-Analyse-Chat oeffnen',
    icon: 'comment-alt',
    onClick: (_event, helpers) => {
      helpers.toggleSidebar(SIDEBAR_COMPONENT_TITLE);
    },
  });
