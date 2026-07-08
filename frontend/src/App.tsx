import { useState, useCallback } from 'react';
import DashboardPage from './pages/DashboardPage';
import ReviewPage from './pages/ReviewPage';
import FolderReviewPage from './pages/FolderReviewPage';

type View = 'dashboard' | 'review' | 'folder';

export default function App() {
  const [view, setView] = useState<View>('dashboard');
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const handleBack = useCallback(() => {
    setJobIds([]);
    setSelectedJobId(null);
    setView('dashboard');
  }, []);

  const handleJobChange = useCallback((id: string) => {
    setSelectedJobId(id);
  }, []);

  const handleSelectBatch = useCallback((jobId: string) => {
    setSelectedJobId(jobId);
    setJobIds([jobId]);
    setView('folder');
  }, []);

  if (view === 'review' && selectedJobId) {
    return (
      <ReviewPage
        jobIds={jobIds}
        selectedJobId={selectedJobId}
        onBack={handleBack}
        onJobChange={handleJobChange}
        onJobsUpdate={setJobIds}
      />
    );
  }

  if (view === 'folder' && selectedJobId) {
    return (
      <FolderReviewPage
        jobId={selectedJobId}
        onBack={handleBack}
      />
    );
  }

  return (
    <DashboardPage
      onSelectBatch={handleSelectBatch}
    />
  );
}
