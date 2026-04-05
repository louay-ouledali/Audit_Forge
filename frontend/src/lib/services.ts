import {
  FlaskConical,
  Radar,
  BarChart3,
  Link,
  Search,
  Eye,
  Sparkles,
  Shield,
  ScrollText,
  Bell,
  Lightbulb,
  Terminal,
} from 'lucide-react';

export const SERVICES = {
  benchmarkStudio: { name: 'Benchmark Studio', icon: FlaskConical, color: 'purple' },
  missionControl: { name: 'Mission Control', icon: Radar, color: 'emerald' },
  reportStudio: { name: 'Report Studio', icon: BarChart3, color: 'sky' },
  forgeConnect: { name: 'Forge Connect', icon: Link, color: 'yellow' },
  forgeDiscovery: { name: 'Forge Discovery', icon: Search, color: 'orange' },
  forgeLens: { name: 'Forge Lens', icon: Eye, color: 'violet' },
  forgeCopilot: { name: 'Forge Copilot', icon: Sparkles, color: 'amber' },
  forgeGatekeeper: { name: 'Forge Gatekeeper', icon: Shield, color: 'red' },
  forgeTrail: { name: 'Forge Trail', icon: ScrollText, color: 'teal' },
  forgeSentinel: { name: 'Forge Sentinel', icon: Bell, color: 'rose' },
  forgeInsights: { name: 'Forge Insights', icon: Lightbulb, color: 'cyan' },
  forgeCli: { name: 'Forge CLI', icon: Terminal, color: 'zinc' },
} as const;
