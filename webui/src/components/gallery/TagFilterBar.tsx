import React from 'react';
import { Tag, X, FilterX } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface TagFilterBarProps {
  allTags: string[];
  selectedTags: Set<string>;
  onToggleTag: (tag: string) => void;
  onClearFilters: () => void;
}

export const TagFilterBar: React.FC<TagFilterBarProps> = ({
  allTags,
  selectedTags,
  onToggleTag,
  onClearFilters,
}) => {
  const hasActiveFilters = selectedTags.size > 0;

  return (
    <div className="flex flex-col gap-2 p-3 rounded-lg border border-border bg-card/40">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Tag className="w-4 h-4 text-primary" />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Filter by Tags
          </span>
          {allTags.length > 0 && (
            <span className="text-xs px-1.5 py-0.2 rounded-full bg-secondary text-secondary-foreground">
              {allTags.length}
            </span>
          )}
        </div>

        {hasActiveFilters && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClearFilters}
            className="h-7 text-xs text-muted-foreground hover:text-destructive flex items-center gap-1 cursor-pointer"
          >
            <FilterX className="w-3.5 h-3.5" />
            Clear Filters ({selectedTags.size})
          </Button>
        )}
      </div>

      {allTags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 pt-1 max-h-36 overflow-y-auto pr-1">
          {allTags.map((tag) => {
            const isActive = selectedTags.has(tag);
            return (
              <Badge
                key={tag}
                variant={isActive ? 'default' : 'outline'}
                onClick={() => onToggleTag(tag)}
                className={`cursor-pointer rounded-full transition-all text-xs py-0.5 px-2.5 flex items-center gap-1 select-none ${
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90'
                    : 'bg-background hover:bg-accent text-foreground hover:border-primary/50'
                }`}
              >
                <span>#{tag}</span>
                {isActive && <X className="w-3 h-3 hover:opacity-80 shrink-0" />}
              </Badge>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic py-1">
          No tags found in gallery. Processing photos will extract tags automatically.
        </p>
      )}
    </div>
  );
};

export default TagFilterBar;
