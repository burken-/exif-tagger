# Unfiltered Folder Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure the folder browser widget in both Processing and Gallery tabs displays all available folders on disk without filtering and opens directly at the currently selected directory path.

**Architecture:** Update backend `get_gallery_folders` in `db.py` to scan the physical filesystem under `root_directory / relative_path` and merge DB image counts, returning all subdirectories (including unindexed ones with count 0). Update frontend `ProcessingTab.tsx` and `GalleryTab.tsx` to pass the currently selected folder path when opening the `FolderSelectModal`.

**Tech Stack:** Python 3.12, FastAPI, SQLite, React, TypeScript, Vite, TailwindCSS

## Global Constraints
- Python tests must be run using `.venv/bin/pytest`.
- Web UI build must be verified with `npm --prefix webui run build`.

---

### Task 1: Backend Unfiltered Folder Discovery (`get_gallery_folders`)

**Files:**
- Modify: `src/exif_tagger/db.py:350-400`
- Test: `tests/test_gallery_folders_and_glob.py`

**Interfaces:**
- Produces: `get_gallery_folders(relative_path: str = "", db_path: str | Path | None = None, root_directory: str | Path | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test for unindexed subdirectories**

Update `tests/test_gallery_folders_and_glob.py` to test that a physical folder on disk containing 0 indexed images in DB is included in `get_gallery_folders` output.

```python
def test_get_gallery_folders_unindexed_folders(tmp_path: Path):
    db_file = tmp_path / "test_gallery.db"
    init_db(db_file)

    root = tmp_path / "gallery"
    root.mkdir()

    # Create folders on disk
    (root / "indexed_folder").mkdir()
    (root / "empty_unindexed_folder").mkdir()

    img1 = root / "indexed_folder" / "photo.jpg"
    Image.new("RGB", (50, 50), color="blue").save(img1, format="JPEG")

    sync_gallery_index(root_directory=root, db_path=db_file)

    # Now create an extra unindexed subfolder after sync
    (root / "new_unindexed_dir").mkdir()

    res = get_gallery_folders(relative_path="", db_path=db_file, root_directory=root)
    folder_names = [f["name"] for f in res["folders"]]
    
    assert "indexed_folder" in folder_names
    assert "empty_unindexed_folder" in folder_names
    assert "new_unindexed_dir" in folder_names

    unindexed_item = next(f for f in res["folders"] if f["name"] == "new_unindexed_dir")
    assert unindexed_item["image_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gallery_folders_and_glob.py -k test_get_gallery_folders_unindexed_folders`
Expected: FAIL (assertion error because `empty_unindexed_folder` or `new_unindexed_dir` is missing from `res["folders"]`).

- [ ] **Step 3: Update `get_gallery_folders` in `src/exif_tagger/db.py`**

Modify `get_gallery_folders` in `src/exif_tagger/db.py` to accept `root_directory: str | Path | None = None`, scan physical disk directories, and merge DB counts:

```python
def get_gallery_folders(
    relative_path: str = "",
    db_path: str | Path | None = None,
    root_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Get all subdirectories under relative_path (from disk and DB) with image count badges."""
    from exif_tagger.config import load_config

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_rel = relative_path.strip().strip("/").replace("\\", "/")
        if clean_rel == ".":
            clean_rel = ""

        # Determine root directory on disk
        if root_directory is None:
            config = load_config()
            root_directory = config.root_directory

        root_path = Path(root_directory).resolve()
        target_dir = (root_path / clean_rel).resolve() if clean_rel else root_path

        all_subfolders: set[str] = set()
        subfolders_count: dict[str, int] = {}

        # 1. Physical disk scan
        if target_dir.exists() and target_dir.is_dir():
            for item in target_dir.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    all_subfolders.add(item.name)

        # 2. DB scan for image counts and DB-known folders
        rows = conn.execute("SELECT relative_path FROM images").fetchall()
        for r in rows:
            rel_p = r["relative_path"].replace("\\", "/")
            parts = [p for p in rel_p.split("/") if p]

            if not clean_rel:
                if len(parts) > 1:
                    child_folder = parts[0]
                    all_subfolders.add(child_folder)
                    subfolders_count[child_folder] = subfolders_count.get(child_folder, 0) + 1
            else:
                rel_parts = [p for p in clean_rel.split("/") if p]
                depth = len(rel_parts)
                if len(parts) > depth + 1 and [p.lower() for p in parts[:depth]] == [p.lower() for p in rel_parts]:
                    child_folder = parts[depth]
                    all_subfolders.add(child_folder)
                    subfolders_count[child_folder] = subfolders_count.get(child_folder, 0) + 1

        folders_list = []
        for name in sorted(all_subfolders):
            full_path = f"{clean_rel}/{name}" if clean_rel else name
            folders_list.append({
                "name": name,
                "relative_path": full_path,
                "image_count": subfolders_count.get(name, 0),
            })

        breadcrumbs = [{"name": "Root", "path": ""}]
        if clean_rel:
            accum = []
            for part in clean_rel.split("/"):
                accum.append(part)
                breadcrumbs.append({"name": part, "path": "/".join(accum)})

        return {
            "current_path": clean_rel,
            "breadcrumbs": breadcrumbs,
            "folders": folders_list,
            "total_images": len(rows),
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run pytest to verify all tests pass**

Run: `.venv/bin/pytest tests/test_gallery_folders_and_glob.py`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add src/exif_tagger/db.py tests/test_gallery_folders_and_glob.py
git commit -m "feat: scan disk directories in get_gallery_folders for unfiltered folder navigation"
```

---

### Task 2: Frontend Folder Picker Path Memory (`ProcessingTab` & `GalleryTab`)

**Files:**
- Modify: `webui/src/components/processing/ProcessingTab.tsx:36-39`
- Modify: `webui/src/components/gallery/GalleryTab.tsx:57-60`

**Interfaces:**
- Consumes: `fetchFolders(path: string)` hook method from `useProcessing` / `useGallery`.

- [ ] **Step 1: Update `ProcessingTab.tsx` to pass `folderPath` when browsing**

In `webui/src/components/processing/ProcessingTab.tsx`, update `handleBrowseFolders`:

```tsx
  const handleBrowseFolders = () => {
    fetchFolders(folderPath);
    setIsFolderModalOpen(true);
  };
```

- [ ] **Step 2: Update `GalleryTab.tsx` to handle `currentFolder` properly when browsing**

In `webui/src/components/gallery/GalleryTab.tsx`, verify `handleOpenFolderModal`:

```tsx
  const handleOpenFolderModal = () => {
    fetchFolders(currentFolder || '');
    setIsFolderModalOpen(true);
  };
```

- [ ] **Step 3: Run webui build to verify compilation**

Run: `npm --prefix webui run build`
Expected: Successful Vite build without TypeScript errors.

- [ ] **Step 4: Run complete pytest suite**

Run: `.venv/bin/pytest`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit changes**

```bash
git add webui/src/components/processing/ProcessingTab.tsx webui/src/components/gallery/GalleryTab.tsx
git commit -m "fix: pass active folder path when opening folder browser modal"
```
