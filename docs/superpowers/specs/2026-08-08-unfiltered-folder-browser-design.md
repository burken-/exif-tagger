# Design Spec: Unfiltered Folder Browser with Path Memory

## Overview
This specification details the changes required to ensure all folder browser widgets across the application (in both the Processing tab and Gallery tab) display **all available folders on disk** without filtering, and open directly at the **currently selected directory** (or root if none selected).

## Problems Addressed
1. **Filtered Folders**: The backend `get_gallery_folders` endpoint only retrieved subfolders present in the `images` SQLite database table (`SELECT relative_path FROM images`). Folders on disk that had not been processed yet, contained no indexed images, or were empty were completely omitted from the folder browser.
2. **Initial Path Reset**: Opening the folder browser on the Processing tab called `fetchFolders('')`, forcing the modal to open at root (`""`) instead of starting at the path currently in `folderPath`.

## Requirements

### 1. Backend: Unfiltered Folder Discovery (`get_gallery_folders`)
- **Location**: `src/exif_tagger/db.py` (`get_gallery_folders`) and `src/exif_tagger/server.py` (`/api/gallery/folders`).
- **Disk Scan**: Locate the physical path corresponding to `root_directory / relative_path`. If the directory exists on disk, list all subdirectories (`item.is_dir()`), excluding hidden system directories starting with `.`.
- **Database Count Merge**: Query SQLite `images` table for image counts under the given `relative_path`.
- **Combined List**: Combine physical subdirectories on disk and subdirectories in the DB into a single sorted list of `FolderItem` objects.
  - Each item includes `name`, `relative_path`, and `image_count` (0 if no indexed images in DB).
  - No folders on disk are filtered out.
- **Breadcrumbs**: Compute breadcrumbs for the current path from Root (`""`) down to `relative_path`.

### 2. Frontend: Open Browser at Currently Selected Path
- **Processing Tab (`ProcessingTab.tsx`)**:
  - Update `handleBrowseFolders` to pass the current `folderPath` to `fetchFolders(folderPath)`.
  - When the user clicks "Browse Folders", `fetchFolders` will request `/api/gallery/folders?path=<folderPath>`.
  - The modal will open showing the breadcrumbs and subfolders at `folderPath`, allowing the user to navigate up to parent folders or down into subfolders.
- **Gallery Tab (`GalleryTab.tsx`)**:
  - `handleOpenFolderModal` already passes `currentFolder` to `fetchFolders(currentFolder)`. Ensure that when `currentFolder` is empty, it correctly passes `""` (Root).
- **Folder Select Modal (`FolderSelectModal.tsx`)**:
  - Continues to render breadcrumbs for `currentModalFolder` and the list of subfolders.

## Component Flow & Data Model

```
[User Clicks 'Browse Folders'] 
          │
          ▼
[ProcessingTab / GalleryTab] ──(Pass current path)──► [fetchFolders(path)]
                                                             │
                                                             ▼
                                                    GET /api/gallery/folders?path=...
                                                             │
                                                             ▼
                                                    [server.py / db.py]
                                                    - Resolve root_directory + path
                                                    - Read physical dirs on disk
                                                    - Count DB images
                                                    - Merge & sort
                                                             │
                                                             ▼
                                              [FolderSelectModal rendered at path]
                                              - Breadcrumbs: Root > path
                                              - Subfolders listed (including 0 image_count)
```

## Testing & Verification
1. **Unit Tests (`tests/test_gallery_folders_and_glob.py`)**:
   - Verify `get_gallery_folders` returns subdirectories on disk even if they contain 0 images in the database.
   - Verify breadcrumb generation for nested paths on disk.
2. **Frontend Tests**:
   - Verify modal opens at the current `folderPath` / `currentFolder` value.
