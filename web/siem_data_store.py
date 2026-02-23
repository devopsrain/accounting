"""
SIEM (Security Information and Event Management) Data Store
Tracks all data upload events with IP address, timestamp, user info, and file details.
Stores logs in Parquet format for efficient querying.
"""

import pandas as pd
import uuid
import os
import logging
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'siem')
UPLOAD_LOG_FILE = os.path.join(DATA_DIR, 'upload_events.parquet')
ALERT_FILE = os.path.join(DATA_DIR, 'siem_alerts.parquet')

# ── Alert Thresholds ───────────────────────────────────────────
RAPID_UPLOAD_THRESHOLD = 10        # number of uploads that trigger a rapid-upload alert
RAPID_UPLOAD_WINDOW_MINUTES = 5    # time window in minutes for rapid-upload detection
LARGE_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB threshold for large file alerts


class SIEMDataStore:
    """Centralized security event logging for all data uploads."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        # In-memory ring buffer for recent events (avoids re-reading parquet on every alert)
        self._recent_events: deque = deque(maxlen=500)

    # ── Upload Event Logging ──────────────────────────────────────────

    def log_upload_event(self, request_obj, module: str, endpoint: str,
                         filename: str = None, file_size: int = 0,
                         records_imported: int = 0, status: str = 'success',
                         details: str = '', user: str = None):
        """
        Log a data upload event from a Flask request.
        
        Args:
            request_obj: Flask request object (to extract IP, user-agent, etc.)
            module: Module name (e.g., 'payroll', 'vat', 'inventory')
            endpoint: Route endpoint (e.g., '/payroll/employees/import-excel')
            filename: Uploaded file name
            file_size: File size in bytes
            records_imported: Number of records successfully imported
            status: 'success', 'partial', or 'failed'
            details: Additional details or error message
            user: Username or identifier (auto-detected from session if not provided)
        """
        # Auto-detect user from Flask session if not provided
        if user is None:
            try:
                from flask import session
                user = session.get('username', 'anonymous')
            except Exception as e:
                logger.debug("Could not get username from session: %s", e)
                user = 'anonymous'

        # Extract IP - check forwarded headers first (for reverse proxies)
        ip_address = (
            request_obj.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request_obj.headers.get('X-Real-IP', '')
            or request_obj.remote_addr
            or 'unknown'
        )

        user_agent = request_obj.headers.get('User-Agent', 'unknown')
        referer = request_obj.headers.get('Referer', '')

        event = {
            'event_id': str(uuid.uuid4()),
            'timestamp': datetime.now().isoformat(),
            'ip_address': ip_address,
            'user': user,
            'module': module,
            'endpoint': endpoint,
            'http_method': request_obj.method,
            'filename': filename or '',
            'file_size_bytes': file_size,
            'records_imported': records_imported,
            'status': status,
            'details': details,
            'user_agent': user_agent,
            'referer': referer,
            'content_type': request_obj.content_type or '',
        }

        # Append to parquet
        new_df = pd.DataFrame([event])
        if os.path.exists(UPLOAD_LOG_FILE):
            existing = pd.read_parquet(UPLOAD_LOG_FILE)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined.to_parquet(UPLOAD_LOG_FILE, index=False)

        # Track event in memory for fast alert evaluation
        self._recent_events.append({
            'ip_address': event['ip_address'],
            'timestamp': datetime.now(),
        })

        # Check alert rules
        self._evaluate_alerts(event)

        return event

    # ── Query Methods ─────────────────────────────────────────────────

    def get_all_events(self, limit: int = 500):
        """Get all upload events, most recent first."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df = df.sort_values('timestamp', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    def get_events_by_ip(self, ip_address: str):
        """Get all events from a specific IP."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df = df[df['ip_address'] == ip_address]
        df = df.sort_values('timestamp', ascending=False)
        return df.to_dict('records')

    def get_events_by_module(self, module: str):
        """Get all events for a specific module."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df = df[df['module'] == module]
        df = df.sort_values('timestamp', ascending=False)
        return df.to_dict('records')

    def get_events_by_date_range(self, start_date: str, end_date: str):
        """Get events within a date range (YYYY-MM-DD)."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df['ts'] = pd.to_datetime(df['timestamp'])
        if start_date:
            df = df[df['ts'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['ts'] <= pd.to_datetime(end_date) + pd.Timedelta(days=1)]
        df = df.sort_values('timestamp', ascending=False)
        df = df.drop(columns=['ts'])
        return df.to_dict('records')

    def get_events_by_status(self, status: str):
        """Get events by status (success/partial/failed)."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df = df[df['status'] == status]
        df = df.sort_values('timestamp', ascending=False)
        return df.to_dict('records')

    def get_event_by_id(self, event_id: str):
        """Get a single event by ID."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return None
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        matches = df[df['event_id'] == event_id]
        if matches.empty:
            return None
        return matches.iloc[0].to_dict()

    # ── Dashboard Statistics ──────────────────────────────────────────

    def get_dashboard_stats(self):
        """Get summary statistics for the SIEM dashboard."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return {
                'total_events': 0,
                'unique_ips': 0,
                'successful_uploads': 0,
                'failed_uploads': 0,
                'total_records_imported': 0,
                'total_data_bytes': 0,
                'modules_active': 0,
                'events_today': 0,
                'events_this_week': 0,
                'top_ips': [],
                'top_modules': [],
                'hourly_activity': [],
                'recent_failures': [],
            }

        df = pd.read_parquet(UPLOAD_LOG_FILE)
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        week_ago = (now - pd.Timedelta(days=7)).isoformat()

        df['ts'] = pd.to_datetime(df['timestamp'])

        # Basic counts
        total = len(df)
        unique_ips = df['ip_address'].nunique()
        success = len(df[df['status'] == 'success'])
        failed = len(df[df['status'] == 'failed'])
        total_records = int(df['records_imported'].sum()) if 'records_imported' in df.columns else 0
        total_bytes = int(df['file_size_bytes'].sum()) if 'file_size_bytes' in df.columns else 0
        modules_active = df['module'].nunique()

        # Time-based
        events_today = len(df[df['ts'].dt.strftime('%Y-%m-%d') == today_str])
        events_week = len(df[df['ts'] >= week_ago])

        # Top IPs (upload frequency)
        top_ips = (
            df.groupby('ip_address')
            .agg(count=('event_id', 'count'), last_seen=('timestamp', 'max'))
            .sort_values('count', ascending=False)
            .head(10)
            .reset_index()
            .to_dict('records')
        )

        # Top modules
        top_modules = (
            df.groupby('module')
            .agg(count=('event_id', 'count'), records=('records_imported', 'sum'))
            .sort_values('count', ascending=False)
            .reset_index()
            .to_dict('records')
        )

        # Hourly activity (last 24h)
        last_24h = df[df['ts'] >= (now - pd.Timedelta(hours=24))]
        if not last_24h.empty:
            hourly = (
                last_24h.groupby(last_24h['ts'].dt.hour)
                .size()
                .reindex(range(24), fill_value=0)
                .to_dict()
            )
            hourly_activity = [{'hour': h, 'count': c} for h, c in hourly.items()]
        else:
            hourly_activity = [{'hour': h, 'count': 0} for h in range(24)]

        # Recent failures
        failures = df[df['status'] == 'failed'].sort_values('timestamp', ascending=False).head(5)
        recent_failures = failures.to_dict('records') if not failures.empty else []

        return {
            'total_events': total,
            'unique_ips': unique_ips,
            'successful_uploads': success,
            'failed_uploads': failed,
            'total_records_imported': total_records,
            'total_data_bytes': total_bytes,
            'modules_active': modules_active,
            'events_today': events_today,
            'events_this_week': events_week,
            'top_ips': top_ips,
            'top_modules': top_modules,
            'hourly_activity': hourly_activity,
            'recent_failures': recent_failures,
        }

    # ── Alert System ──────────────────────────────────────────────────

    def _evaluate_alerts(self, event: dict):
        """Check if the event triggers any alert rules."""
        alerts = []

        # Rule 1: Failed upload
        if event['status'] == 'failed':
            alerts.append({
                'alert_id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(),
                'severity': 'warning',
                'rule': 'upload_failed',
                'message': f"Failed upload from {event['ip_address']} to {event['module']}/{event['endpoint']}",
                'event_id': event['event_id'],
                'ip_address': event['ip_address'],
                'acknowledged': False,
            })

        # Rule 2: Rapid uploads from same IP (more than N in last M min)
        # Uses in-memory ring buffer instead of re-reading the full parquet file
        cutoff = datetime.now() - timedelta(minutes=RAPID_UPLOAD_WINDOW_MINUTES)
        recent_count = sum(
            1 for e in self._recent_events
            if e['ip_address'] == event['ip_address'] and e['timestamp'] >= cutoff
        )
        if recent_count > RAPID_UPLOAD_THRESHOLD:
                alerts.append({
                    'alert_id': str(uuid.uuid4()),
                    'timestamp': datetime.now().isoformat(),
                    'severity': 'high',
                    'rule': 'rapid_uploads',
                    'message': f"Rapid upload activity: {len(recent)} uploads in {RAPID_UPLOAD_WINDOW_MINUTES} min from {event['ip_address']}",
                    'event_id': event['event_id'],
                    'ip_address': event['ip_address'],
                    'acknowledged': False,
                })

        # Rule 3: Large file upload
        if event.get('file_size_bytes', 0) > LARGE_FILE_SIZE_BYTES:
            alerts.append({
                'alert_id': str(uuid.uuid4()),
                'timestamp': datetime.now().isoformat(),
                'severity': 'info',
                'rule': 'large_file',
                'message': f"Large file upload ({event['file_size_bytes'] / 1024 / 1024:.1f} MB) from {event['ip_address']}",
                'event_id': event['event_id'],
                'ip_address': event['ip_address'],
                'acknowledged': False,
            })

        if alerts:
            self._save_alerts(alerts)

    def _save_alerts(self, alerts: list):
        """Save alerts to parquet."""
        new_df = pd.DataFrame(alerts)
        if os.path.exists(ALERT_FILE):
            existing = pd.read_parquet(ALERT_FILE)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
        combined.to_parquet(ALERT_FILE, index=False)

    def get_alerts(self, acknowledged: bool = None, limit: int = 100):
        """Get SIEM alerts."""
        if not os.path.exists(ALERT_FILE):
            return []
        df = pd.read_parquet(ALERT_FILE)
        if acknowledged is not None:
            df = df[df['acknowledged'] == acknowledged]
        df = df.sort_values('timestamp', ascending=False)
        if limit:
            df = df.head(limit)
        return df.to_dict('records')

    def acknowledge_alert(self, alert_id: str):
        """Mark an alert as acknowledged."""
        if not os.path.exists(ALERT_FILE):
            return False
        df = pd.read_parquet(ALERT_FILE)
        mask = df['alert_id'] == alert_id
        if mask.any():
            df.loc[mask, 'acknowledged'] = True
            df.to_parquet(ALERT_FILE, index=False)
            return True
        return False

    def get_alert_counts(self):
        """Get alert counts by severity."""
        if not os.path.exists(ALERT_FILE):
            return {'total': 0, 'unacknowledged': 0, 'high': 0, 'warning': 0, 'info': 0}
        df = pd.read_parquet(ALERT_FILE)
        unack = df[df['acknowledged'] == False]
        return {
            'total': len(df),
            'unacknowledged': len(unack),
            'high': len(unack[unack['severity'] == 'high']),
            'warning': len(unack[unack['severity'] == 'warning']),
            'info': len(unack[unack['severity'] == 'info']),
        }

    # ── IP Analysis ───────────────────────────────────────────────────

    def get_ip_summary(self):
        """Get a summary of all IPs that have uploaded data."""
        if not os.path.exists(UPLOAD_LOG_FILE):
            return []
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        summary = (
            df.groupby('ip_address')
            .agg(
                total_uploads=('event_id', 'count'),
                first_seen=('timestamp', 'min'),
                last_seen=('timestamp', 'max'),
                successful=('status', lambda x: (x == 'success').sum()),
                failed=('status', lambda x: (x == 'failed').sum()),
                modules_used=('module', 'nunique'),
                total_records=('records_imported', 'sum'),
                total_bytes=('file_size_bytes', 'sum'),
            )
            .sort_values('total_uploads', ascending=False)
            .reset_index()
        )
        return summary.to_dict('records')

    # ── Export ────────────────────────────────────────────────────────

    def export_events_to_excel(self):
        """Export all events to an Excel file. Returns the temp file path."""
        import tempfile
        if not os.path.exists(UPLOAD_LOG_FILE):
            return None
        df = pd.read_parquet(UPLOAD_LOG_FILE)
        df = df.sort_values('timestamp', ascending=False)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx', prefix='siem_export_')
        tmp_path = tmp.name
        tmp.close()
        try:
            df.to_excel(tmp_path, index=False, sheet_name='Upload Events')
        except Exception:
            # Clean up orphaned temp file on write failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return tmp_path


# Singleton instance
siem_store = SIEMDataStore()

__all__ = [
    'siem_store',
    'SIEMDataStore',
    'RAPID_UPLOAD_THRESHOLD',
    'RAPID_UPLOAD_WINDOW_MINUTES',
    'LARGE_FILE_SIZE_BYTES',
]
