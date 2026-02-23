"""
Multi-Company Web Portal Routes

Flask routes for multi-company user portal and management system
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime, date
from typing import Dict, List, Optional
import uuid

from models.multi_company import (
    Company, User, UserRole, MultiCompanyUserManager, 
    SubscriptionPlan, CompanyStatus, CompanyInvitation
)
from core.multi_company_payroll import MultiCompanyPayrollManager
from models.ethiopian_payroll import Employee, EmployeeCategory

# Initialize managers (in production, these would be database-backed)
try:
    # Try to load demo data
    from multicompany_demo_setup import setup_demo_data
    user_manager, payroll_manager = setup_demo_data()
    print("✓ Demo data loaded successfully")
except Exception as e:
    print(f"⚠️  Could not load demo data: {e}")
    # Fallback to empty managers
    user_manager = MultiCompanyUserManager()
    payroll_manager = MultiCompanyPayrollManager(user_manager)

# Create blueprint
multicompany_bp = Blueprint('multicompany', __name__, url_prefix='/company')

# Helper functions — delegate to centralised auth module
from auth_data_store import _hash_password as hash_password, _verify_password as verify_password

def get_current_user() -> Optional[User]:
    """Get current logged-in user"""
    if not session.get('logged_in'):
        return None
    user_id = session.get('user_id')
    if user_id:
        return user_manager.users.get(user_id)
    return None

def require_login():
    """Check if user is logged in"""
    return get_current_user() is not None

def require_company_access(company_id: str = None) -> bool:
    """Check if user has access to company"""
    user = get_current_user()
    if not user:
        return False
    
    target_company = company_id or session.get('current_company_id')
    return user.has_access_to_company(target_company) if target_company else False

# Authentication routes
@multicompany_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
            
        username = data.get('username')
        password = data.get('password')
        
        # Find user
        user = None
        for u in user_manager.users.values():
            if u.username == username or u.email == username:
                user = u
                break
        
        if user and verify_password(password, user.password_hash):
            # Set session — include shared auth keys so @login_required works
            session['user_id'] = user.user_id
            session['username'] = user.username
            session['full_name'] = user.full_name
            session['privilege_level'] = getattr(user, 'privilege_level', 'viewer')
            session['logged_in'] = True
            
            # Update login stats
            user.last_login = datetime.now()
            user.login_count += 1
            
            # If user has only one company, set it as default
            companies = user.get_companies()
            if len(companies) == 1:
                session['current_company_id'] = companies[0]
                payroll_manager.set_user_context(user.user_id, companies[0])
            
            redirect_url = '/company/dashboard' if len(companies) == 1 else '/company/select'
            
            if request.is_json:
                return jsonify({
                    'success': True, 
                    'user': user.full_name,
                    'companies_count': len(companies),
                    'redirect': redirect_url
                })
            else:
                flash(f'Welcome back, {user.full_name}!', 'success')
                return redirect(redirect_url)
        else:
            error_msg = 'Invalid credentials'
            if request.is_json:
                return jsonify({'success': False, 'error': error_msg}), 401
            else:
                flash(error_msg, 'error')
                return render_template('multicompany/login.html')
    
    return render_template('multicompany/login.html')

@multicompany_bp.route('/logout')
def logout():
    """User logout"""
    session.clear()
    return redirect(url_for('multicompany.login'))

@multicompany_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        data = request.get_json()
        
        # Check if username/email exists
        for user in user_manager.users.values():
            if user.username == data.get('username') or user.email == data.get('email'):
                return jsonify({'success': False, 'error': 'Username or email already exists'}), 400
        
        # Create user
        user_data = {
            'user_id': str(uuid.uuid4()),
            'username': data.get('username'),
            'email': data.get('email'),
            'password_hash': hash_password(data.get('password')),
            'first_name': data.get('first_name'),
            'last_name': data.get('last_name'),
            'phone': data.get('phone', ''),
        }
        
        user = user_manager.create_user(user_data)
        
        return jsonify({'success': True, 'message': 'Account created successfully'})
    
    return render_template('multicompany/register.html')

# Company selection and dashboard
@multicompany_bp.route('/select')
def select_company():
    """Company selection page"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    companies = user_manager.get_user_companies(user.user_id)
    
    return render_template('multicompany/company_select.html', 
                         user=user, companies=companies)

