# Design Spec: Gallery UI/UX Improvements & Deep Linking

**Date**: 2026-08-07  
**Author**: Antigravity AI  
**Status**: Proposed

---

## 1. Overview

This document specifies UI and backend enhancements for the **Image Gallery** tab in `exif-tagger`. The improvements aim to make navigating large photo libraries effortless, fast, and intuitive.

---

## 2. Requirements & Key Features

### 2.1 Folder Navigation & Tree Explorer
- **Folder Selector Banner & Modal**:
  - Display active folder path with interactive breadcrumbs: `📁 Root / Vacation / 2024 [ Select Folder ]`.
  - Clicking "Select Folder" opens a modal displaying subfolders with image count badges.
  - Selecting a folder filters gallery results strictly to that directory scope (`relative_path`).

### 2.2 Glob Pattern Search Filtering
- Support Unix-style glob patterns in the search input (e.g. `*.jpg`, `vacation/**/*.png`, `DSC_0[1-5]*.JPG`).
- Backend `get_gallery_images()` handles both standard substring search and glob wildcard matching (`fnmatch` / SQLite `GLOB`).

### 2.3 Repositioned Selection Toolbar
- Move `[ Select All (Page) ]` and `[ Deselect All ]` buttons out of the top search bar into a dedicated action toolbar directly above the `#gallery-grid`.
- Include active selection counter: `X images selected`.

### 2.4 Aligned Global Tag Removal Form
- Fix visual layout alignment of "Remove Tag Globally" text box and action button using aligned flexbox structure.

### 2.5 Google-Style Page Navigation & URL Deep Linking
- **Numbered Pagination**: Render page buttons `[1] [2] [3] ... [N]`, `[< Prev]`, `[Next >]`, and direct page jump input box.
- **URL Hash Deep Linking & Browser History**:
  - Update `window.location.hash` on navigation:  
    `#gallery?folder=vacation/2024&search=*.jpg&tags=nature&page=2&limit=48`
  - Support `hashchange` / `popstate` events so browser Back and Forward buttons navigate history, and links can be shared directly.

### 2.6 Additional UX Enhancements
- Page size selector: `Show [ 24 | 48 | 96 | 192 ] images`.
- Image hover badges & selection highlights.

---

## 3. Architecture & API Specifications

### 3.1 Backend Folder Endpoint (`GET /api/gallery/folders`)
- **Query Params**: `path` (optional relative folder path, defaults to `""`).
- **Response**:
```json
{
  "current_path": "vacation",
  "breadcrumbs": [
    {"name": "Root", "path": ""},
    {"name": "vacation", "path": "vacation"}
  ],
  "folders": [
    {"name": "2024", "relative_path": "vacation/2024", "image_count": 42},
    {"name": "2025", "relative_path": "vacation/2025", "image_count": 18}
  ],
  "total_images": 60
}
```

### 3.2 Enhanced Image Query Endpoint (`GET /api/gallery/images`)
- **New Query Params**:
  - `folder`: Scopes query to images within directory (`relative_path LIKE 'folder/%'`).
  - `glob`: Bool flag or automatic detection of glob characters (`*`, `?`, `[`).
  - `limit`: Dynamic page size (default 48).

---

## 4. Verification Strategy

1. **Backend Unit Tests (`tests/test_gallery_folders_and_glob.py`)**:
   - Test folder listing API endpoint.
   - Test glob pattern search filtering in database.
   - Test folder scoping query.
2. **UI Manual Verification**:
   - Verify folder selector modal & breadcrumbs navigation.
   - Verify selection buttons above grid.
   - Verify Google-style page navigation and URL deep linking with back/forward history.
