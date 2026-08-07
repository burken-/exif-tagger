"""SQLite database module for indexing and querying images and their XPTags.

Provides fast database indexing of photos in gallery root directory for web UI gallery browsing,
filtering by tags, single image tag editing, batch tag updates, and global tag removal.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from exif_tagger.exif_writer import get_existing_xptags, set_xptags
from exif_tagger.image_scanner import scan_images

logger = logging.getLogger(__name__)

_config_dir = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = _config_dir / "gallery.db"


def get_db_path(custom_path: str | Path | None = None) -> Path:
    """Resolve SQLite database path from param, env var, or default location."""
    if custom_path:
        return Path(custom_path)
    env_path = os.environ.get("EXIFTAGGER_DB_FILE")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a SQLite database connection with row factory enabled."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: str | Path | None = None) -> None:
    """Initialize SQLite database tables and indices if they do not exist."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    last_modified REAL NOT NULL,
                    indexed_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS image_tags (
                    image_id INTEGER NOT NULL,
                    tag_name TEXT NOT NULL,
                    PRIMARY KEY (image_id, tag_name),
                    FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_path ON images(file_path);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_tag_name ON image_tags(tag_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_image_tags_image_id ON image_tags(image_id);")
    finally:
        conn.close()


def sync_gallery_index(
    root_directory: str | Path,
    exclude_patterns: list[str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Scan root_directory and sync database with image metadata and EXIF XPTags.

    Returns stats dict: {"total": int, "indexed": int, "updated": int, "deleted": int}.
    """
    init_db(db_path)
    root = Path(root_directory).resolve()
    if not root.exists() or not root.is_dir():
        logger.warning("sync_gallery_index: invalid root directory: %s", root_directory)
        return {"total": 0, "indexed": 0, "updated": 0, "deleted": 0}

    scanned_paths = scan_images(root, exclude_patterns=exclude_patterns)
    scanned_map = {str(p.resolve()): p for p in scanned_paths}

    conn = get_connection(db_path)
    updated_count = 0
    deleted_count = 0

    from datetime import UTC, datetime

    try:
        with conn:
            # 1. Purge records for files that no longer exist or are no longer in scanned set
            existing_rows = conn.execute("SELECT id, file_path, last_modified FROM images").fetchall()
            existing_db_map = {row["file_path"]: row for row in existing_rows}

            for db_file_path, row in existing_db_map.items():
                if db_file_path not in scanned_map or not Path(db_file_path).exists():
                    conn.execute("DELETE FROM images WHERE id = ?", (row["id"],))
                    deleted_count += 1

            # 2. Insert or update scanned images
            for abs_path_str, img_path in scanned_map.items():
                try:
                    mtime = img_path.stat().st_mtime
                except OSError:
                    continue

                db_entry = existing_db_map.get(abs_path_str)
                needs_update = db_entry is None or abs(db_entry["last_modified"] - mtime) > 0.001

                if needs_update:
                    try:
                        rel_path = img_path.relative_to(root).as_posix()
                    except ValueError:
                        rel_path = img_path.name

                    exif_tags = get_existing_xptags(img_path)
                    now_iso = datetime.now(UTC).isoformat()

                    if db_entry is None:
                        cursor = conn.execute(
                            """
                            INSERT INTO images (file_path, filename, relative_path, last_modified, indexed_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (abs_path_str, img_path.name, rel_path, mtime, now_iso),
                        )
                        image_id = cursor.lastrowid
                    else:
                        image_id = db_entry["id"]
                        conn.execute(
                            """
                            UPDATE images
                            SET filename = ?, relative_path = ?, last_modified = ?, indexed_at = ?
                            WHERE id = ?
                            """,
                            (img_path.name, rel_path, mtime, now_iso, image_id),
                        )
                        conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))

                    for t in exif_tags:
                        clean_tag = t.strip().lower()
                        if clean_tag:
                            conn.execute(
                                "INSERT OR IGNORE INTO image_tags (image_id, tag_name) VALUES (?, ?)",
                                (image_id, clean_tag),
                            )

                    updated_count += 1

        return {
            "total": len(scanned_paths),
            "indexed": len(scanned_map),
            "updated": updated_count,
            "deleted": deleted_count,
        }
    finally:
        conn.close()


def get_gallery_images(
    db_path: str | Path | None = None,
    offset: int = 0,
    limit: int = 50,
    tags: list[str] | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Retrieve paginated images matching optional tag filter (ANY of selected tags) or search string.

    Returns (images_list, total_count).
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        clean_tags = [t.strip().lower() for t in (tags or []) if t.strip()]

        where_clauses: list[str] = []
        params: list[Any] = []

        if clean_tags:
            placeholders = ",".join("?" for _ in clean_tags)
            where_clauses.append(f"""
                id IN (
                    SELECT DISTINCT image_id FROM image_tags WHERE tag_name IN ({placeholders})
                )
            """)
            params.extend(clean_tags)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            where_clauses.append("(LOWER(filename) LIKE ? OR LOWER(relative_path) LIKE ?)")
            params.extend([search_pattern, search_pattern])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_sql = f"SELECT COUNT(*) as cnt FROM images {where_sql}"
        total_count = conn.execute(count_sql, params).fetchone()["cnt"]

        query_sql = f"""
            SELECT id, file_path, filename, relative_path, last_modified
            FROM images
            {where_sql}
            ORDER BY filename ASC, id ASC
            LIMIT ? OFFSET ?
        """
        query_params = list(params) + [limit, offset]
        rows = conn.execute(query_sql, query_params).fetchall()

        image_ids = [row["id"] for row in rows]
        tags_map: dict[int, list[str]] = {img_id: [] for img_id in image_ids}

        if image_ids:
            img_placeholders = ",".join("?" for _ in image_ids)
            tag_rows = conn.execute(
                f"SELECT image_id, tag_name FROM image_tags WHERE image_id IN ({img_placeholders}) ORDER BY tag_name ASC",
                image_ids,
            ).fetchall()
            for tr in tag_rows:
                tags_map[tr["image_id"]].append(tr["tag_name"])

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "file_path": r["file_path"],
                "filename": r["filename"],
                "relative_path": r["relative_path"],
                "last_modified": r["last_modified"],
                "tags": tags_map.get(r["id"], []),
            })

        return results, total_count
    finally:
        conn.close()


def get_all_tags(db_path: str | Path | None = None) -> list[str]:
    """Get sorted list of all unique tag names in database."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT DISTINCT tag_name FROM image_tags ORDER BY tag_name ASC").fetchall()
        return [r["tag_name"] for r in rows]
    finally:
        conn.close()


def get_image_by_id(image_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Get detailed metadata and tags for a single image by ID."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT id, file_path, filename, relative_path, last_modified FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            return None

        tag_rows = conn.execute(
            "SELECT tag_name FROM image_tags WHERE image_id = ? ORDER BY tag_name ASC",
            (image_id,),
        ).fetchall()
        tags = [tr["tag_name"] for tr in tag_rows]

        return {
            "id": row["id"],
            "file_path": row["file_path"],
            "filename": row["filename"],
            "relative_path": row["relative_path"],
            "last_modified": row["last_modified"],
            "tags": tags,
        }
    finally:
        conn.close()


def update_image_tags_in_db_and_exif(
    image_id: int,
    tags: list[str],
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> bool:
    """Update EXIF XPTags and database records for a single image."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT id, file_path FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            return False

        image_path = Path(row["file_path"])
        clean_tags = sorted({t.strip().lower() for t in tags if t.strip()})

        # Write to EXIF
        if image_path.exists():
            set_xptags(image_path, clean_tags, base_dir=base_dir)

        mtime = image_path.stat().st_mtime if image_path.exists() else row["last_modified"]

        with conn:
            conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, image_id))
            conn.execute("DELETE FROM image_tags WHERE image_id = ?", (image_id,))
            for t in clean_tags:
                conn.execute(
                    "INSERT OR IGNORE INTO image_tags (image_id, tag_name) VALUES (?, ?)",
                    (image_id, t),
                )
        return True
    finally:
        conn.close()