@multicompany_bp.route('/switch/<company_id>')
def switch_company(company_id: str):
    """Switch active company"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    success, message = payroll_manager.switch_company_context(user.user_id, company_id)
    
    if success:
        session['current_company_id'] = company_id
        return redirect(url_for('multicompany.dashboard'))
    else:
        flash(message, 'error')
        return redirect(url_for('multicompany.select_company'))

@multicompany_bp.route('/dashboard')
def dashboard():
    """Multi-company dashboard"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    current_company_id = session.get('current_company_id')
    
    if not current_company_id:
        return redirect(url_for('multicompany.select_company'))
    
    # Set payroll context
    payroll_manager.set_user_context(user.user_id, current_company_id)
    
    # Get company data
    company = user_manager.companies.get(current_company_id)
    company_summary = payroll_manager.get_company_summary()
    user_companies = payroll_manager.get_user_companies_summary(user.user_id)
    user_role = user.get_role_in_company(current_company_id)
    
    return render_template('multicompany/dashboard.html',
                         user=user,
                         company=company,
                         user_role=user_role,
                         company_summary=company_summary,
                         user_companies=user_companies)

# Company management
@multicompany_bp.route('/create', methods=['GET', 'POST'])
def create_company():
    """Create new company"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    if request.method == 'POST':
        data = request.get_json()
        user = get_current_user()
        
        company_data = {
            'company_id': str(uuid.uuid4()),
            'name': data.get('name'),
            'registration_number': data.get('registration_number'),
            'tin_number': data.get('tin_number'),
            'address': data.get('address'),
            'city': data.get('city', 'Addis Ababa'),
            'phone': data.get('phone', ''),
            'email': data.get('email', ''),
            'business_type': data.get('business_type', ''),
            'subscription_plan': SubscriptionPlan(data.get('subscription_plan', 'FREE')),
            'status': CompanyStatus.TRIAL
        }
        
        try:
            company = user_manager.create_company(company_data, user.user_id)
            payroll_manager.initialize_company_payroll(company.company_id)
            
            return jsonify({
                'success': True, 
                'company_id': company.company_id,
                'message': f'Company "{company.name}" created successfully'
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    return render_template('multicompany/create_company.html')

@multicompany_bp.route('/settings')
def company_settings():
    """Company settings page"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    
    if not company_id or not user.is_admin_in_company(company_id):
        flash('Access denied', 'error')
        return redirect(url_for('multicompany.dashboard'))
    
    company = user_manager.companies.get(company_id)
    company_users = user_manager.get_company_users(company_id)
    
    return render_template('multicompany/company_settings.html',
                         company=company,
                         company_users=company_users)

