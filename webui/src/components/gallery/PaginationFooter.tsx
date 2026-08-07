import React, { useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';

interface PaginationFooterProps {
  currentPage: number;
  pageSize: number;
  totalImages: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}

export const PaginationFooter: React.FC<PaginationFooterProps> = ({
  currentPage,
  pageSize,
  totalImages,
  onPageChange,
  onPageSizeChange,
}) => {
  const totalPages = Math.ceil(totalImages / pageSize) || 1;
  const [jumpValue, setJumpValue] = useState(String(currentPage));

  useEffect(() => {
    setJumpValue(String(currentPage));
  }, [currentPage]);

  // Compute pages to display (Google-style numbered pagination)
  const getPageNumbers = () => {
    const pages: (number | string)[] = [];
    const current = currentPage;

    pages.push(1);

    const start = Math.max(2, current - 2);
    const end = Math.min(totalPages - 1, current + 2);

    if (start > 2) {
      pages.push('...');
    }

    for (let i = start; i <= end; i++) {
      pages.push(i);
    }

    if (end < totalPages - 1) {
      pages.push('...');
    }

    if (totalPages > 1) {
      pages.push(totalPages);
    }

    return Array.from(new Set(pages));
  };

  const handleJumpSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseInt(jumpValue, 10);
    if (!isNaN(parsed) && parsed >= 1 && parsed <= totalPages) {
      onPageChange(parsed);
    } else {
      setJumpValue(String(currentPage));
    }
  };

  const startItem = totalImages > 0 ? (currentPage - 1) * pageSize + 1 : 0;
  const endItem = Math.min(currentPage * pageSize, totalImages);

  return (
    <div className="flex flex-col md:flex-row items-center justify-between gap-4 p-4 rounded-lg border border-border bg-card/60 text-xs">
      {/* Page Info */}
      <div className="text-muted-foreground font-medium">
        Showing <span className="text-foreground font-semibold">{startItem}</span> -{' '}
        <span className="text-foreground font-semibold">{endItem}</span> of{' '}
        <span className="text-foreground font-semibold">{totalImages}</span> images
      </div>

      {/* Center: Numbered Page Buttons & Prev/Next */}
      <div className="flex items-center gap-1.5 flex-wrap justify-center">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className="h-8 px-2 text-xs"
          aria-label="Previous Page"
        >
          <ChevronLeft className="w-4 h-4" />
          <span className="hidden sm:inline ml-1">Prev</span>
        </Button>

        <div className="flex items-center gap-1">
          {getPageNumbers().map((p, idx) => {
            if (p === '...') {
              return (
                <span key={`ellipsis-${idx}`} className="px-1.5 text-muted-foreground select-none">
                  ...
                </span>
              );
            }

            const pageNum = p as number;
            const isActive = pageNum === currentPage;

            return (
              <Button
                key={pageNum}
                type="button"
                variant={isActive ? 'default' : 'outline'}
                size="sm"
                onClick={() => onPageChange(pageNum)}
                className={`h-8 w-8 p-0 text-xs font-medium ${
                  isActive ? 'bg-primary text-primary-foreground font-bold' : ''
                }`}
              >
                {pageNum}
              </Button>
            );
          })}
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className="h-8 px-2 text-xs"
          aria-label="Next Page"
        >
          <span className="hidden sm:inline mr-1">Next</span>
          <ChevronRight className="w-4 h-4" />
        </Button>
      </div>

      {/* Right Controls: Page Jump & Page Size */}
      <div className="flex items-center gap-3">
        {/* Page Jump Form */}
        <form onSubmit={handleJumpSubmit} className="flex items-center gap-1">
          <span className="text-muted-foreground whitespace-nowrap">Go to:</span>
          <Input
            type="number"
            min={1}
            max={totalPages}
            value={jumpValue}
            onChange={(e) => setJumpValue(e.target.value)}
            className="h-8 w-14 text-xs text-center px-1"
          />
        </form>

        {/* Per-Page Selector */}
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground whitespace-nowrap">Per page:</span>
          <Select
            value={String(pageSize)}
            onChange={(e) => onPageSizeChange(parseInt(e.target.value, 10))}
            className="h-8 w-16 text-xs px-2"
          >
            <option value="24">24</option>
            <option value="48">48</option>
            <option value="96">96</option>
            <option value="192">192</option>
          </Select>
        </div>
      </div>
    </div>
  );
};

export default PaginationFooter;
