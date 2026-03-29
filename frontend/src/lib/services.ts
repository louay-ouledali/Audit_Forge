import {
  FlaskConical,
  Radar,
  BarChart3,
  Link,
  Search,
  Eye,
  Sparkles,
} from 'lucide-react';

export const SERVICES = {
  benchmarkStudio: { name: 'Benchmark Studio', icon: FlaskConical, color: 'purple' },
  missionControl: { name: 'Mission Control', icon: Radar, color: 'emerald' },
  reportStudio: { name: 'Report Studio', icon: BarChart3, color: 'sky' },
  forgeConnect: { name: 'Forge Connect', icon: Link, color: 'yellow' },
  forgeDiscovery: { name: 'Forge Discovery', icon: Search, color: 'orange' },
  forgeLens: { name: 'Forge Lens', icon: Eye, color: 'violet' },
  forgeCopilot: { name: 'Forge Copilot', icon: Sparkles, color: 'amber' },
} as const;
