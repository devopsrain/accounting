"""
SIEM (Security Information and Event Management) Routes
Dashboard and log viewer for tracking all data upload events.
"""

from flask import Blueprint, render_template, request, jsonify, send_file, redirect, url_for, flash
from siem_data_store import siem_store

siem_bp = Blueprint('siem', __name__, template_folder='templates')


@siem_bp.route('/')
def dashboard():
    """SIEM Dashboard with stats, alerts, and recent activity."""
    stats = siem_store.get_dashboard_stats()
    alerts = siem_store.get_alerts(acknowledged=False, limit=10)
    alert_counts = siem_store.get_alert_counts()
    recent_events = siem_store.get_all_events(limit=15)
    return render_template('siem/dashboard.html',
                           stats=stats, alerts=alerts,
                           alert_counts=alert_counts,
                           recent_events=recent_events)


@siem_bp.route('/events')
def event_log():
    """Full event log with filtering."""
    # Filters
    ip_filter = request.args.get('ip', '')
    module_filter = request.args.get('module', '')
    status_filter = request.args.get('status', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    if start_date or end_date:
        events = siem_store.get_events_by_date_range(start_date, end_date)
    elif ip_filter:
        events = siem_store.get_events_by_ip(ip_filter)
    elif module_filter:
        events = siem_store.get_events_by_module(module_filter)
    elif status_filter:
        events = siem_store.get_events_by_status(status_filter)
    else:
        events = siem_store.get_all_events(limit=500)

    # Apply additional filters in combination
    if ip_filter and not (start_date or end_date):
        pass  # already filtered
    elif ip_filter:
        events = [e for e in events if e.get('ip_address') == ip_filter]
    if module_filter and not (not ip_filter and not start_date and not end_date):
        events = [e for e in events if e.get('module') == module_filter]
    if status_filter and not (not ip_filter and not module_filter and not start_date and not end_date):
        events = [e for e in events if e.get('status') == status_filter]

    return render_template('siem/events.html',
                           events=events,
                           ip_filter=ip_filter,
                           module_filter=module_filter,
                           status_filter=status_filter,
                           start_date=start_date,
                           end_date=end_date)


@siem_bp.route('/events/<event_id>')
def event_detail(event_id):
    """Detailed view of a single event."""
    event = siem_store.get_event_by_id(event_id)
    if not event:
        flash('Event not found', 'danger')
        return redirect(url_for('siem.event_log'))
    return render_template('siem/event_detail.html', event=event)


@siem_bp.route('/ips')
def ip_tracker():
    """IP address tracking and analysis."""
    ip_summary = siem_store.get_ip_summary()
    return render_template('siem/ip_tracker.html', ip_summary=ip_summary)


@siem_bp.route('/alerts')
def alerts():
    """Alert management."""
    show = request.args.get('show', 'unacknowledged')
    if show == 'all':
        alert_list = siem_store.get_alerts(acknowledged=None)
    elif show == 'acknowledged':
        alert_list = siem_store.get_alerts(acknowledged=True)
    else:
        alert_list = siem_store.get_alerts(acknowledged=False)
    alert_counts = siem_store.get_alert_counts()
    return render_template('siem/alerts.html',
                           alerts=alert_list,
                           alert_counts=alert_counts,
                           show=show)


@siem_bp.route('/alerts/acknowledge/<alert_id>', methods=['POST'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert."""
    siem_store.acknowledge_alert(alert_id)
    flash('Alert acknowledged', 'success')
    return redirect(request.referrer or url_for('siem.alerts'))


@siem_bp.route('/export')
def export_events():
    """Export all events to Excel."""
    filepath = siem_store.export_events_to_excel()
    if not filepath:
        flash('No events to export', 'warning')
        return redirect(url_for('siem.dashboard'))
    return send_file(filepath,
                     as_attachment=True,
                     download_name='siem_upload_events.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
