import { useState, useCallback } from 'react';
import DashboardPage from './pages/DashboardPage';
import UploadPage from './pages/UploadPage';
import ReviewPage from './pages/ReviewPage';
import FolderReviewPage from './pages/FolderReviewPage';

type View = 'dashboard' | 'upload' | 'review' | 'folder';

export default function App() {
  const [view, setView] = useState<View>('dashboard');
  const [jobIds, setJobIds] = useState<string[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const handleDone = useCallback((ids: string[]) => {
    setJobIds(ids);
    setSelectedJobId(ids[0] || null);
    if (ids.length > 0) {
      setView('folder');
    }
  }, []);

  const handleBack = useCallback(() => {
    setJobIds([]);
    setSelectedJobId(null);
    setView('dashboard');
  }, []);

  const handleJobChange = useCallback((id: string) => {
    setSelectedJobId(id);
  }, []);

  const handleNewBatch = useCallback(() => {
    setView('upload');
  }, []);

  const handleSelectBatch = useCallback((jobId: string) => {
    setSelectedJobId(jobId);
    setJobIds([jobId]);
    setView('folder');
  }, []);

  if (view === 'upload') {
    return <UploadPage onDone={handleDone} onBack={handleBack} />;
  }

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
      onNewBatch={handleNewBatch}
      onSelectBatch={handleSelectBatch}
    />
  );
}
