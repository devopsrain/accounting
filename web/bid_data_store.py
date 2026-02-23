"""
Bid Management Data Store

Parquet-based persistence for public bid tracking with document management,
deadline reminders, and email alert configuration.
"""

import pandas as pd
import os
import uuid
import shutil
import smtplib
import threading
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger(__name__)


def _resolve_company_id(company_id=None):
    """Resolve company_id from arg → Flask g → 'default'."""
    if company_id:
        return company_id
    try:
        from flask import g
        return getattr(g, 'company_id', None) or 'default'
    except (ImportError, RuntimeError):
        return 'default'


class BidDataStore:
    """Data store for bid tracking with parquet persistence and file storage."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.bid_file = os.path.join(data_dir, "bid_records.parquet")
        self.documents_dir = os.path.join(data_dir, "bid_documents")

        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(self.documents_dir, exist_ok=True)

        # Schema ----------------------------------------------------------
        self.bid_schema = {
            'id': 'string',
            'company_id': 'string',
            'title': 'string',
            'reference_number': 'string',
            'organization': 'string',          # issuing entity
            'description': 'string',
            'category': 'string',              # IT, Construction, Consulting …
            'status': 'string',                # Draft, Open, In Progress, Submitted, Won, Lost, Cancelled
            'deadline': 'string',              # YYYY-MM-DD HH:MM
            'submission_date': 'string',       # actual submission date
            'bid_amount': 'float64',
            'currency': 'string',
            'case_handler_name': 'string',
            'case_handler_email': 'string',
            'reminder_days_before': 'int64',   # how many days before deadline to send reminder
            'reminder_sent': 'bool',
            'notes': 'string',
            'created_at': 'string',
            'updated_at': 'string',
        }

        self.document_schema = {
            'id': 'string',
            'bid_id': 'string',
            'filename': 'string',
            'original_filename': 'string',
            'doc_type': 'string',       # original_bid, technical, financial, supporting, other
            'description': 'string',
            'uploaded_by': 'string',
            'file_size': 'int64',
            'uploaded_at': 'string',
        }

        self.doc_file = os.path.join(data_dir, "bid_documents_meta.parquet")

        self._initialize_files()

        # Start background reminder thread
        self._start_reminder_thread()

    # ------------------------------------------------------------------
    #  Initialisation
    # ------------------------------------------------------------------
    def _initialize_files(self):
        for path, schema in [
            (self.bid_file, self.bid_schema),
            (self.doc_file, self.document_schema),
        ]:
            if not os.path.exists(path):
                df = pd.DataFrame(columns=list(schema.keys()))
                df = df.astype(schema)
                df.to_parquet(path, index=False)

    # ------------------------------------------------------------------
    #  Bid CRUD
    # ------------------------------------------------------------------
    def save_bid(self, data: Dict[str, Any]) -> Optional[str]:
        """Create or update a bid record. Returns the bid id."""
        try:
            df = pd.read_parquet(self.bid_file)
            now = datetime.now().isoformat()

            if 'id' not in data or not data['id']:
                data['id'] = f"BID-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
                data['created_at'] = now
                data['updated_at'] = now
                data.setdefault('status', 'Draft')
                data.setdefault('reminder_sent', False)
                data.setdefault('currency', 'ETB')
                data.setdefault('reminder_days_before', 3)
                data['company_id'] = data.get('company_id') or _resolve_company_id()
                for f in ('bid_amount',):
                    data[f] = float(data.get(f) or 0)
                data['reminder_days_before'] = int(data.get('reminder_days_before') or 3)
                new = pd.DataFrame([data])
                df = pd.concat([df, new], ignore_index=True)
            else:
                # Update existing
                idx = df.index[df['id'] == data['id']]
                if idx.empty:
                    return None
                data['updated_at'] = now
                # Coerce numeric fields to proper types before assignment
                if 'bid_amount' in data:
                    data['bid_amount'] = float(data['bid_amount'] or 0)
                if 'reminder_days_before' in data:
                    data['reminder_days_before'] = int(data['reminder_days_before'] or 3)
                for col, val in data.items():
                    if col in df.columns:
                        df.loc[idx, col] = val

            # Enforce column dtypes before writing
            for col, dtype in self.bid_schema.items():
                if col in df.columns:
                    try:
                        df[col] = df[col].astype(dtype)
                    except (ValueError, TypeError):
                        pass
            df.to_parquet(self.bid_file, index=False)
            return data['id']
        except Exception as e:
            logger.error("Error saving bid: %s", e, exc_info=True)
            return None

    def get_all_bids(self, company_id: str = None) -> List[Dict]:
        try:
            df = pd.read_parquet(self.bid_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            records = df.to_dict('records')
            for r in records:
                r['document_count'] = self._count_documents(r['id'])
            return records
        except Exception as e:
            logger.error("Error loading bids: %s", e)
            return []

    def get_bid_by_id(self, bid_id: str) -> Optional[Dict]:
        try:
            df = pd.read_parquet(self.bid_file)
            row = df[df['id'] == bid_id]
            if row.empty:
                return None
            record = row.iloc[0].to_dict()
            record['documents'] = self.get_documents(bid_id)
            return record
        except Exception as e:
            logger.error("Error loading bid %s: %s", bid_id, e)
            return None

    def delete_bid(self, bid_id: str) -> bool:
        try:
            df = pd.read_parquet(self.bid_file)
            df = df[df['id'] != bid_id]
            df.to_parquet(self.bid_file, index=False)
            # Delete associated documents
            self._delete_bid_documents(bid_id)
            return True
        except Exception as e:
            logger.error("Error deleting bid %s: %s", bid_id, e)
            return False

    def get_summary_stats(self, company_id: str = None) -> Dict[str, Any]:
        try:
            df = pd.read_parquet(self.bid_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            if df.empty:
                return {'total': 0, 'open': 0, 'in_progress': 0, 'submitted': 0,
                        'won': 0, 'lost': 0, 'total_value': 0, 'upcoming_deadlines': 0}
            now_str = datetime.now().strftime('%Y-%m-%d')
            upcoming = df[
                (df['status'].isin(['Open', 'In Progress', 'Draft'])) &
                (df['deadline'] >= now_str)
            ]
            return {
                'total': len(df),
                'open': int((df['status'] == 'Open').sum()),
                'in_progress': int((df['status'] == 'In Progress').sum()),
                'submitted': int((df['status'] == 'Submitted').sum()),
                'won': int((df['status'] == 'Won').sum()),
                'lost': int((df['status'] == 'Lost').sum()),
                'draft': int((df['status'] == 'Draft').sum()),
                'total_value': float(df['bid_amount'].sum()),
                'upcoming_deadlines': len(upcoming),
            }
        except Exception as e:
            logger.error("Error computing bid stats: %s", e)
            return {'total': 0, 'open': 0, 'in_progress': 0, 'submitted': 0,
                    'won': 0, 'lost': 0, 'total_value': 0, 'upcoming_deadlines': 0}

    # ------------------------------------------------------------------
    #  Document management
    # ------------------------------------------------------------------
    def save_document(self, bid_id: str, file_obj, doc_type: str,
                      description: str = '', uploaded_by: str = '') -> Optional[str]:
        """Save an uploaded file and record metadata. Returns doc id."""
        try:
            doc_id = f"DOC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            original_name = file_obj.filename
            ext = os.path.splitext(original_name)[1]
            safe_name = f"{doc_id}{ext}"

            # Create per-bid directory
            bid_dir = os.path.join(self.documents_dir, bid_id)
            os.makedirs(bid_dir, exist_ok=True)

            filepath = os.path.join(bid_dir, safe_name)
            file_obj.save(filepath)
            file_size = os.path.getsize(filepath)

            meta = {
                'id': doc_id,
                'bid_id': bid_id,
                'filename': safe_name,
                'original_filename': original_name,
                'doc_type': doc_type,
                'description': description,
                'uploaded_by': uploaded_by,
                'file_size': file_size,
                'uploaded_at': datetime.now().isoformat(),
            }

            df = pd.read_parquet(self.doc_file)
            df = pd.concat([df, pd.DataFrame([meta])], ignore_index=True)
            df.to_parquet(self.doc_file, index=False)
            return doc_id
        except Exception as e:
            logger.error("Error saving document: %s", e, exc_info=True)
            return None

    def get_documents(self, bid_id: str) -> List[Dict]:
        try:
            df = pd.read_parquet(self.doc_file)
            docs = df[df['bid_id'] == bid_id].to_dict('records')
            for d in docs:
                d['file_size_display'] = self._format_size(d.get('file_size', 0))
                d['doc_type_label'] = {
                    'original_bid': 'Original Bid Document',
                    'technical': 'Technical Proposal',
                    'financial': 'Financial Proposal',
                    'supporting': 'Supporting Document',
                    'other': 'Other',
                }.get(d.get('doc_type', ''), d.get('doc_type', ''))
            return docs
        except Exception as e:
            logger.error("Error loading documents for bid %s: %s", bid_id, e)
            return []

    def get_document_path(self, bid_id: str, doc_id: str) -> Optional[str]:
        """Return the filesystem path for a document so it can be sent."""
        try:
            df = pd.read_parquet(self.doc_file)
            row = df[(df['id'] == doc_id) & (df['bid_id'] == bid_id)]
            if row.empty:
                return None
            filename = row.iloc[0]['filename']
            path = os.path.join(self.documents_dir, bid_id, filename)
            return path if os.path.exists(path) else None
        except Exception as e:
            logger.error("Error finding document path: %s", e)
            return None

    def get_document_meta(self, doc_id: str) -> Optional[Dict]:
        try:
            df = pd.read_parquet(self.doc_file)
            row = df[df['id'] == doc_id]
            if row.empty:
                return None
            return row.iloc[0].to_dict()
        except Exception as e:
            logger.error("Error loading document meta: %s", e)
            return None

    def delete_document(self, doc_id: str) -> bool:
        try:
            df = pd.read_parquet(self.doc_file)
            row = df[df['id'] == doc_id]
            if not row.empty:
                filename = row.iloc[0]['filename']
                bid_id = row.iloc[0]['bid_id']
                path = os.path.join(self.documents_dir, bid_id, filename)
                if os.path.exists(path):
                    os.remove(path)
            df = df[df['id'] != doc_id]
            df.to_parquet(self.doc_file, index=False)
            return True
        except Exception as e:
            logger.error("Error deleting document: %s", e)
            return False

    def _count_documents(self, bid_id: str) -> int:
        try:
            df = pd.read_parquet(self.doc_file)
            return int((df['bid_id'] == bid_id).sum())
        except Exception:
            return 0

    def _delete_bid_documents(self, bid_id: str):
        """Remove all documents (files + meta) for a bid."""
        try:
            df = pd.read_parquet(self.doc_file)
            df = df[df['bid_id'] != bid_id]
            df.to_parquet(self.doc_file, index=False)
            bid_dir = os.path.join(self.documents_dir, bid_id)
            if os.path.isdir(bid_dir):
                shutil.rmtree(bid_dir)
        except Exception as e:
            logger.error("Error cleaning up documents for bid %s: %s", bid_id, e)

    # ------------------------------------------------------------------
    #  Email Reminders
    # ------------------------------------------------------------------
    def _start_reminder_thread(self):
        """Background thread that checks every hour for approaching deadlines."""
        def _checker():
            while True:
                try:
                    self._check_reminders()
                except Exception as e:
                    logger.error("Reminder check error: %s", e)
                threading.Event().wait(3600)  # every hour

        t = threading.Thread(target=_checker, daemon=True)
        t.start()
        logger.info("Bid deadline reminder thread started")

    def _check_reminders(self):
        """Send email reminders for bids approaching their deadline."""
        try:
            df = pd.read_parquet(self.bid_file)
            if df.empty:
                return

            now = datetime.now()
            for idx, row in df.iterrows():
                if row.get('reminder_sent', False):
                    continue
                if row['status'] not in ('Open', 'In Progress', 'Draft'):
                    continue
                if not row.get('deadline') or not row.get('case_handler_email'):
                    continue

                try:
                    deadline = datetime.strptime(str(row['deadline'])[:16], '%Y-%m-%d %H:%M')
                except (ValueError, TypeError):
                    try:
                        deadline = datetime.strptime(str(row['deadline'])[:10], '%Y-%m-%d')
                    except (ValueError, TypeError):
                        continue

                days_before = int(row.get('reminder_days_before', 3))
                trigger = deadline - timedelta(days=days_before)

                if now >= trigger:
                    sent = self._send_reminder_email(row, deadline)
                    if sent:
                        df.at[idx, 'reminder_sent'] = True
                        logger.info("Reminder sent for bid %s to %s",
                                    row['id'], row['case_handler_email'])

            df.to_parquet(self.bid_file, index=False)
        except Exception as e:
            logger.error("Error in reminder check: %s", e, exc_info=True)

    def _send_reminder_email(self, bid: Dict, deadline: datetime) -> bool:
        """Send a deadline reminder email for a bid.

        Uses SMTP env vars: BID_SMTP_HOST, BID_SMTP_PORT, BID_SMTP_USER,
        BID_SMTP_PASSWORD, BID_SMTP_FROM.  Returns True even when SMTP
        is not configured so the flag is set (avoids spamming logs).
        """
        smtp_host = os.environ.get('BID_SMTP_HOST', '')
        smtp_port = int(os.environ.get('BID_SMTP_PORT', '587'))
        smtp_user = os.environ.get('BID_SMTP_USER', '')
        smtp_pass = os.environ.get('BID_SMTP_PASSWORD', '')
        smtp_from = os.environ.get('BID_SMTP_FROM', smtp_user or 'noreply@devopsrain.com')

        to_email = bid.get('case_handler_email', '')
        if not to_email:
            return False

        days_left = (deadline - datetime.now()).days
        subject = f"⏰ Bid Deadline Reminder: {bid.get('title', 'Untitled')} — {days_left} day(s) left"

        body = f"""
