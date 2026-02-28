import { useLocation } from 'react-router-dom';
import ReportBuilder from './ReportBuilder';

export default function Reports() {
  const location = useLocation();
  const state = location.state as { missionId?: number; missionName?: string } | null;
  return <ReportBuilder missionId={state?.missionId} missionName={state?.missionName} />;
}
