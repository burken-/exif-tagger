import React, { useState } from 'react';
import { Tags, Plus, Minus, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/layout/ToastContainer';

interface BatchTagPanelProps {
  selectedCount: number;
  allTags: string[];
  onApplyBatchTags: (addTags: string[], removeTags: string[]) => Promise<{ success: boolean; modified?: number; error?: string }>;
}

export const BatchTagPanel: React.FC<BatchTagPanelProps> = ({
  selectedCount,
  allTags,
  onApplyBatchTags,
}) => {
  const [addInput, setAddInput] = useState('');
  const [removeInput, setRemoveInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { showToast } = useToast();

  const handleApply = async () => {
    if (selectedCount === 0) {
      showToast('No images selected. Please select at least one image.', 'warning');
      return;
    }

    const addTags = addInput
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);

    const removeTags = removeInput
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);

    if (addTags.length === 0 && removeTags.length === 0) {
      showToast('Specify at least one tag to add or remove.', 'warning');
      return;
    }

    setIsSubmitting(true);
    showToast(`Updating tags for ${selectedCount} selected image(s)...`, 'info');

    try {
      const result = await onApplyBatchTags(addTags, removeTags);
      if (result.success) {
        showToast(`Successfully updated ${result.modified ?? selectedCount} image(s)!`, 'success');
        setAddInput('');
        setRemoveInput('');
      } else {
        showToast(result.error || 'Batch tag update failed', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Error executing batch tag update', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Tags className="w-4 h-4 text-primary" />
            <CardTitle className="text-base font-semibold">Batch Tag Operations</CardTitle>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium transition-colors ${
            selectedCount > 0
              ? 'bg-primary/20 text-primary font-semibold'
              : 'bg-muted text-muted-foreground'
          }`}>
            {selectedCount} selected
          </span>
        </div>
        <CardDescription className="text-xs">
          Add or remove tags simultaneously across all selected images.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {/* Add Tags Input */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <Plus className="w-3.5 h-3.5 text-emerald-500" />
              Add Tags (comma-separated)
            </label>
            <Input
              type="text"
              list="existing-tags-datalist"
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="e.g. landscape, summer, nature"
              className="text-xs h-9"
            />
          </div>

          {/* Remove Tags Input */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <Minus className="w-3.5 h-3.5 text-rose-500" />
              Remove Tags (comma-separated)
            </label>
            <Input
              type="text"
              list="existing-tags-datalist"
              value={removeInput}
              onChange={(e) => setRemoveInput(e.target.value)}
              placeholder="e.g. draft, blurry"
              className="text-xs h-9"
            />
          </div>
        </div>

        {/* Global Datalist for existing tags */}
        <datalist id="existing-tags-datalist">
          {(allTags || []).map((tag) => (
            <option key={tag} value={tag} />
          ))}
        </datalist>

        <Button
          type="button"
          onClick={handleApply}
          disabled={selectedCount === 0 || isSubmitting}
          className="w-full sm:w-auto text-xs h-9 gap-1.5"
        >
          <CheckCircle2 className="w-4 h-4" />
          {isSubmitting ? 'Applying...' : 'Apply Batch Tags'}
        </Button>
      </CardContent>
    </Card>
  );
};

export default BatchTagPanel;
