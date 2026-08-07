import React, { useState } from 'react';
import { useSchedule } from '@/hooks/useSchedule';
import { useToast } from '@/components/layout/ToastContainer';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Calendar,
  Clock,
  Play,
  Trash2,
  Plus,
  Folder,
  Loader2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';
import type { CreateSchedulePayload } from '@/types';

interface PresetOption {
  label: string;
  value: string;
  cron: string;
  intervalHours?: number;
}

const CRON_PRESETS: PresetOption[] = [
  { label: 'Every Hour', value: 'hourly', cron: '0 * * * *', intervalHours: 1 },
  { label: 'Every 6 Hours', value: '6hours', cron: '0 */6 * * *', intervalHours: 6 },
  { label: 'Every 12 Hours', value: '12hours', cron: '0 */12 * * *', intervalHours: 12 },
  { label: 'Daily at Midnight', value: 'daily', cron: '0 0 * * *', intervalHours: 24 },
  { label: 'Weekly (Sunday at Midnight)', value: 'weekly', cron: '0 0 * * 0', intervalHours: 168 },
  { label: 'Custom Cron Expression', value: 'custom', cron: '' },
];

export const ScheduleTab: React.FC = () => {
  const { schedules, loading, error, loadSchedules, runSchedule, deleteSchedule, createSchedule } =
    useSchedule();
  const { showToast } = useToast();

  const [isDialogOpen, setIsDialogOpen] = useState<boolean>(false);
  const [runningId, setRunningId] = useState<string | number | null>(null);
  const [deletingId, setDeletingId] = useState<string | number | null>(null);

  // Form State for New Schedule
  const [jobName, setJobName] = useState<string>('');
  const [folderPath, setFolderPath] = useState<string>('');
  const [preset, setPreset] = useState<string>('hourly');
  const [cronExpr, setCronExpr] = useState<string>('0 * * * *');
  const [intervalHours, setIntervalHours] = useState<string>('1');
  const [maxImages, setMaxImages] = useState<string>('');
  const [isActive, setIsActive] = useState<boolean>(true);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const resetForm = () => {
    setJobName('');
    setFolderPath('');
    setPreset('hourly');
    setCronExpr('0 * * * *');
    setIntervalHours('1');
    setMaxImages('');
    setIsActive(true);
  };

  const handlePresetChange = (selected: string) => {
    setPreset(selected);
    const found = CRON_PRESETS.find((p) => p.value === selected);
    if (found && selected !== 'custom') {
      setCronExpr(found.cron);
      if (found.intervalHours) {
        setIntervalHours(found.intervalHours.toString());
      }
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jobName.trim()) {
      showToast('Schedule name is required', 'warning');
      return;
    }
    if (!folderPath.trim()) {
      showToast('Target folder path is required', 'warning');
      return;
    }

    setIsSubmitting(true);
    try {
      const payload: CreateSchedulePayload = {
        name: jobName.trim(),
        folder: folderPath.trim(),
        cron_expression: cronExpr.trim() || undefined,
        interval_hours: intervalHours ? parseFloat(intervalHours) : undefined,
        max_images: maxImages ? parseInt(maxImages, 10) : undefined,
        enabled: isActive,
      };

      const res = await createSchedule(payload);
      if (res.success) {
        showToast(`Schedule "${jobName}" created successfully`, 'success');
        setIsDialogOpen(false);
        resetForm();
      } else {
        showToast(res.error || 'Failed to create schedule', 'error');
      }
    } catch (err: any) {
      showToast('Error creating schedule: ' + err.message, 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRunNow = async (id: string | number, name: string) => {
    setRunningId(id);
    try {
      const res = await runSchedule(id);
      if (res.success) {
        showToast(`Triggered execution for "${name}"`, 'success');
      } else {
        showToast(res.error || `Failed to run job "${name}"`, 'error');
      }
    } catch (err: any) {
      showToast('Failed to trigger job: ' + err.message, 'error');
    } finally {
      setRunningId(null);
    }
  };

  const handleDelete = async (id: string | number, name: string) => {
    setDeletingId(id);
    try {
      const res = await deleteSchedule(id);
      if (res.success) {
        showToast(`Deleted schedule "${name}"`, 'info');
      } else {
        showToast(res.error || `Failed to delete "${name}"`, 'error');
      }
    } catch (err: any) {
      showToast('Error deleting schedule: ' + err.message, 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const formatDate = (isoStr?: string) => {
    if (!isoStr) return 'Never';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border p-5 rounded-xl shadow-sm">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Calendar className="w-5 h-5 text-primary" />
            Scheduled Tasks
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Automate recurring tag processing scans using cron expressions or intervals.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={loadSchedules}
            disabled={loading}
            className="gap-1.5"
            title="Refresh schedules"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={() => {
              resetForm();
              setIsDialogOpen(true);
            }}
            className="gap-1.5 font-semibold bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="w-4 h-4" />
            Add New Schedule
          </Button>
        </div>
      </div>

      {/* Main Schedule List Card */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-lg">Configured Cron Jobs</CardTitle>
          <CardDescription>
            Active and inactive scheduled image processing tasks.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && schedules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
              <Loader2 className="w-7 h-7 animate-spin text-primary" />
              <p className="text-sm font-medium">Loading schedules...</p>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-8 text-destructive gap-2 border border-destructive/20 rounded-lg bg-destructive/5">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <p className="text-sm">{error}</p>
            </div>
          ) : schedules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center border border-dashed rounded-lg">
              <Clock className="w-10 h-10 text-muted-foreground/50 mb-3" />
              <h3 className="text-base font-semibold text-foreground">No Cron Schedules Found</h3>
              <p className="text-sm text-muted-foreground max-w-sm mt-1 mb-4">
                You haven't set up any recurring tagging jobs yet. Add a new schedule to run AI scans automatically.
              </p>
              <Button
                size="sm"
                onClick={() => {
                  resetForm();
                  setIsDialogOpen(true);
                }}
                className="gap-1.5"
              >
                <Plus className="w-4 h-4" />
                Add New Schedule
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-muted-foreground text-xs uppercase font-semibold">
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Job Name & Path</th>
                    <th className="py-3 px-4">Cron Expression</th>
                    <th className="py-3 px-4">Limit</th>
                    <th className="py-3 px-4">Last Run</th>
                    <th className="py-3 px-4">Next Run</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {schedules.map((job) => {
                    const active = job.enabled !== false;
                    const isRunning = runningId === job.id;
                    const isDeleting = deletingId === job.id;

                    return (
                      <tr
                        key={job.id}
                        className="hover:bg-accent/30 transition-colors group"
                      >
                        <td className="py-3.5 px-4">
                          {active ? (
                            <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1">
                              <CheckCircle2 className="w-3 h-3" /> Active
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="text-muted-foreground gap-1">
                              Disabled
                            </Badge>
                          )}
                        </td>
                        <td className="py-3.5 px-4 font-medium">
                          <div className="text-foreground font-semibold">{job.name}</div>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground mt-0.5 font-mono">
                            <Folder className="w-3.5 h-3.5 shrink-0 text-primary/70" />
                            <span className="truncate max-w-[200px]">{job.folder}</span>
                          </div>
                        </td>
                        <td className="py-3.5 px-4 font-mono text-xs">
                          {job.cron_expression ? (
                            <span className="px-2 py-1 rounded bg-accent/60 border border-border text-foreground font-mono">
                              {job.cron_expression}
                            </span>
                          ) : job.interval_hours ? (
                            <span className="text-muted-foreground">
                              Every {job.interval_hours}h
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-muted-foreground text-xs font-mono">
                          {job.max_images ? `${job.max_images} imgs` : 'Unlimited'}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-muted-foreground">
                          <div>{formatDate(job.last_run_at)}</div>
                          {job.last_status && (
                            <span
                              className={`text-[10px] uppercase font-semibold ${
                                job.last_status === 'success'
                                  ? 'text-emerald-400'
                                  : 'text-rose-400'
                              }`}
                            >
                              {job.last_status}
                            </span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-muted-foreground">
                          {formatDate(job.next_run_at)}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleRunNow(job.id, job.name)}
                              disabled={isRunning}
                              className="h-8 gap-1 text-xs"
                              title="Run job immediately"
                            >
                              {isRunning ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Play className="w-3.5 h-3.5 fill-current text-primary" />
                              )}
                              Run Now
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleDelete(job.id, job.name)}
                              disabled={isDeleting}
                              className="h-8 w-8 p-0"
                              title="Delete schedule"
                            >
                              {isDeleting ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="w-3.5 h-3.5" />
                              )}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add New Schedule Dialog Modal */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Calendar className="w-5 h-5 text-primary" />
              Add New Schedule
            </DialogTitle>
            <DialogDescription>
              Configure an automated background scan for a target image directory.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleCreateSubmit} className="space-y-4 py-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Schedule Name *</label>
              <Input
                value={jobName}
                onChange={(e) => setJobName(e.target.value)}
                placeholder="e.g. Nightly Vacation Scan"
                required
                className="text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Target Folder Path *</label>
              <Input
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder="/data/images/vacation"
                required
                className="font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Path relative to root directory or full absolute path on server.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Schedule Preset</label>
                <Select
                  value={preset}
                  onChange={(e) => handlePresetChange(e.target.value)}
                  className="text-sm"
                >
                  {CRON_PRESETS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Cron Expression</label>
                <Input
                  value={cronExpr}
                  onChange={(e) => {
                    setCronExpr(e.target.value);
                    setPreset('custom');
                  }}
                  placeholder="0 * * * *"
                  className="font-mono text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Interval (Hours)</label>
                <Input
                  type="number"
                  step="0.5"
                  min="0.1"
                  value={intervalHours}
                  onChange={(e) => setIntervalHours(e.target.value)}
                  placeholder="e.g. 6"
                  className="text-sm"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Max Images (Optional)</label>
                <Input
                  type="number"
                  min="1"
                  value={maxImages}
                  onChange={(e) => setMaxImages(e.target.value)}
                  placeholder="Leave empty for all"
                  className="text-sm"
                />
              </div>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-accent/40 border border-border">
              <div className="space-y-0.5">
                <label className="text-sm font-medium text-foreground cursor-pointer">
                  Activate Immediately
                </label>
                <p className="text-xs text-muted-foreground">
                  Enable cron trigger as soon as schedule is saved.
                </p>
              </div>
              <Switch checked={isActive} onCheckedChange={setIsActive} />
            </div>

            <DialogFooter className="pt-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting} className="gap-1.5">
                {isSubmitting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                Save Schedule
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ScheduleTab;