Dear {bid.get('case_handler_name', 'Team')},

This is a reminder that the following bid is approaching its deadline:

  Title:        {bid.get('title', '')}
  Reference:    {bid.get('reference_number', '')}
  Organization: {bid.get('organization', '')}
  Deadline:     {deadline.strftime('%A, %d %B %Y at %H:%M')}
  Status:       {bid.get('status', '')}

Please ensure all technical and financial proposals are uploaded and reviewed before the deadline.

—
Ethiopian Accounting System – Bid Tracker
Developed by DevOpsRain Technologies CC
        """.strip()

        if not smtp_host:
            logger.info("SMTP not configured – reminder logged but not emailed for bid %s",
                        bid.get('id'))
            return True  # Mark as sent to avoid re-triggering

        try:
            msg = MIMEMultipart()
            msg['From'] = smtp_from
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error("Failed to send reminder email for bid %s: %s", bid.get('id'), e)
            return False

    def send_test_email(self, to_email: str) -> Dict[str, Any]:
        """Send a test email to verify SMTP configuration."""
        smtp_host = os.environ.get('BID_SMTP_HOST', '')
        if not smtp_host:
            return {'success': False,
                    'message': 'SMTP not configured. Set BID_SMTP_HOST, BID_SMTP_PORT, BID_SMTP_USER, BID_SMTP_PASSWORD environment variables.'}
        try:
            smtp_port = int(os.environ.get('BID_SMTP_PORT', '587'))
            smtp_user = os.environ.get('BID_SMTP_USER', '')
            smtp_pass = os.environ.get('BID_SMTP_PASSWORD', '')
            smtp_from = os.environ.get('BID_SMTP_FROM', smtp_user or 'noreply@devopsrain.com')

            msg = MIMEText("This is a test email from the Ethiopian Accounting System – Bid Tracker module.\n\nIf you received this, your SMTP configuration is working correctly.\n\n— DevOpsRain Technologies CC")
            msg['Subject'] = '✅ Bid Tracker – SMTP Test Email'
            msg['From'] = smtp_from
            msg['To'] = to_email

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            return {'success': True, 'message': f'Test email sent to {to_email}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        for unit in ('B', 'KB', 'MB', 'GB'):
            if abs(size_bytes) < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


# Module-level singleton
bid_store = BidDataStore(data_dir='data')
