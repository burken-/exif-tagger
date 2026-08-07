import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Folder, Play, Square, Hash } from 'lucide-react';

export interface SessionCardProps {
  folderPath: string;
  onFolderPathChange: (path: string) => void;
  maxImages: number | null;
  onMaxImagesChange: (max: number | null) => void;
  isRunning: boolean;
  onStart: () => void;
  onStop: () => void;
}

export const SessionCard: React.FC<SessionCardProps> = ({
  folderPath,
  onFolderPathChange,
  maxImages,
  onMaxImagesChange,
  isRunning,
  onStart,
  onStop,
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isRunning) {
      onStart();
    }
  };

  const handleMaxImagesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (val === '') {
      onMaxImagesChange(null);
    } else {
      const num = parseInt(val, 10);
      onMaxImagesChange(isNaN(num) ? null : Math.max(1, num));
    }
  };

  return (
    <Card className="border-border shadow-sm">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Folder className="w-5 h-5 text-primary" />
          <CardTitle>Session Control</CardTitle>
        </div>
        <CardDescription>
          Configure target directory path and maximum image processing limits.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label htmlFor="folderPath" className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Folder className="w-4 h-4 text-muted-foreground" />
                Folder Path
              </label>
              <Input
                id="folderPath"
                type="text"
                value={folderPath}
                onChange={(e) => onFolderPathChange(e.target.value)}
                placeholder="/data/images/this-month"
                disabled={isRunning}
              />
              <p className="text-xs text-muted-foreground">
                Target directory path containing images to process.
              </p>
            </div>

            <div className="space-y-2">
              <label htmlFor="maxImages" className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Hash className="w-4 h-4 text-muted-foreground" />
                Max Images
              </label>
              <Input
                id="maxImages"
                type="number"
                min={1}
                value={maxImages === null ? '' : maxImages}
                onChange={handleMaxImagesChange}
                placeholder="Optional limit (e.g. 100)"
                disabled={isRunning}
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to process all images in directory.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <Button
              type="submit"
              variant="default"
              disabled={isRunning}
              className="flex items-center gap-2"
            >
              <Play className="w-4 h-4" />
              Start Processing
            </Button>

            <Button
              type="button"
              variant="destructive"
              disabled={!isRunning}
              onClick={onStop}
              className="flex items-center gap-2"
            >
              <Square className="w-4 h-4" />
              Stop Processing
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};

export default SessionCard;
