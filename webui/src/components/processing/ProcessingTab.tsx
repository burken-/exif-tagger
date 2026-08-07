import React from 'react';
import { useProcessing } from '@/hooks/useProcessing';
import { useToast } from '@/components/layout/ToastContainer';
import { SessionCard } from './SessionCard';
import { ProgressCard } from './ProgressCard';
import { LogOutputCard } from './LogOutputCard';

export const ProcessingTab: React.FC = () => {
  const {
    isRunning,
    folderPath,
    maxImages,
    processedCount,
    totalCount,
    progressPct,
    logs,
    autoScroll,
    statusText,
    summary,
    startProcessing,
    stopProcessing,
    clearLogs,
    setAutoScroll,
    setFolderPath,
    setMaxImages,
  } = useProcessing();

  const { showToast } = useToast();

  const handleStart = async () => {
    const res = await startProcessing();
    if (res) {
      if (res.success) {
        showToast('Processing session started', 'success');
      } else if (res.error) {
        showToast(res.error, 'error');
      }
    }
  };

  const handleStop = async () => {
    const res = await stopProcessing();
    if (res) {
      if (res.success) {
        showToast('Processing session stop requested', 'info');
      } else if (res.error) {
        showToast(res.error, 'error');
      }
    }
  };

  return (
    <div className="space-y-6">
      <SessionCard
        folderPath={folderPath}
        onFolderPathChange={setFolderPath}
        maxImages={maxImages}
        onMaxImagesChange={setMaxImages}
        isRunning={isRunning}
        onStart={handleStart}
        onStop={handleStop}
      />

      <ProgressCard
        processedCount={processedCount}
        totalCount={totalCount}
        progressPct={progressPct}
        statusText={statusText}
        isRunning={isRunning}
        summary={summary}
      />

      <LogOutputCard
        logs={logs}
        autoScroll={autoScroll}
        onAutoScrollChange={setAutoScroll}
        onClearLogs={clearLogs}
      />
    </div>
  );
};

export default ProcessingTab;
