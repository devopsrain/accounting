"""
Backup & Archive Module – Data Store and Engine

Memory-optimised daily backup of all parquet/xlsx data files.
Archives are stored as compressed zip files (one per day).
A scheduled batch job runs at 01:00 each night.

Design decisions for memory efficiency:
  - Files are streamed into the zip archive one-by-one (never all loaded at once)
  - Uses ZIP_DEFLATED (zlib) with compresslevel=6 for good compression/speed balance
  - Old archives auto-purge after configurable retention days
  - Manifest JSON inside each archive records file metadata without re-reading
"""

import os
import json
import zipfile
import hashlib
import shutil
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WEB_DIR, 'data')
BACKUP_DIR = os.path.join(WEB_DIR, 'data', 'backups')
BACKUP_META_FILE = os.path.join(BACKUP_DIR, 'backup_log.parquet')

# ── Config ────────────────────────────────────────────────────────
DEFAULT_RETENTION_DAYS = 30        # keep archives for 30 days
SCHEDULE_HOUR = 1                  # 01:00 daily
SCHEDULE_MINUTE = 0
CHUNK_SIZE = 64 * 1024             # 64 KB read buffer for streaming into zip


def _file_sha256(filepath: str) -> str:
    """Compute SHA-256 of a file in 64 KB chunks (memory-friendly)."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class BackupEngine:
    """Creates, manages, and restores compressed daily backup archives."""

    def __init__(self, data_dir: str = DATA_DIR, backup_dir: str = BACKUP_DIR,
                 retention_days: int = DEFAULT_RETENTION_DAYS):
        self.data_dir = data_dir
        self.backup_dir = backup_dir
        self.retention_days = retention_days
        os.makedirs(self.backup_dir, exist_ok=True)

    # ── Discover files to back up ─────────────────────────────────

    def _collect_files(self) -> list:
        """
        Walk data_dir and collect all data files (parquet, xlsx, json, csv).
        Excludes the backups/ subdirectory itself.
        Returns list of dicts with relative_path, abs_path, size, mtime.
        """
        files = []
        for root, dirs, filenames in os.walk(self.data_dir):
            # Skip the backups directory
            rel_root = os.path.relpath(root, self.data_dir)
            if rel_root == 'backups' or rel_root.startswith('backups' + os.sep):
                continue
            for fn in filenames:
                abs_path = os.path.join(root, fn)
                rel_path = os.path.relpath(abs_path, self.data_dir)
                stat = os.stat(abs_path)
                files.append({
                    'relative_path': rel_path.replace('\\', '/'),
                    'abs_path': abs_path,
                    'size_bytes': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return files

    # ── Create backup ─────────────────────────────────────────────

    def create_backup(self, label: str = None, triggered_by: str = 'manual') -> dict:
        """
        Create a compressed archive of all data files.

        Memory-optimised: files are streamed into the zip one at a time using
        64 KB chunks, so peak memory usage equals ~64 KB + zip buffer overhead
        regardless of total data size.

        Returns a result dict with archive_path, file_count, compressed_size, etc.
        """
        now = datetime.now()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M%S')
        archive_name = f"backup_{date_str}_{time_str}.zip"
        if label:
            safe_label = ''.join(c if c.isalnum() or c in '-_' else '_' for c in label)
            archive_name = f"backup_{date_str}_{time_str}_{safe_label}.zip"

        archive_path = os.path.join(self.backup_dir, archive_name)
        files = self._collect_files()

        if not files:
            return {
                'success': False,
                'error': 'No data files found to back up',
                'file_count': 0,
            }

        manifest = {
            'backup_date': now.isoformat(),
            'triggered_by': triggered_by,
            'label': label or '',
            'files': [],
        }

        total_original = 0

        # Stream files into zip one by one for memory efficiency
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for finfo in files:
                abs_p = finfo['abs_path']
                rel_p = finfo['relative_path']
                size = finfo['size_bytes']

                # Compute checksum in streaming fashion
                sha = _file_sha256(abs_p)

                # Add file to zip (zipfile reads it in chunks internally)
                zf.write(abs_p, arcname=rel_p)

                manifest['files'].append({
                    'path': rel_p,
                    'size_bytes': size,
                    'sha256': sha,
                    'modified': finfo['modified'],
                })
                total_original += size

            # Write manifest inside the archive
            manifest_json = json.dumps(manifest, indent=2, default=str)
            zf.writestr('_backup_manifest.json', manifest_json)

        compressed_size = os.path.getsize(archive_path)
        ratio = round(compressed_size / total_original * 100, 1) if total_original > 0 else 0

        result = {
            'success': True,
            'archive_name': archive_name,
            'archive_path': archive_path,
            'file_count': len(files),
            'original_size': total_original,
            'compressed_size': compressed_size,
            'compression_ratio': ratio,
            'timestamp': now.isoformat(),
            'triggered_by': triggered_by,
            'label': label or '',
        }

        # Log to parquet
        self._log_backup(result)
        logger.info(f"Backup created: {archive_name} ({len(files)} files, "
                     f"{compressed_size:,} bytes, {ratio}% of original)")
        return result

    # ── List backups ──────────────────────────────────────────────

    def list_backups(self) -> list:
        """List all backup archives, most recent first."""
        backups = []
        for fn in os.listdir(self.backup_dir):
            if fn.endswith('.zip') and fn.startswith('backup_'):
                fp = os.path.join(self.backup_dir, fn)
                stat = os.stat(fp)
                # Read manifest if possible
                manifest = self._read_manifest(fp)
                backups.append({
                    'archive_name': fn,
                    'size_bytes': stat.st_size,
                    'size_display': self._human_size(stat.st_size),
                    'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'file_count': len(manifest.get('files', [])) if manifest else '?',
                    'triggered_by': manifest.get('triggered_by', '?') if manifest else '?',
                    'label': manifest.get('label', '') if manifest else '',
                })
        backups.sort(key=lambda b: b['created'], reverse=True)
        return backups

    def _read_manifest(self, archive_path: str) -> dict:
        """Read manifest from archive without extracting all files."""
        try:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                if '_backup_manifest.json' in zf.namelist():
                    return json.loads(zf.read('_backup_manifest.json'))
        except Exception as e:
            logger.warning("Could not read backup manifest from %s: %s", archive_path, e)
        return None

    def get_backup_details(self, archive_name: str) -> dict:
        """Get detailed info about a specific backup archive."""
        archive_path = os.path.join(self.backup_dir, archive_name)
        if not os.path.exists(archive_path):
            return None

        manifest = self._read_manifest(archive_path)
        stat = os.stat(archive_path)

        return {
            'archive_name': archive_name,
            'archive_path': archive_path,
            'size_bytes': stat.st_size,
            'size_display': self._human_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'manifest': manifest,
            'file_count': len(manifest.get('files', [])) if manifest else 0,
        }

    # ── Restore from backup ──────────────────────────────────────

    def restore_backup(self, archive_name: str, confirm: bool = False) -> dict:
        """
        Restore data files from a backup archive.
        Extracts files one by one (memory efficient) back into data_dir.
        The current data is backed up first as a safety net.
        """
        archive_path = os.path.join(self.backup_dir, archive_name)
        if not os.path.exists(archive_path):
            return {'success': False, 'error': 'Archive not found'}

        if not confirm:
            return {'success': False, 'error': 'Restore requires confirmation'}

        # Safety: create a pre-restore backup first
        safety = self.create_backup(label='pre-restore-safety', triggered_by='auto-safety')

        restored = 0
        errors = []

        with zipfile.ZipFile(archive_path, 'r') as zf:
            for member in zf.namelist():
                if member == '_backup_manifest.json':
                    continue
                try:
                    target = os.path.join(self.data_dir, member)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    # Extract one file at a time (memory efficient)
                    with zf.open(member) as src, open(target, 'wb') as dst:
                        while True:
                            chunk = src.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            dst.write(chunk)
                    restored += 1
                except Exception as e:
                    errors.append(f"{member}: {str(e)}")

        return {
            'success': len(errors) == 0,
            'restored_files': restored,
            'errors': errors,
            'safety_backup': safety.get('archive_name', ''),
        }

    # ── Delete archive ────────────────────────────────────────────

    def delete_backup(self, archive_name: str) -> bool:
        """Delete a specific backup archive."""
        archive_path = os.path.join(self.backup_dir, archive_name)
        if os.path.exists(archive_path) and archive_name.endswith('.zip'):
            os.remove(archive_path)
            return True
        return False

    # ── Retention purge ───────────────────────────────────────────

    def purge_old_backups(self) -> int:
        """Remove archives older than retention_days. Returns count deleted."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        deleted = 0
        for fn in os.listdir(self.backup_dir):
            if fn.endswith('.zip') and fn.startswith('backup_'):
                fp = os.path.join(self.backup_dir, fn)
                mtime = datetime.fromtimestamp(os.stat(fp).st_mtime)
                if mtime < cutoff:
                    os.remove(fp)
                    deleted += 1
                    logger.info(f"Purged old backup: {fn}")
        return deleted

    # ── Backup log (parquet) ──────────────────────────────────────

    def _log_backup(self, result: dict):
        """Append backup result to the log parquet file."""
        entry = {
            'backup_id': result.get('archive_name', ''),
            'timestamp': result.get('timestamp', datetime.now().isoformat()),
            'file_count': result.get('file_count', 0),
            'original_size': result.get('original_size', 0),
            'compressed_size': result.get('compressed_size', 0),
            'compression_ratio': result.get('compression_ratio', 0),
            'triggered_by': result.get('triggered_by', ''),
            'label': result.get('label', ''),
            'success': result.get('success', False),
        }
        new_df = pd.DataFrame([entry])
        if os.path.exists(BACKUP_META_FILE):
            existing = pd.read_parquet(BACKUP_META_FILE)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
        combined.to_parquet(BACKUP_META_FILE, index=False)

    def get_backup_log(self, limit: int = 50) -> list:
        """Get backup history from the log."""
        if not os.path.exists(BACKUP_META_FILE):
            return []
        df = pd.read_parquet(BACKUP_META_FILE)
        df = df.sort_values('timestamp', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    # ── Statistics ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get backup statistics."""
        backups = self.list_backups()
        total_size = sum(b['size_bytes'] for b in backups)
        last_backup = backups[0] if backups else None

        # Current data size
        files = self._collect_files()
        current_data_size = sum(f['size_bytes'] for f in files)

        return {
            'total_backups': len(backups),
            'total_archive_size': total_size,
            'total_archive_display': self._human_size(total_size),
            'current_data_files': len(files),
            'current_data_size': current_data_size,
            'current_data_display': self._human_size(current_data_size),
            'last_backup': last_backup,
            'retention_days': self.retention_days,
            'schedule_time': f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}",
        }

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _human_size(nbytes: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if abs(nbytes) < 1024:
                return f"{nbytes:.1f} {unit}"
            nbytes /= 1024
        return f"{nbytes:.1f} TB"


# ── Scheduler ─────────────────────────────────────────────────────

class BackupScheduler:
    """
    Lightweight daemon thread that triggers the daily backup at SCHEDULE_HOUR:SCHEDULE_MINUTE.
    Checks every 60 seconds. No heavy dependencies (no APScheduler/celery).
    Memory footprint: ~0 (just a sleeping thread).
    """

    def __init__(self, engine: BackupEngine):
        self.engine = engine
        self._thread = None
        self._stop = threading.Event()
        self._last_run_date = None

    def start(self):
        """Start the scheduler daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='backup-scheduler')
        self._thread.start()
        logger.info(f"Backup scheduler started (daily at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d})")

    def stop(self):
        """Signal the scheduler to stop."""
        self._stop.set()

    def _run(self):
        """Main loop: sleep 60s, check if it's time to run."""
        while not self._stop.is_set():
            now = datetime.now()
            today = now.date()

            if (now.hour == SCHEDULE_HOUR and
                now.minute >= SCHEDULE_MINUTE and
                now.minute < SCHEDULE_MINUTE + 2 and
                self._last_run_date != today):

                logger.info("Scheduled backup starting...")
                try:
                    result = self.engine.create_backup(
                        label='scheduled',
                        triggered_by='scheduler'
                    )
                    if result['success']:
                        logger.info(f"Scheduled backup complete: {result['archive_name']}")
                        # Also purge old backups
                        purged = self.engine.purge_old_backups()
                        if purged:
                            logger.info(f"Purged {purged} old backup(s)")
                    else:
                        logger.error(f"Scheduled backup failed: {result.get('error')}")
                except Exception as e:
                    logger.error(f"Scheduled backup error: {e}")

                self._last_run_date = today

            # Sleep 60 seconds between checks
            self._stop.wait(60)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def next_run(self) -> str:
        """Estimate next scheduled run time."""
        now = datetime.now()
        target = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return target.isoformat()


# ── Singleton instances ───────────────────────────────────────────
backup_engine = BackupEngine()
backup_scheduler = BackupScheduler(backup_engine)
__all__ = [
    'backup_engine',
    'backup_scheduler',
    'BackupEngine',
    'BackupScheduler',
    'DEFAULT_RETENTION_DAYS',
    'SCHEDULE_HOUR',
    'SCHEDULE_MINUTE',
    'CHUNK_SIZE',
]