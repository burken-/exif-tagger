import React from 'react';
import { CheckSquare, Square, Image as ImageIcon, Loader2 } from 'lucide-react';
import type { GalleryImage } from '@/types';
import { ImageCard } from './ImageCard';
import { Button } from '@/components/ui/button';

interface ImageGridProps {
  images: GalleryImage[];
  selectedImageIds: Set<number>;
  onToggleSelect: (id: number, checked?: boolean) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onImageClick: (image: GalleryImage) => void;
  loading: boolean;
}

export const ImageGrid: React.FC<ImageGridProps> = ({
  images,
  selectedImageIds,
  onToggleSelect,
  onSelectAll,
  onDeselectAll,
  onImageClick,
  loading,
}) => {
  const selectedOnPage = images.filter((img) => selectedImageIds.has(img.id)).length;

  return (
    <div className="space-y-3">
      {/* Selection Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-lg border border-border bg-card/40 text-xs">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onSelectAll}
            disabled={images.length === 0}
            className="h-7 text-xs gap-1.5"
          >
            <CheckSquare className="w-3.5 h-3.5" />
            Select All
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDeselectAll}
            disabled={selectedOnPage === 0}
            className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
          >
            <Square className="w-3.5 h-3.5" />
            Deselect All
          </Button>
        </div>

        <div className="text-muted-foreground font-medium">
          Selected on page:{' '}
          <span className="text-foreground font-bold">{selectedOnPage}</span> / {images.length}
        </div>
      </div>

      {/* Loading state */}
      {loading ? (
        <div className="flex flex-col items-center justify-center min-h-[300px] border border-dashed border-border rounded-lg bg-card/20 py-16">
          <Loader2 className="w-8 h-8 text-primary animate-spin mb-3" />
          <p className="text-sm font-medium text-muted-foreground">Loading images...</p>
        </div>
      ) : images.length > 0 ? (
        /* Image Grid */
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {images.map((image) => (
            <ImageCard
              key={image.id}
              image={image}
              isSelected={selectedImageIds.has(image.id)}
              onToggleSelect={onToggleSelect}
              onClick={onImageClick}
            />
          ))}
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center min-h-[300px] border border-dashed border-border rounded-lg bg-card/20 py-16 text-center">
          <ImageIcon className="w-12 h-12 text-muted-foreground/40 mb-3 stroke-1" />
          <p className="text-base font-semibold text-foreground">No images found</p>
          <p className="text-xs text-muted-foreground max-w-sm mt-1">
            No photos matched your current search filters or folder scope. Try clearing your filters or changing directory.
          </p>
        </div>
      )}
    </div>
  );
};

export default ImageGrid;
