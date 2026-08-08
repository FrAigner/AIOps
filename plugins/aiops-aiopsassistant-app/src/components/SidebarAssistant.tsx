import React from 'react';
import ChatPanel from './ChatPanel/ChatPanel';

// Komponente fuer den Grafana-Extension-Sidebar-Slot
// (grafana/extension-sidebar/v0-alpha) - dieselbe Sidebar, ueber die auch der
// offizielle Grafana Assistant eingehaengt wird. Props sind der Kontext, den
// Grafana beim Oeffnen mitgibt; wir brauchen ihn (noch) nicht.
function SidebarAssistant() {
  return <ChatPanel layout="narrow" />;
}

export default SidebarAssistant;