# User management
@multicompany_bp.route('/invite-user', methods=['POST'])
def invite_user():
    """Invite user to company"""
    if not require_login():
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    
    if not company_id or not user.is_admin_in_company(company_id):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    
    data = request.get_json()
    email = data.get('email')
    role = UserRole(data.get('role', 'EMPLOYEE'))
    message = data.get('message', '')
    
    try:
        invitation = user_manager.invite_user_to_company(
            company_id, user.user_id, email, role, message
        )
        
        # In production, send email here
        return jsonify({
            'success': True,
            'invitation_id': invitation.invitation_id,
            'message': f'Invitation sent to {email}'
        })
    except PermissionError as e:
        return jsonify({'success': False, 'error': str(e)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@multicompany_bp.route('/accept-invitation/<invitation_id>')
def accept_invitation(invitation_id: str):
    """Accept company invitation"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    success = user_manager.accept_invitation(invitation_id, user.user_id)
    
    if success:
        flash('Invitation accepted successfully', 'success')
    else:
        flash('Invalid or expired invitation', 'error')
    
    return redirect(url_for('multicompany.select_company'))

# Payroll routes (company-specific)
@multicompany_bp.route('/employees')
def employees():
    """Company employees list"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    company_id = session.get('current_company_id')
    if not require_company_access(company_id):
        return redirect(url_for('multicompany.select_company'))
    
    user = get_current_user()
    payroll_manager.set_user_context(user.user_id, company_id)
    
    context = payroll_manager.get_current_context()
    employees = list(context.employees.values()) if context else []
    
    return render_template('multicompany/employees.html',
                         employees=employees,
                         can_manage=payroll_manager.check_permission(UserRole.HR_MANAGER))

@multicompany_bp.route('/add-employee', methods=['POST'])
def add_employee():
    """Add employee to company"""
    if not require_login():
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    payroll_manager.set_user_context(user.user_id, company_id)
    
    data = request.get_json()
    
    employee_data = {
        'employee_id': str(uuid.uuid4()),
        'employee_number': data.get('employee_number'),
        'first_name': data.get('first_name'),
        'last_name': data.get('last_name'),
        'email': data.get('email'),
        'phone': data.get('phone', ''),
        'category': EmployeeCategory(data.get('category')),
        'base_salary': float(data.get('base_salary', 0)),
        'department': data.get('department', ''),
        'position': data.get('position', ''),
        'hire_date': datetime.strptime(data.get('hire_date'), '%Y-%m-%d').date() if data.get('hire_date') else date.today(),
        'bank_account': data.get('bank_account', ''),
        'tin_number': data.get('tin_number', ''),
    }
    
    success, message = payroll_manager.add_employee(employee_data)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400

@multicompany_bp.route('/payroll/calculate', methods=['POST'])
def calculate_payroll():
    """Calculate payroll for company"""
    if not require_login():
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    payroll_manager.set_user_context(user.user_id, company_id)
    
    data = request.get_json()
    month = int(data.get('month'))
    year = int(data.get('year'))
    employee_ids = data.get('employee_ids')  # Optional
    
    success, summary = payroll_manager.calculate_payroll(month, year, employee_ids)
    
    if success:
        return jsonify({
            'success': True,
            'summary': {
                'month': summary.month,
                'year': summary.year,
                'employees_count': len(summary.payslips),
                'total_gross': summary.total_gross_salary,
                'total_tax': summary.total_tax,
                'total_net': summary.total_net_salary,
                'total_pension_employer': summary.total_pension_employer
            }
        })
    else:
        return jsonify({'success': False, 'error': 'Payroll calculation failed'}), 400

@multicompany_bp.route('/payroll/payslip/<employee_id>/<int:month>/<int:year>')
def get_payslip(employee_id: str, month: int, year: int):
    """Get employee payslip"""
    if not require_login():
        return redirect(url_for('multicompany.login'))
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    payroll_manager.set_user_context(user.user_id, company_id)
    
    payslip = payroll_manager.get_employee_payslip(employee_id, month, year)
    
    if payslip:
        return render_template('multicompany/payslip.html', payslip=payslip)
    else:
        flash('Payslip not found or access denied', 'error')
        return redirect(url_for('multicompany.employees'))

# API endpoints for AJAX
@multicompany_bp.route('/api/company-summary')
def api_company_summary():
    """Get company summary data"""
    if not require_login():
        return jsonify({'error': 'Not logged in'}), 401
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    
    if not require_company_access(company_id):
        return jsonify({'error': 'Access denied'}), 403
    
    payroll_manager.set_user_context(user.user_id, company_id)
    summary = payroll_manager.get_company_summary()
    
    return jsonify(summary)

@multicompany_bp.route('/api/user-companies')
def api_user_companies():
    """Get user's companies"""
    if not require_login():
        return jsonify({'error': 'Not logged in'}), 401
    
    user = get_current_user()
    companies = payroll_manager.get_user_companies_summary(user.user_id)
    
    return jsonify({'companies': companies})

@multicompany_bp.route('/api/export-data')
def api_export_data():
    """Export company data"""
    if not require_login():
        return jsonify({'error': 'Not logged in'}), 401
    
    user = get_current_user()
    company_id = session.get('current_company_id')
    payroll_manager.set_user_context(user.user_id, company_id)
    
    data = payroll_manager.export_company_data('json')
    
    if data:
        return jsonify({'success': True, 'data': data})
    else:
        return jsonify({'error': 'Permission denied or export failed'}), 403