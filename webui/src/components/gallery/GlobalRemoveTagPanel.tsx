import React, { useState } from 'react';
import { Trash2, AlertTriangle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/layout/ToastContainer';

interface GlobalRemoveTagPanelProps {
  allTags: string[];
  onRemoveTagGlobal: (tagName: string) => Promise<{ success: boolean; modified?: number; error?: string }>;
}

export const GlobalRemoveTagPanel: React.FC<GlobalRemoveTagPanelProps> = ({
  allTags,
  onRemoveTagGlobal,
}) => {
  const [tagName, setTagName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { showToast } = useToast();

  const handleGlobalRemove = async () => {
    const trimmed = tagName.trim().toLowerCase();
    if (!trimmed) {
      showToast('Please enter a tag name to remove globally.', 'warning');
      return;
    }

    const confirmed = window.confirm(
      `Are you sure you want to remove tag "${trimmed}" from ALL photos in your entire library?`
    );
    if (!confirmed) return;

    setIsSubmitting(true);
    showToast(`Removing tag "${trimmed}" globally from library...`, 'info');

    try {
      const result = await onRemoveTagGlobal(trimmed);
      if (result.success) {
        showToast(
          `Successfully removed tag "${trimmed}" from ${result.modified ?? 0} photo(s)!`,
          'success'
        );
        setTagName('');
      } else {
        showToast(result.error || 'Global tag removal failed', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Error removing tag globally', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card className="border-destructive/30 bg-card/60">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2 text-destructive">
          <Trash2 className="w-4 h-4" />
          <CardTitle className="text-base font-semibold text-foreground">
            Global Tag Removal
          </CardTitle>
        </div>
        <CardDescription className="text-xs">
          Permanently strip a tag from every single image in your gallery and EXIF database.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
          <div className="relative flex-1">
            <Input
              type="text"
              list="global-existing-tags-datalist"
              value={tagName}
              onChange={(e) => setTagName(e.target.value)}
              placeholder="Type tag to purge globally (e.g. legacy-tag)"
              className="text-xs h-9"
            />
            <datalist id="global-existing-tags-datalist">
              {(allTags || []).map((tag) => (
                <option key={tag} value={tag} />
              ))}
            </datalist>
          </div>

          <Button
            type="button"
            variant="destructive"
            onClick={handleGlobalRemove}
            disabled={!tagName.trim() || isSubmitting}
            className="text-xs h-9 gap-1.5 shrink-0"
          >
            <AlertTriangle className="w-4 h-4" />
            {isSubmitting ? 'Purging...' : 'Remove Tag Globally'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export default GlobalRemoveTagPanel;
