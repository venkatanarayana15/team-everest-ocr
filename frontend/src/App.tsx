import { useState, useCallback } from 'react';
import ErrorBoundary from './components/ErrorBoundary';
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

  return (
    <ErrorBoundary>
      {view === 'review' && selectedJobId ? (
        <ReviewPage
          jobIds={jobIds}
          selectedJobId={selectedJobId}
          onBack={handleBack}
          onJobChange={handleJobChange}
          onJobsUpdate={setJobIds}
        />
      ) : view === 'folder' && selectedJobId ? (
        <FolderReviewPage
          jobId={selectedJobId}
          onBack={handleBack}
        />
      ) : (
        <DashboardPage
          onSelectBatch={handleSelectBatch}
        />
      )}
    </ErrorBoundary>
  );
}
