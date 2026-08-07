import React, { useEffect, useRef } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Terminal, Trash2 } from 'lucide-react';
import type { LogItem } from '@/types';

export interface LogOutputCardProps {
  logs: LogItem[];
  autoScroll: boolean;
  onAutoScrollChange: (autoScroll: boolean) => void;
  onClearLogs: () => void;
}

export const LogOutputCard: React.FC<LogOutputCardProps> = ({
  logs,
  autoScroll,
  onAutoScrollChange,
  onClearLogs,
}) => {
  const consoleContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && consoleContainerRef.current) {
      consoleContainerRef.current.scrollTop = consoleContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const getLogTextColor = (log: LogItem) => {
    const type = (log.level || log.type || 'info').toLowerCase();
    if (type.includes('error') || type.includes('err')) return 'text-rose-400';
    if (type.includes('warn')) return 'text-amber-400';
    if (type.includes('success')) return 'text-emerald-400';
    return 'text-slate-300';
  };

  return (
    <Card className="border-border shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-primary" />
            <div>
              <CardTitle>Console Output</CardTitle>
              <CardDescription className="mt-0.5">
                Live terminal log stream from the tagging engine.
              </CardDescription>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label htmlFor="autoScrollSwitch" className="text-xs text-muted-foreground cursor-pointer select-none">
                Auto-scroll
              </label>
              <Switch
                id="autoScrollSwitch"
                checked={autoScroll}
                onCheckedChange={onAutoScrollChange}
                aria-label="Toggle auto-scroll"
              />
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={onClearLogs}
              disabled={logs.length === 0}
              className="h-8 px-2.5 text-xs flex items-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
              Clear Log
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div
          ref={consoleContainerRef}
          className="h-80 w-full overflow-y-auto rounded-lg bg-slate-950 border border-slate-800 p-4 font-mono text-xs text-slate-200 select-text space-y-1 shadow-inner"
        >
          {logs.length === 0 ? (
            <div className="h-full flex items-center justify-center text-slate-500 font-mono text-xs italic">
              No logs captured yet. Start a session to view real-time log output.
            </div>
          ) : (
            logs.map((log, index) => (
              <div key={log.id !== undefined ? `${log.id}-${index}` : index} className="flex items-start gap-3 hover:bg-slate-900/50 py-0.5 px-1 rounded">
                <span className="text-slate-600 select-none w-10 text-right shrink-0 font-mono">
                  {String(index + 1).padStart(3, '0')}
                </span>
                <span className={`break-all ${getLogTextColor(log)}`}>
                  {log.text}
                </span>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
};

export default LogOutputCard;
