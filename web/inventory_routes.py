"""
Inventory and Warehouse Management Routes

Flask Blueprint for comprehensive inventory management:
- Item Master (CRUD, import/export)
- Stock Movements (receipt, issue, transfer, adjustment)
- Inventory Valuation (FIFO, LIFO, weighted average)
- Stock Replenishment (alerts, purchase requisitions)
- Asset & Resource Allocation (event materials, rental items)
- Maintenance Scheduling (preventive & corrective)
- Inventory Reporting (stock levels, valuation, movements)
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
import pandas as pd
from datetime import datetime

from inventory_data_store import InventoryDataStore

inventory_bp = Blueprint('inventory', __name__, template_folder='templates')
inv_store = InventoryDataStore(data_dir='data')


# ======================================================================
# DASHBOARD
# ======================================================================
@inventory_bp.route('/')
def dashboard():
    summary = inv_store.get_dashboard_summary()
    return render_template('inventory/dashboard.html', summary=summary)


# ======================================================================
# ITEM MASTER MANAGEMENT
# ======================================================================
@inventory_bp.route('/items')
def items_list():
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    items = inv_store.get_all_items(
        status=status if status else None,
        category=category if category else None,
    )
    items.reverse()
    categories = inv_store.get_categories()
    return render_template('inventory/items_list.html', items=items, categories=categories,
                           selected_category=category, selected_status=status)


@inventory_bp.route('/items/add', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        item = {
            'name': request.form.get('name', '').strip(),
            'sku': request.form.get('sku', '').strip(),
            'category': request.form.get('category', '').strip(),
            'description': request.form.get('description', '').strip(),
            'unit': request.form.get('unit', 'pcs').strip(),
            'unit_price': float(request.form.get('unit_price', 0) or 0),
            'cost_price': float(request.form.get('cost_price', 0) or 0),
            'serial_number': request.form.get('serial_number', '').strip(),
            'batch_number': request.form.get('batch_number', '').strip(),
            'barcode': request.form.get('barcode', '').strip(),
            'current_stock': float(request.form.get('current_stock', 0) or 0),
            'min_stock_level': float(request.form.get('min_stock_level', 0) or 0),
            'reorder_point': float(request.form.get('reorder_point', 0) or 0),
            'reorder_quantity': float(request.form.get('reorder_quantity', 0) or 0),
            'location': request.form.get('location', '').strip(),
            'is_rentable': request.form.get('is_rentable', 'no'),
            'valuation_method': request.form.get('valuation_method', 'weighted_average'),
        }

        if not item['name']:
            flash('Item name is required', 'error')
            return render_template('inventory/add_item.html', item=item, categories=inv_store.get_categories())

        if not item['sku']:
            item['sku'] = inv_store.generate_sku(item['category'], item['name'])

        if inv_store.save_item(item):
            flash(f'Item "{item["name"]}" added successfully!', 'success')
            return redirect(url_for('inventory.items_list'))
        else:
            flash('Error saving item', 'error')

    return render_template('inventory/add_item.html', item={}, categories=inv_store.get_categories())


@inventory_bp.route('/items/edit/<item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    item = inv_store.get_item_by_id(item_id)
    if not item:
        flash('Item not found', 'error')
        return redirect(url_for('inventory.items_list'))

    if request.method == 'POST':
        item.update({
            'name': request.form.get('name', '').strip(),
            'sku': request.form.get('sku', '').strip(),
            'category': request.form.get('category', '').strip(),
            'description': request.form.get('description', '').strip(),
            'unit': request.form.get('unit', 'pcs').strip(),
            'unit_price': float(request.form.get('unit_price', 0) or 0),
            'cost_price': float(request.form.get('cost_price', 0) or 0),
            'serial_number': request.form.get('serial_number', '').strip(),
            'batch_number': request.form.get('batch_number', '').strip(),
            'barcode': request.form.get('barcode', '').strip(),
            'min_stock_level': float(request.form.get('min_stock_level', 0) or 0),
            'reorder_point': float(request.form.get('reorder_point', 0) or 0),
            'reorder_quantity': float(request.form.get('reorder_quantity', 0) or 0),
            'location': request.form.get('location', '').strip(),
            'is_rentable': request.form.get('is_rentable', 'no'),
            'valuation_method': request.form.get('valuation_method', 'weighted_average'),
        })

        if inv_store.save_item(item):
            flash('Item updated successfully!', 'success')
            return redirect(url_for('inventory.items_list'))
        else:
            flash('Error updating item', 'error')

    return render_template('inventory/edit_item.html', item=item, categories=inv_store.get_categories())


@inventory_bp.route('/items/delete/<item_id>', methods=['POST'])
def delete_item(item_id):
    if inv_store.delete_item(item_id):
        flash('Item deleted', 'success')
    else:
        flash('Error deleting item', 'error')
    return redirect(url_for('inventory.items_list'))


@inventory_bp.route('/items/import', methods=['GET', 'POST'])
def import_items():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not file.filename.lower().endswith(('.xlsx', '.xls')):
            flash('Please upload an Excel file (.xlsx or .xls)', 'error')
            return redirect(request.url)
        try:
            df = pd.read_excel(file, sheet_name=0)
            if df.empty:
                flash('The uploaded file contains no data', 'error')
                return redirect(request.url)
            result = inv_store.import_items_from_dataframe(df, file.filename)
            # SIEM: Log successful upload
            siem_store.log_upload_event(
                request, module='inventory', endpoint='/inventory/items/import',
                filename=file.filename, records_imported=result.get('imported', 0),
                status='success', details=f"Imported {result.get('imported', 0)} inventory items"
            )
            return render_template('inventory/import_result.html', result=result, filename=file.filename)
        except Exception as e:
            # SIEM: Log failed upload
            siem_store.log_upload_event(
                request, module='inventory', endpoint='/inventory/items/import',
                filename=file.filename if 'file' in dir() else '',
                status='failed', details=str(e)
            )
            flash(f'Error reading Excel file: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('inventory/import_items.html')


@inventory_bp.route('/items/export')
def export_items():
    filepath = inv_store.export_items_to_excel()
    if filepath:
        return send_file(filepath, as_attachment=True,
                         download_name=f"inventory_items_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    flash('Error exporting items', 'error')
    return redirect(url_for('inventory.items_list'))


@inventory_bp.route('/items/download-template')
def download_template():
    filepath = inv_store.generate_sample_excel()
    if filepath:
        return send_file(filepath, as_attachment=True, download_name='Inventory_Import_Template.xlsx')
    flash('Error generating template', 'error')
    return redirect(url_for('inventory.import_items'))


# ======================================================================
# STOCK MOVEMENTS
# ======================================================================
@inventory_bp.route('/movements')
def movements_list():
    mtype = request.args.get('type', '')
    movements = inv_store.get_all_movements(movement_type=mtype if mtype else None)
    movements.reverse()
    return render_template('inventory/movements_list.html', movements=movements, selected_type=mtype)


@inventory_bp.route('/movements/add', methods=['GET', 'POST'])
def add_movement():
    if request.method == 'POST':
        movement = {
            'item_id': request.form.get('item_id', ''),
            'movement_type': request.form.get('movement_type', ''),
            'quantity': float(request.form.get('quantity', 0) or 0),
            'unit_cost': float(request.form.get('unit_cost', 0) or 0),
            'from_location': request.form.get('from_location', '').strip(),
            'to_location': request.form.get('to_location', '').strip(),
            'reference_number': request.form.get('reference_number', '').strip(),
            'reason': request.form.get('reason', '').strip(),
            'date': request.form.get('date', datetime.now().strftime('%Y-%m-%d')),
            'approval_status': request.form.get('approval_status', 'approved'),
        }

        if not movement['item_id'] or not movement['movement_type'] or movement['quantity'] <= 0:
            flash('Item, movement type, and positive quantity are required', 'error')
            items = inv_store.get_all_items(status='active')
            return render_template('inventory/add_movement.html', movement=movement, items=items)

        if inv_store.save_movement(movement):
            flash('Stock movement recorded successfully!', 'success')
            return redirect(url_for('inventory.movements_list'))
        else:
            flash('Error saving movement', 'error')

    items = inv_store.get_all_items(status='active')
    return render_template('inventory/add_movement.html', movement={}, items=items)


@inventory_bp.route('/movements/approve/<movement_id>', methods=['POST'])
def approve_movement(movement_id):
    approved_by = request.form.get('approved_by', 'Admin')
    action = request.form.get('action', 'approve')
    if inv_store.approve_movement(movement_id, approved_by, approve=(action == 'approve')):
        flash(f'Movement {action}d successfully', 'success')
    else:
        flash('Error processing movement', 'error')
    return redirect(url_for('inventory.movements_list'))


# ======================================================================
# INVENTORY VALUATION
# ======================================================================
@inventory_bp.route('/valuation')
def valuation():
    method = request.args.get('method', '')
    valuations = inv_store.calculate_valuation(method=method if method else None)
    total_value = sum(v.get('total_value', 0) for v in valuations)
    return render_template('inventory/valuation.html', valuations=valuations,
                           total_value=total_value, selected_method=method)


# ======================================================================
# STOCK REPLENISHMENT
# ======================================================================
@inventory_bp.route('/replenishment')
def replenishment():
    low_stock = inv_store.get_low_stock_items()
    requisitions = inv_store.get_all_requisitions()
    requisitions.reverse()
    return render_template('inventory/replenishment.html', low_stock=low_stock, requisitions=requisitions)


@inventory_bp.route('/replenishment/auto-generate', methods=['POST'])
def auto_generate_requisitions():
    count = inv_store.auto_generate_requisitions()
    if count > 0:
        flash(f'Generated {count} purchase requisition(s)', 'success')
    else:
        flash('No new requisitions needed', 'info')
    return redirect(url_for('inventory.replenishment'))


@inventory_bp.route('/replenishment/add', methods=['GET', 'POST'])
def add_requisition():
    if request.method == 'POST':
        req = {
            'item_id': request.form.get('item_id', ''),
            'quantity_needed': float(request.form.get('quantity_needed', 0) or 0),
            'estimated_cost': float(request.form.get('estimated_cost', 0) or 0),
            'priority': request.form.get('priority', 'medium'),
            'requested_by': request.form.get('requested_by', '').strip(),
            'supplier': request.form.get('supplier', '').strip(),
            'notes': request.form.get('notes', '').strip(),
            'date': request.form.get('date', datetime.now().strftime('%Y-%m-%d')),
        }
        if inv_store.save_requisition(req):
            flash('Purchase requisition created!', 'success')
            return redirect(url_for('inventory.replenishment'))
        else:
            flash('Error creating requisition', 'error')

    items = inv_store.get_all_items(status='active')
    return render_template('inventory/add_requisition.html', req={}, items=items)


@inventory_bp.route('/replenishment/update/<req_id>', methods=['POST'])
def update_requisition(req_id):
    status = request.form.get('status', '')
    approved_by = request.form.get('approved_by', 'Admin')
    if inv_store.update_requisition_status(req_id, status, approved_by):
        flash(f'Requisition updated to: {status}', 'success')
    else:
        flash('Error updating requisition', 'error')
    return redirect(url_for('inventory.replenishment'))


# ======================================================================
# ASSET & RESOURCE ALLOCATION
# ======================================================================
@inventory_bp.route('/allocations')
def allocations_list():
    status = request.args.get('status', '')
    allocations = inv_store.get_all_allocations(status=status if status else None)
    allocations.reverse()
    overdue = inv_store.get_overdue_allocations()
    return render_template('inventory/allocations_list.html', allocations=allocations,
                           overdue=overdue, selected_status=status)


@inventory_bp.route('/allocations/add', methods=['GET', 'POST'])
def add_allocation():
    if request.method == 'POST':
        alloc = {
            'item_id': request.form.get('item_id', ''),
            'event_name': request.form.get('event_name', '').strip(),
            'allocated_quantity': float(request.form.get('allocated_quantity', 0) or 0),
            'allocation_date': request.form.get('allocation_date', datetime.now().strftime('%Y-%m-%d')),
            'expected_return_date': request.form.get('expected_return_date', ''),
            'allocated_by': request.form.get('allocated_by', '').strip(),
            'notes': request.form.get('notes', '').strip(),
        }

        if not alloc['item_id'] or not alloc['event_name'] or alloc['allocated_quantity'] <= 0:
            flash('Item, event name, and positive quantity are required', 'error')
            items = inv_store.get_all_items(status='active')
            return render_template('inventory/add_allocation.html', alloc=alloc, items=items)

        if inv_store.save_allocation(alloc):
            flash('Asset allocated successfully!', 'success')
            return redirect(url_for('inventory.allocations_list'))
        else:
            flash('Error saving allocation', 'error')

    items = inv_store.get_all_items(status='active')
    rentable = [i for i in items if i.get('is_rentable') == 'yes']
    return render_template('inventory/add_allocation.html', alloc={}, items=items, rentable_items=rentable)


@inventory_bp.route('/allocations/return/<alloc_id>', methods=['POST'])
def return_allocation(alloc_id):
    return_qty = float(request.form.get('return_quantity', 0) or 0)
    if return_qty <= 0:
        flash('Return quantity must be positive', 'error')
    elif inv_store.return_allocation(alloc_id, return_qty):
        flash('Return processed successfully!', 'success')
    else:
        flash('Error processing return', 'error')
    return redirect(url_for('inventory.allocations_list'))


# ======================================================================
# MAINTENANCE SCHEDULING
# ======================================================================
@inventory_bp.route('/maintenance')
def maintenance_list():
    status = request.args.get('status', '')
    maintenance = inv_store.get_all_maintenance(status=status if status else None)
    maintenance.reverse()
    upcoming = inv_store.get_upcoming_maintenance(days=30)
    overdue = inv_store.get_overdue_maintenance()
    return render_template('inventory/maintenance_list.html', maintenance=maintenance,
                           upcoming=upcoming, overdue=overdue, selected_status=status)


@inventory_bp.route('/maintenance/add', methods=['GET', 'POST'])
def add_maintenance():
    if request.method == 'POST':
        maint = {
            'item_id': request.form.get('item_id', ''),
            'maintenance_type': request.form.get('maintenance_type', 'preventive'),
            'description': request.form.get('description', '').strip(),
            'scheduled_date': request.form.get('scheduled_date', ''),
            'assigned_to': request.form.get('assigned_to', '').strip(),
            'cost': float(request.form.get('cost', 0) or 0),
            'notes': request.form.get('notes', '').strip(),
        }

        if not maint['item_id'] or not maint['scheduled_date']:
            flash('Item and scheduled date are required', 'error')
            items = inv_store.get_all_items(status='active')
            return render_template('inventory/add_maintenance.html', maint=maint, items=items)

        if inv_store.save_maintenance(maint):
            flash('Maintenance scheduled successfully!', 'success')
            return redirect(url_for('inventory.maintenance_list'))
        else:
            flash('Error scheduling maintenance', 'error')

    items = inv_store.get_all_items(status='active')
    return render_template('inventory/add_maintenance.html', maint={}, items=items)


@inventory_bp.route('/maintenance/update/<maint_id>', methods=['POST'])
def update_maintenance(maint_id):
    status = request.form.get('status', '')
    completed_date = request.form.get('completed_date', '')
    cost = float(request.form.get('cost', 0) or 0)
    if inv_store.update_maintenance_status(maint_id, status, completed_date, cost):
        flash(f'Maintenance updated to: {status}', 'success')
    else:
        flash('Error updating maintenance', 'error')
    return redirect(url_for('inventory.maintenance_list'))


# ======================================================================
# REPORTS
# ======================================================================
@inventory_bp.route('/reports')
def reports():
    return render_template('inventory/reports.html')


@inventory_bp.route('/reports/stock')
def stock_report():
    raw_items = inv_store.get_stock_report()
    total_value = sum(r.get('value', 0) for r in raw_items)
    out_of_stock = len([r for r in raw_items if r.get('stock_status') == 'out_of_stock'])
    low_stock = len([r for r in raw_items if r.get('stock_status') in ('low', 'reorder')])
    # Build structured report object expected by template
    report = {
        'summary': {
            'total_items': len(raw_items),
            'out_of_stock': out_of_stock,
            'low_stock': low_stock,
            'total_value': total_value,
        },
        'items': raw_items,
    }
    return render_template('inventory/report_stock.html', report=report,
                           total_value=total_value, out_of_stock=out_of_stock, low_stock=low_stock)


@inventory_bp.route('/reports/valuation')
def valuation_report():
    method = request.args.get('method', 'weighted_average')
    valuations = inv_store.calculate_valuation(method=method)
    total = sum(v.get('total_value', 0) for v in valuations)
    return render_template('inventory/report_valuation.html', valuations=valuations,
                           total=total, method=method)


@inventory_bp.route('/reports/movements')
def movement_report():
    start = request.args.get('start_date', '')
    end = request.args.get('end_date', '')
    raw_report = inv_store.get_movement_report(start_date=start, end_date=end)
    # Build structured report object expected by template
    if isinstance(raw_report, dict):
        movements = raw_report.get('movements', [])
        report = {
            'summary': {
                'total_movements': raw_report.get('total', len(movements)),
                'receipts': raw_report.get('receipts', 0),
                'issues': raw_report.get('issues', 0),
                'transfers': raw_report.get('transfers', 0),
                'adjustments': raw_report.get('adjustments', 0),
                'total_value': raw_report.get('total_receipt_value', 0) + raw_report.get('total_issue_value', 0),
            },
            'movements': movements,
        }
    else:
        report = {'summary': {'total_movements': 0, 'receipts': 0, 'issues': 0, 'transfers': 0, 'adjustments': 0, 'total_value': 0}, 'movements': []}
    return render_template('inventory/report_movements.html', report=report,
                           start_date=start, end_date=end)
