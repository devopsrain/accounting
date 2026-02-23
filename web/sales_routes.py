"""
Sales & Marketing Website Blueprint

Public-facing landing page for the Ethiopian Business Management System.
No authentication required — this is the sales pitch before sign-up.
"""

from flask import Blueprint, render_template, request, flash, redirect, url_for
import logging

logger = logging.getLogger(__name__)

sales_bp = Blueprint(
    'sales',
    __name__,
    template_folder='templates',
    url_prefix='/sales',
)


@sales_bp.route('/')
def landing():
    """Main sales landing page with hero, features, pricing, support tiers."""
    return render_template('sales/index.html')


@sales_bp.route('/contact', methods=['POST'])
def contact():
    """Handle the contact / demo-request form."""
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    company = request.form.get('company', '').strip()
    tier = request.form.get('tier', '').strip()
    message = request.form.get('message', '').strip()

    if not name or not email:
        flash('Please provide your name and email.', 'danger')
        return redirect(url_for('sales.landing') + '#contact')

    # Log the lead (in production, store in DB or send to CRM)
    logger.info(
        "SALES LEAD: name=%s  email=%s  company=%s  tier=%s  message=%s",
        name, email, company, tier, message,
    )
    flash('Thank you! Our team will contact you within 24 hours.', 'success')
    return redirect(url_for('sales.landing') + '#contact')
