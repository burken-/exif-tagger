import React, { useState } from 'react';
import { Image as ImageIcon, SlidersHorizontal, RefreshCw, Info } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useGallery } from '@/hooks/useGallery';
import { useToast } from '@/components/layout/ToastContainer';
import { FolderBreadcrumbs } from './FolderBreadcrumbs';
import { FolderSelectModal } from './FolderSelectModal';
import { TagFilterBar } from './TagFilterBar';
import { GalleryToolbar } from './GalleryToolbar';
import { BatchTagPanel } from './BatchTagPanel';
import { GlobalRemoveTagPanel } from './GlobalRemoveTagPanel';
import { ImageGrid } from './ImageGrid';
import { ImageDetailModal } from './ImageDetailModal';
import { PaginationFooter } from './PaginationFooter';

export const GalleryTab: React.FC = () => {
  const {
    images,
    allTags,
    selectedTags,
    selectedImageIds,
    currentFolder,
    searchQuery,
    currentPage,
    pageSize,
    totalImages,
    folders,
    modalFolder,
    folderBreadcrumbs,
    selectedImageDetail,
    isSyncing,
    loading,
    error,
    fetchFolders,
    toggleTagFilter,
    clearTagFilters,
    toggleImageSelection,
    selectAllOnPage,
    deselectAllOnPage,
    applyBatchTags,
    removeTagGlobal,
    updateSingleImageTags,
    fetchImageDetail,
    clearImageDetail,
    syncGalleryIndex,
    setCurrentFolder,
    setSearchQuery,
    setCurrentPage,
    setPageSize,
  } = useGallery();

  const { showToast } = useToast();
  const [isFolderModalOpen, setIsFolderModalOpen] = useState(false);
  const [showManagementPanels, setShowManagementPanels] = useState(true);

  const handleOpenFolderModal = () => {
    fetchFolders(currentFolder);
    setIsFolderModalOpen(true);
  };

  const handleSyncIndex = async () => {
    showToast('Syncing gallery index with disk...', 'info');
    const res = await syncGalleryIndex();
    if (res.success) {
      showToast(
        `Gallery index sync complete! Total: ${res.stats?.total || 0}, Updated: ${res.stats?.updated || 0}`,
        'success'
      );
    } else {
      showToast(res.error || 'Gallery sync failed', 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* Main Gallery Container Card */}
      <Card className="border-border">
        <CardHeader className="pb-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-primary" />
                <CardTitle className="text-xl">Image Gallery</CardTitle>
              </div>
              <CardDescription>
                Browse images, filter by tags, and manage EXIF tags across your library.
              </CardDescription>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleSyncIndex}
                disabled={isSyncing}
                className="flex items-center gap-2 shrink-0 h-9"
              >
                <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin text-primary' : ''}`} />
                <span>{isSyncing ? 'Syncing...' : 'Sync Index'}</span>
              </Button>

              <button
                type="button"
                onClick={() => setShowManagementPanels((prev) => !prev)}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border bg-card hover:bg-accent transition-colors cursor-pointer h-9"
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                <span>{showManagementPanels ? 'Hide Tag Management' : 'Show Tag Management'}</span>
              </button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Top Info Banner when totalImages === 0 && !isSyncing && !loading */}
          {totalImages === 0 && !isSyncing && !loading && (
            <div className="flex items-start gap-3 p-4 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-indigo-200 text-sm">
              <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-indigo-100">No images indexed yet</p>
                <p className="text-xs text-indigo-200/80 mt-0.5">
                  Click <strong>Sync Index</strong> in the top right header to scan your library directory and populate the gallery index.
                </p>
              </div>
            </div>
          )}

          {/* Folder Scope Navigation */}
          <FolderBreadcrumbs
            currentFolder={currentFolder}
            onSelectFolder={setCurrentFolder}
            onOpenModal={handleOpenFolderModal}
          />

          {/* Search Toolbar */}
          <GalleryToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
          />

          {/* Active Tag Filter Badges */}
          <TagFilterBar
            allTags={allTags}
            selectedTags={selectedTags}
            onToggleTag={toggleTagFilter}
            onClearFilters={clearTagFilters}
          />

          {/* Batch Operations & Global Purge Panels */}
          {showManagementPanels && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <BatchTagPanel
                selectedCount={selectedImageIds.size}
                allTags={allTags}
                onApplyBatchTags={applyBatchTags}
              />
              <GlobalRemoveTagPanel
                allTags={allTags}
                onRemoveTagGlobal={removeTagGlobal}
              />
            </div>
          )}

          {/* Error Banner if any */}
          {error && (
            <div className="p-3 rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-xs">
              <strong>Error:</strong> {error}
            </div>
          )}

          {/* Image Grid with Selection Controls */}
          <ImageGrid
            images={images}
            selectedImageIds={selectedImageIds}
            onToggleSelect={toggleImageSelection}
            onSelectAll={selectAllOnPage}
            onDeselectAll={deselectAllOnPage}
            onImageClick={(img) => fetchImageDetail(img.id)}
            loading={loading}
            totalImages={totalImages}
            hasActiveFilters={Boolean(searchQuery || selectedTags.size > 0 || currentFolder)}
            onSync={handleSyncIndex}
            isSyncing={isSyncing}
            onClearFilters={() => {
              clearTagFilters();
              setCurrentFolder('');
            }}
          />

          {/* Pagination Footer */}
          <PaginationFooter
            currentPage={currentPage}
            pageSize={pageSize}
            totalImages={totalImages}
            onPageChange={setCurrentPage}
            onPageSizeChange={setPageSize}
          />
        </CardContent>
      </Card>

      {/* Folder Selection Dialog */}
      <FolderSelectModal
        open={isFolderModalOpen}
        onOpenChange={setIsFolderModalOpen}
        currentModalFolder={modalFolder}
        folders={folders}
        breadcrumbs={folderBreadcrumbs}
        onNavigate={(path) => fetchFolders(path)}
        onSelectFolder={setCurrentFolder}
      />

      {/* Single Image Detail Modal */}
      <ImageDetailModal
        image={selectedImageDetail}
        open={selectedImageDetail !== null}
        onClose={clearImageDetail}
        onUpdateTags={updateSingleImageTags}
        allTags={allTags}
      />
    </div>
  );
};

export default GalleryTab;