def batch_update_tags(
    image_ids: list[int],
    add_tags: list[str],
    remove_tags: list[str],
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> int:
    """Batch add and/or remove tags across multiple images by ID.

    Modifies EXIF XPTags and updates the SQLite database index.
    Returns the count of modified images.
    """
    if not image_ids:
        return 0

    to_add = {t.strip().lower() for t in add_tags if t.strip()}
    to_remove = {t.strip().lower() for t in remove_tags if t.strip()}

    if not to_add and not to_remove:
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    modified_count = 0

    try:
        placeholders = ",".join("?" for _ in image_ids)
        rows = conn.execute(
            f"SELECT id, file_path FROM images WHERE id IN ({placeholders})",
            image_ids,
        ).fetchall()

        for row in rows:
            img_id = row["id"]
            img_path = Path(row["file_path"])

            # Read current tags
            current_tags_rows = conn.execute(
                "SELECT tag_name FROM image_tags WHERE image_id = ?", (img_id,)
            ).fetchall()
            current_tags = {r["tag_name"] for r in current_tags_rows}

            new_tags = (current_tags | to_add) - to_remove
            if new_tags != current_tags:
                sorted_tags = sorted(new_tags)
                if img_path.exists():
                    set_xptags(img_path, sorted_tags, base_dir=base_dir)

                mtime = img_path.stat().st_mtime if img_path.exists() else 0.0

                with conn:
                    conn.execute("UPDATE images SET last_modified = ? WHERE id = ?", (mtime, img_id))
                    conn.execute("DELETE FROM image_tags WHERE image_id = ?", (img_id,))
                    for t in sorted_tags:
                        conn.execute(
                            "INSERT OR IGNORE INTO image_tags (image_id, tag_name) VALUES (?, ?)",
                            (img_id, t),
                        )
                modified_count += 1

        return modified_count
    finally:
        conn.close()


def remove_tag_globally(
    tag_name: str,
    db_path: str | Path | None = None,
    base_dir: Path | None = None,
) -> int:
    """Remove a specified tag from ALL images in the gallery and update EXIF metadata.

    Returns the count of images modified.
    """
    clean_tag = tag_name.strip().lower()
    if not clean_tag:
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        matching_rows = conn.execute(
            "SELECT DISTINCT image_id FROM image_tags WHERE tag_name = ?", (clean_tag,)
        ).fetchall()
        image_ids = [r["image_id"] for r in matching_rows]

        if not image_ids:
            return 0

        return batch_update_tags(
            image_ids=image_ids,
            add_tags=[],
            remove_tags=[clean_tag],
            db_path=db_path,
            base_dir=base_dir,
        )
    finally:
        conn.close()
