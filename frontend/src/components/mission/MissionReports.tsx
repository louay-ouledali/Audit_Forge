import { useNavigate } from 'react-router-dom';
import { BarChart3, Bot } from 'lucide-react';

interface Props {
  missionId: number;
  missionName?: string;
}

export default function MissionReports({ missionId, missionName }: Props) {
  const navigate = useNavigate();

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <h3 className="mb-4 text-lg font-semibold text-white">Generate Reports</h3>
        <p className="mb-4 text-sm text-dark-secondary">
          Use the Reports page for full report generation with the Report Builder.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/reports', { state: { missionId, missionName } })}
            className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-black hover:bg-ey-yellow-hover"
          >
            <BarChart3 className="h-4 w-4" /> Open Report Builder
          </button>
          <button
            onClick={() => navigate(`/missions/${missionId}/analysis`)}
            className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-sm font-medium text-dark-secondary hover:text-white"
          >
            <Bot className="h-4 w-4" /> AI Analysis
          </button>
        </div>
      </div>
    </div>
  );
}
