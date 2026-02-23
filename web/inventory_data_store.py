"""
Inventory and Warehouse Management Data Store

Parquet-based persistence for:
- Item Master Management (categories, SKUs, pricing, serial/batch numbers)
- Stock Movements (receipt, issue, transfer, adjustment with approval)
- Inventory Valuation (FIFO, LIFO, weighted average)
- Stock Replenishment (min/reorder levels, purchase requisitions)
- Asset & Resource Allocation (event materials, rental items)
- Maintenance Scheduling (preventive & corrective)
- Inventory Reporting (stock levels, valuation, movement, usage)
"""

import pandas as pd
import os
import uuid
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Tuple
import tempfile
import math
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


class InventoryDataStore:
    """Comprehensive inventory and warehouse management data store."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        # File paths
        self.items_file = os.path.join(data_dir, "inventory_items.parquet")
        self.categories_file = os.path.join(data_dir, "inventory_categories.parquet")
        self.movements_file = os.path.join(data_dir, "inventory_movements.parquet")
        self.allocations_file = os.path.join(data_dir, "inventory_allocations.parquet")
        self.maintenance_file = os.path.join(data_dir, "inventory_maintenance.parquet")
        self.requisitions_file = os.path.join(data_dir, "inventory_requisitions.parquet")
        self.import_history_file = os.path.join(data_dir, "inventory_import_history.parquet")

        # Schemas
        self.items_schema = {
            'id': 'string',
            'company_id': 'string',
            'sku': 'string',
            'name': 'string',
            'description': 'string',
            'category': 'string',
            'unit': 'string',
            'unit_price': 'float64',
            'cost_price': 'float64',
            'serial_number': 'string',
            'batch_number': 'string',
            'barcode': 'string',
            'current_stock': 'float64',
            'min_stock_level': 'float64',
            'reorder_point': 'float64',
            'reorder_quantity': 'float64',
            'location': 'string',
            'is_rentable': 'string',
            'status': 'string',
            'valuation_method': 'string',
            'created_at': 'string',
            'updated_at': 'string',
        }

        self.categories_schema = {
            'id': 'string',
            'name': 'string',
            'description': 'string',
            'parent_category': 'string',
            'created_at': 'string',
        }

        self.movements_schema = {
            'id': 'string',
            'item_id': 'string',
            'item_name': 'string',
            'movement_type': 'string',       # receipt, issue, transfer, adjustment
            'quantity': 'float64',
            'unit_cost': 'float64',
            'total_cost': 'float64',
            'from_location': 'string',
            'to_location': 'string',
            'reference_number': 'string',
            'reason': 'string',
            'approved_by': 'string',
            'approval_status': 'string',      # pending, approved, rejected
            'date': 'string',
            'created_at': 'string',
        }

        self.allocations_schema = {
            'id': 'string',
            'item_id': 'string',
            'item_name': 'string',
            'event_name': 'string',
            'allocated_quantity': 'float64',
            'returned_quantity': 'float64',
            'allocation_date': 'string',
            'expected_return_date': 'string',
            'actual_return_date': 'string',
            'status': 'string',               # allocated, partial_return, returned, overdue
            'allocated_by': 'string',
            'notes': 'string',
            'created_at': 'string',
        }

        self.maintenance_schema = {
            'id': 'string',
            'item_id': 'string',
            'item_name': 'string',
            'maintenance_type': 'string',     # preventive, corrective
            'description': 'string',
            'scheduled_date': 'string',
            'completed_date': 'string',
            'status': 'string',               # scheduled, in_progress, completed, overdue, cancelled
            'assigned_to': 'string',
            'cost': 'float64',
            'notes': 'string',
            'created_at': 'string',
        }

        self.requisitions_schema = {
            'id': 'string',
            'item_id': 'string',
            'item_name': 'string',
            'quantity_needed': 'float64',
            'current_stock': 'float64',
            'reorder_point': 'float64',
            'estimated_cost': 'float64',
            'priority': 'string',             # low, medium, high, critical
            'status': 'string',               # pending, approved, ordered, received, cancelled
            'requested_by': 'string',
            'approved_by': 'string',
            'supplier': 'string',
            'notes': 'string',
            'date': 'string',
            'created_at': 'string',
        }

        self.import_history_schema = {
            'id': 'string',
            'filename': 'string',
            'import_type': 'string',
            'import_date': 'string',
            'total_rows': 'int64',
            'imported_rows': 'int64',
            'errors': 'int64',
            'status': 'string',
        }

        self._initialize_files()

    def _initialize_files(self):
        """Create parquet files with proper schemas if they don't exist."""
        file_schema_pairs = [
            (self.items_file, self.items_schema),
            (self.categories_file, self.categories_schema),
            (self.movements_file, self.movements_schema),
            (self.allocations_file, self.allocations_schema),
            (self.maintenance_file, self.maintenance_schema),
            (self.requisitions_file, self.requisitions_schema),
            (self.import_history_file, self.import_history_schema),
        ]
        for filepath, schema in file_schema_pairs:
            if not os.path.exists(filepath):
                df = pd.DataFrame(columns=list(schema.keys()))
                for col, dtype in schema.items():
                    if dtype == 'int64':
                        df[col] = pd.array([], dtype='Int64')
                    else:
                        df[col] = df[col].astype(dtype)
                df.to_parquet(filepath, index=False)

    # ======================================================================
    # ITEM MASTER MANAGEMENT
    # ======================================================================
    def save_item(self, item: Dict[str, Any]) -> bool:
        """Save or update an inventory item."""
        try:
            df = pd.read_parquet(self.items_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            now = datetime.now().isoformat()

            # Inject company_id
            item['company_id'] = item.get('company_id') or _resolve_company_id()

            if 'id' not in item or not item['id']:
                item['id'] = f"ITM-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
                item['created_at'] = now
                item['updated_at'] = now
                if 'current_stock' not in item:
                    item['current_stock'] = 0.0
                if 'status' not in item:
                    item['status'] = 'active'
                if 'valuation_method' not in item:
                    item['valuation_method'] = 'weighted_average'
                if 'is_rentable' not in item:
                    item['is_rentable'] = 'no'
                df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
            else:
                item['updated_at'] = now
                idx = df.index[df['id'] == item['id']]
                if len(idx) > 0:
                    for key, value in item.items():
                        df.loc[idx[0], key] = value
                else:
                    item['created_at'] = now
                    df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)

            df.to_parquet(self.items_file, index=False)
            return True
        except Exception as e:
            print(f"Error saving item: {e}")
            return False

    def get_all_items(self, status: str = None, category: str = None, company_id: str = None) -> List[Dict]:
        """Get all items for the current company, optionally filtered by status or category."""
        try:
            df = pd.read_parquet(self.items_file)
            if 'company_id' not in df.columns:
                df['company_id'] = 'default'
            cid = _resolve_company_id(company_id)
            df = df[df['company_id'] == cid]
            if status:
                df = df[df['status'] == status]
            if category:
                df = df[df['category'] == category]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def get_item_by_id(self, item_id: str) -> Optional[Dict]:
        try:
            df = pd.read_parquet(self.items_file)
            match = df[df['id'] == item_id]
            if match.empty:
                return None
            return match.fillna('').iloc[0].to_dict()
        except Exception:
            return None

    def delete_item(self, item_id: str) -> bool:
        try:
            df = pd.read_parquet(self.items_file)
            df = df[df['id'] != item_id]
            df.to_parquet(self.items_file, index=False)
            return True
        except Exception:
            return False

    def get_categories(self) -> List[str]:
        """Get distinct category names from items."""
        try:
            df = pd.read_parquet(self.items_file)
            cats = df['category'].dropna().unique().tolist()
            return sorted([c for c in cats if c])
        except Exception:
            return []

    def generate_sku(self, category: str, name: str) -> str:
        """Auto-generate a SKU from category and name."""
        cat_code = ''.join(c for c in category[:3].upper() if c.isalpha()) if category else 'GEN'
        name_code = ''.join(c for c in name[:3].upper() if c.isalpha()) if name else 'ITM'
        seq = uuid.uuid4().hex[:4].upper()
        return f"{cat_code}-{name_code}-{seq}"

    # ======================================================================
    # STOCK MOVEMENT
    # ======================================================================
    def save_movement(self, movement: Dict[str, Any]) -> bool:
        """Record a stock movement and update item stock levels."""
        try:
            df = pd.read_parquet(self.movements_file)
            now = datetime.now().isoformat()

            if 'id' not in movement or not movement['id']:
                movement['id'] = f"MOV-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in movement:
                movement['created_at'] = now
            if 'approval_status' not in movement:
                movement['approval_status'] = 'approved'
            if 'total_cost' not in movement:
                qty = float(movement.get('quantity', 0))
                uc = float(movement.get('unit_cost', 0))
                movement['total_cost'] = qty * uc

            # Resolve item name
            if movement.get('item_id') and not movement.get('item_name'):
                item = self.get_item_by_id(movement['item_id'])
                if item:
                    movement['item_name'] = item.get('name', '')

            df = pd.concat([df, pd.DataFrame([movement])], ignore_index=True)
            df.to_parquet(self.movements_file, index=False)

            # Update item stock level if approved
            if movement.get('approval_status') == 'approved':
                self._update_stock_from_movement(movement)

            return True
        except Exception as e:
            print(f"Error saving movement: {e}")
            return False

    def _update_stock_from_movement(self, movement: Dict):
        """Adjust item current_stock based on movement type."""
        try:
            item_id = movement.get('item_id')
            if not item_id:
                return
            items_df = pd.read_parquet(self.items_file)
            idx = items_df.index[items_df['id'] == item_id]
            if len(idx) == 0:
                return

            qty = float(movement.get('quantity', 0))
            mtype = movement.get('movement_type', '')
            current = float(items_df.loc[idx[0], 'current_stock'] or 0)

            if mtype == 'receipt':
                items_df.loc[idx[0], 'current_stock'] = current + qty
            elif mtype == 'issue':
                items_df.loc[idx[0], 'current_stock'] = max(0, current - qty)
            elif mtype == 'adjustment':
                items_df.loc[idx[0], 'current_stock'] = qty  # absolute set
            # transfer doesn't change total stock (same warehouse system)

            items_df.loc[idx[0], 'updated_at'] = datetime.now().isoformat()
            items_df.to_parquet(self.items_file, index=False)
        except Exception as e:
            print(f"Error updating stock: {e}")

    def get_all_movements(self, item_id: str = None, movement_type: str = None) -> List[Dict]:
        try:
            df = pd.read_parquet(self.movements_file)
            if item_id:
                df = df[df['item_id'] == item_id]
            if movement_type:
                df = df[df['movement_type'] == movement_type]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def approve_movement(self, movement_id: str, approved_by: str, approve: bool = True) -> bool:
        """Approve or reject a pending movement."""
        try:
            df = pd.read_parquet(self.movements_file)
            idx = df.index[df['id'] == movement_id]
            if len(idx) == 0:
                return False

            new_status = 'approved' if approve else 'rejected'
            df.loc[idx[0], 'approval_status'] = new_status
            df.loc[idx[0], 'approved_by'] = approved_by
            df.to_parquet(self.movements_file, index=False)

            if approve:
                movement = df.loc[idx[0]].to_dict()
                self._update_stock_from_movement(movement)

            return True
        except Exception:
            return False

    # ======================================================================
    # INVENTORY VALUATION
    # ======================================================================
    def calculate_valuation(self, item_id: str = None, method: str = None) -> List[Dict]:
        """Calculate inventory valuation using FIFO, LIFO or Weighted Average."""
        try:
            items = self.get_all_items(status='active')
            if item_id:
                items = [i for i in items if i['id'] == item_id]

            results = []
            for item in items:
                val_method = method or item.get('valuation_method', 'weighted_average')
                movements = self.get_all_movements(item_id=item['id'])
                receipts = [m for m in movements if m['movement_type'] == 'receipt'
                            and m.get('approval_status') == 'approved']
                issues = [m for m in movements if m['movement_type'] == 'issue'
                          and m.get('approval_status') == 'approved']

                current_stock = float(item.get('current_stock', 0))

                if val_method == 'fifo':
                    unit_val = self._fifo_valuation(receipts, issues)
                elif val_method == 'lifo':
                    unit_val = self._lifo_valuation(receipts, issues)
                else:
                    unit_val = self._weighted_avg_valuation(receipts)

                total_val = current_stock * unit_val

                results.append({
                    'item_id': item['id'],
                    'item_name': item.get('name', ''),
                    'sku': item.get('sku', ''),
                    'category': item.get('category', ''),
                    'current_stock': current_stock,
                    'unit': item.get('unit', ''),
                    'valuation_method': val_method,
                    'unit_value': round(unit_val, 2),
                    'total_value': round(total_val, 2),
                })

            return results
        except Exception as e:
            print(f"Error calculating valuation: {e}")
            return []

    def _weighted_avg_valuation(self, receipts: List[Dict]) -> float:
        total_cost = 0.0
        total_qty = 0.0
        for r in receipts:
            qty = float(r.get('quantity', 0))
            cost = float(r.get('unit_cost', 0))
            total_cost += qty * cost
            total_qty += qty
        return (total_cost / total_qty) if total_qty > 0 else 0.0

    def _fifo_valuation(self, receipts: List[Dict], issues: List[Dict]) -> float:
        """FIFO: earliest purchases consumed first."""
        # Sort receipts by date ascending
        sorted_r = sorted(receipts, key=lambda x: x.get('date', ''))
        layers = [(float(r.get('quantity', 0)), float(r.get('unit_cost', 0))) for r in sorted_r]

        total_issued = sum(float(i.get('quantity', 0)) for i in issues)
        remaining = total_issued

        # Consume from oldest first
        for i, (qty, cost) in enumerate(layers):
            if remaining <= 0:
                break
            consumed = min(qty, remaining)
            layers[i] = (qty - consumed, cost)
            remaining -= consumed

        # Remaining layers represent current stock value
        total_val = sum(q * c for q, c in layers if q > 0)
        total_qty = sum(q for q, c in layers if q > 0)
        return (total_val / total_qty) if total_qty > 0 else 0.0

    def _lifo_valuation(self, receipts: List[Dict], issues: List[Dict]) -> float:
        """LIFO: latest purchases consumed first."""
        sorted_r = sorted(receipts, key=lambda x: x.get('date', ''), reverse=True)
        layers = [(float(r.get('quantity', 0)), float(r.get('unit_cost', 0))) for r in sorted_r]

        total_issued = sum(float(i.get('quantity', 0)) for i in issues)
        remaining = total_issued

        for i, (qty, cost) in enumerate(layers):
            if remaining <= 0:
                break
            consumed = min(qty, remaining)
            layers[i] = (qty - consumed, cost)
            remaining -= consumed

        total_val = sum(q * c for q, c in layers if q > 0)
        total_qty = sum(q for q, c in layers if q > 0)
        return (total_val / total_qty) if total_qty > 0 else 0.0

    # ======================================================================
    # STOCK REPLENISHMENT
    # ======================================================================
    def get_low_stock_items(self) -> List[Dict]:
        """Items at or below minimum stock or reorder point."""
        try:
            items = self.get_all_items(status='active')
            low = []
            for item in items:
                stock = float(item.get('current_stock', 0))
                reorder = float(item.get('reorder_point', 0))
                min_level = float(item.get('min_stock_level', 0))
                if reorder > 0 and stock <= reorder:
                    item['alert_type'] = 'reorder'
                    low.append(item)
                elif min_level > 0 and stock <= min_level:
                    item['alert_type'] = 'minimum'
                    low.append(item)
            return low
        except Exception:
            return []

    def save_requisition(self, req: Dict[str, Any]) -> bool:
        try:
            df = pd.read_parquet(self.requisitions_file)
            now = datetime.now().isoformat()

            if 'id' not in req or not req['id']:
                req['id'] = f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in req:
                req['created_at'] = now
            if 'status' not in req:
                req['status'] = 'pending'

            if req.get('item_id') and not req.get('item_name'):
                item = self.get_item_by_id(req['item_id'])
                if item:
                    req['item_name'] = item.get('name', '')

            df = pd.concat([df, pd.DataFrame([req])], ignore_index=True)
            df.to_parquet(self.requisitions_file, index=False)
            return True
        except Exception as e:
            print(f"Error saving requisition: {e}")
            return False

    def get_all_requisitions(self, status: str = None) -> List[Dict]:
        try:
            df = pd.read_parquet(self.requisitions_file)
            if status:
                df = df[df['status'] == status]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def update_requisition_status(self, req_id: str, status: str, approved_by: str = '') -> bool:
        try:
            df = pd.read_parquet(self.requisitions_file)
            idx = df.index[df['id'] == req_id]
            if len(idx) == 0:
                return False
            df.loc[idx[0], 'status'] = status
            if approved_by:
                df.loc[idx[0], 'approved_by'] = approved_by
            df.to_parquet(self.requisitions_file, index=False)
            return True
        except Exception:
            return False

    def auto_generate_requisitions(self) -> int:
        """Generate purchase requisitions for items below reorder point."""
        low_items = self.get_low_stock_items()
        existing = self.get_all_requisitions()
        pending_item_ids = {r['item_id'] for r in existing if r.get('status') in ('pending', 'approved', 'ordered')}
        count = 0
        for item in low_items:
            if item['id'] in pending_item_ids:
                continue
            req = {
                'item_id': item['id'],
                'item_name': item.get('name', ''),
                'quantity_needed': float(item.get('reorder_quantity', 0)) or 10.0,
                'current_stock': float(item.get('current_stock', 0)),
                'reorder_point': float(item.get('reorder_point', 0)),
                'estimated_cost': float(item.get('cost_price', 0)) * (float(item.get('reorder_quantity', 0)) or 10),
                'priority': 'critical' if float(item.get('current_stock', 0)) == 0 else 'high',
                'status': 'pending',
                'requested_by': 'System (Auto)',
                'date': datetime.now().strftime('%Y-%m-%d'),
            }
            if self.save_requisition(req):
                count += 1
        return count

    # ======================================================================
    # ASSET & RESOURCE ALLOCATION (Event Use)
    # ======================================================================
    def save_allocation(self, alloc: Dict[str, Any]) -> bool:
        try:
            df = pd.read_parquet(self.allocations_file)
            now = datetime.now().isoformat()

            if 'id' not in alloc or not alloc['id']:
                alloc['id'] = f"ALC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in alloc:
                alloc['created_at'] = now
            if 'status' not in alloc:
                alloc['status'] = 'allocated'
            if 'returned_quantity' not in alloc:
                alloc['returned_quantity'] = 0.0

            if alloc.get('item_id') and not alloc.get('item_name'):
                item = self.get_item_by_id(alloc['item_id'])
                if item:
                    alloc['item_name'] = item.get('name', '')

            df = pd.concat([df, pd.DataFrame([alloc])], ignore_index=True)
            df.to_parquet(self.allocations_file, index=False)

            # Issue stock for allocation
            if alloc.get('item_id'):
                self.save_movement({
                    'item_id': alloc['item_id'],
                    'movement_type': 'issue',
                    'quantity': float(alloc.get('allocated_quantity', 0)),
                    'reason': f"Allocated to event: {alloc.get('event_name', '')}",
                    'reference_number': alloc['id'],
                    'date': alloc.get('allocation_date', datetime.now().strftime('%Y-%m-%d')),
                    'approval_status': 'approved',
                })

            return True
        except Exception as e:
            print(f"Error saving allocation: {e}")
            return False

    def return_allocation(self, alloc_id: str, return_qty: float) -> bool:
        """Process a return for an allocation."""
        try:
            df = pd.read_parquet(self.allocations_file)
            idx = df.index[df['id'] == alloc_id]
            if len(idx) == 0:
                return False

            row = df.loc[idx[0]]
            allocated = float(row.get('allocated_quantity', 0))
            already_returned = float(row.get('returned_quantity', 0))
            new_returned = already_returned + return_qty

            df.loc[idx[0], 'returned_quantity'] = new_returned
            df.loc[idx[0], 'actual_return_date'] = datetime.now().strftime('%Y-%m-%d')

            if new_returned >= allocated:
                df.loc[idx[0], 'status'] = 'returned'
            else:
                df.loc[idx[0], 'status'] = 'partial_return'

            df.to_parquet(self.allocations_file, index=False)

            # Receipt stock back
            item_id = row.get('item_id', '')
            if item_id:
                self.save_movement({
                    'item_id': item_id,
                    'movement_type': 'receipt',
                    'quantity': return_qty,
                    'reason': f"Returned from event: {row.get('event_name', '')}",
                    'reference_number': alloc_id,
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'approval_status': 'approved',
                })

            return True
        except Exception as e:
            print(f"Error returning allocation: {e}")
            return False

    def get_all_allocations(self, status: str = None) -> List[Dict]:
        try:
            df = pd.read_parquet(self.allocations_file)
            if status:
                df = df[df['status'] == status]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def get_overdue_allocations(self) -> List[Dict]:
        """Allocations past their expected return date."""
        try:
            df = pd.read_parquet(self.allocations_file)
            today = datetime.now().strftime('%Y-%m-%d')
            overdue_mask = (
                df['status'].isin(['allocated', 'partial_return'])
                & (df['expected_return_date'] < today)
                & (df['expected_return_date'] != '')
            )
            overdue_rows = df.loc[overdue_mask]
            if not overdue_rows.empty:
                # Batch-update all overdue rows and write once
                df.loc[overdue_mask, 'status'] = 'overdue'
                df.to_parquet(self.allocations_file, index=False)
            return overdue_rows.fillna('').to_dict('records')
        except Exception:
            return []

    # ======================================================================
    # MAINTENANCE SCHEDULING
    # ======================================================================
    def save_maintenance(self, maint: Dict[str, Any]) -> bool:
        try:
            df = pd.read_parquet(self.maintenance_file)
            now = datetime.now().isoformat()

            if 'id' not in maint or not maint['id']:
                maint['id'] = f"MNT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
            if 'created_at' not in maint:
                maint['created_at'] = now
            if 'status' not in maint:
                maint['status'] = 'scheduled'

            if maint.get('item_id') and not maint.get('item_name'):
                item = self.get_item_by_id(maint['item_id'])
                if item:
                    maint['item_name'] = item.get('name', '')

            df = pd.concat([df, pd.DataFrame([maint])], ignore_index=True)
            df.to_parquet(self.maintenance_file, index=False)
            return True
        except Exception as e:
            print(f"Error saving maintenance: {e}")
            return False

    def update_maintenance_status(self, maint_id: str, status: str, completed_date: str = '', cost: float = 0) -> bool:
        try:
            df = pd.read_parquet(self.maintenance_file)
            idx = df.index[df['id'] == maint_id]
            if len(idx) == 0:
                return False
            df.loc[idx[0], 'status'] = status
            if completed_date:
                df.loc[idx[0], 'completed_date'] = completed_date
            if cost:
                df.loc[idx[0], 'cost'] = cost
            df.to_parquet(self.maintenance_file, index=False)
            return True
        except Exception:
            return False

    def get_all_maintenance(self, status: str = None, item_id: str = None) -> List[Dict]:
        try:
            df = pd.read_parquet(self.maintenance_file)
            if status:
                df = df[df['status'] == status]
            if item_id:
                df = df[df['item_id'] == item_id]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def get_upcoming_maintenance(self, days: int = 30) -> List[Dict]:
        """Get maintenance tasks scheduled within the next N days."""
        try:
            df = pd.read_parquet(self.maintenance_file)
            today = datetime.now().strftime('%Y-%m-%d')
            future = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            df = df[df['status'].isin(['scheduled'])]
            df = df[(df['scheduled_date'] >= today) & (df['scheduled_date'] <= future)]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    def get_overdue_maintenance(self) -> List[Dict]:
        """Get maintenance tasks past their scheduled date."""
        try:
            df = pd.read_parquet(self.maintenance_file)
            today = datetime.now().strftime('%Y-%m-%d')
            df = df[df['status'] == 'scheduled']
            df = df[df['scheduled_date'] < today]
            return df.fillna('').to_dict('records')
        except Exception:
            return []

    # ======================================================================
    # EXCEL IMPORT / EXPORT
    # ======================================================================
    def import_items_from_dataframe(self, df: pd.DataFrame, filename: str = '') -> Dict:
        """Import items from an Excel DataFrame."""
        result = {'success': False, 'message': '', 'total_rows': 0, 'imported': 0, 'errors': []}
        try:
            df.columns = [str(c).strip().lower().replace(' ', '_').replace('-', '_') for c in df.columns]
            result['total_rows'] = len(df)

            col_map = {
                'name': self._find_col(df.columns, ['name', 'item_name', 'product', 'product_name', 'item']),
                'sku': self._find_col(df.columns, ['sku', 'item_code', 'code', 'product_code']),
                'category': self._find_col(df.columns, ['category', 'cat', 'group', 'item_group', 'type']),
                'description': self._find_col(df.columns, ['description', 'desc', 'details', 'notes']),
                'unit': self._find_col(df.columns, ['unit', 'uom', 'unit_of_measure', 'measure']),
                'unit_price': self._find_col(df.columns, ['unit_price', 'price', 'selling_price', 'sell_price']),
                'cost_price': self._find_col(df.columns, ['cost_price', 'cost', 'purchase_price', 'buy_price']),
                'serial_number': self._find_col(df.columns, ['serial_number', 'serial', 'serial_no', 'sn']),
                'batch_number': self._find_col(df.columns, ['batch_number', 'batch', 'batch_no', 'lot']),
                'barcode': self._find_col(df.columns, ['barcode', 'bar_code', 'upc', 'ean']),
                'current_stock': self._find_col(df.columns, ['current_stock', 'stock', 'quantity', 'qty', 'on_hand']),
                'min_stock_level': self._find_col(df.columns, ['min_stock_level', 'min_stock', 'minimum', 'min_qty']),
                'reorder_point': self._find_col(df.columns, ['reorder_point', 'reorder_level', 'reorder']),
                'reorder_quantity': self._find_col(df.columns, ['reorder_quantity', 'reorder_qty', 'order_qty']),
                'location': self._find_col(df.columns, ['location', 'warehouse', 'bin', 'shelf']),
            }

            for idx, row in df.iterrows():
                try:
                    name = self._safe_str(row, col_map.get('name'))
                    if not name:
                        result['errors'].append(f"Row {idx+2}: Missing item name")
                        continue

                    category = self._safe_str(row, col_map.get('category'))
                    item = {
                        'name': name,
                        'sku': self._safe_str(row, col_map.get('sku')) or self.generate_sku(category, name),
                        'category': category,
                        'description': self._safe_str(row, col_map.get('description')),
                        'unit': self._safe_str(row, col_map.get('unit')) or 'pcs',
                        'unit_price': self._safe_float(row, col_map.get('unit_price')),
                        'cost_price': self._safe_float(row, col_map.get('cost_price')),
                        'serial_number': self._safe_str(row, col_map.get('serial_number')),
                        'batch_number': self._safe_str(row, col_map.get('batch_number')),
                        'barcode': self._safe_str(row, col_map.get('barcode')),
                        'current_stock': self._safe_float(row, col_map.get('current_stock')),
                        'min_stock_level': self._safe_float(row, col_map.get('min_stock_level')),
                        'reorder_point': self._safe_float(row, col_map.get('reorder_point')),
                        'reorder_quantity': self._safe_float(row, col_map.get('reorder_quantity')),
                        'location': self._safe_str(row, col_map.get('location')),
                    }
                    if self.save_item(item):
                        result['imported'] += 1
                    else:
                        result['errors'].append(f"Row {idx+2}: Failed to save")
                except Exception as e:
                    result['errors'].append(f"Row {idx+2}: {str(e)}")

            result['success'] = True
            result['message'] = f"Imported {result['imported']} of {result['total_rows']} items."
            self._save_import_history('items', filename, result)
        except Exception as e:
            result['message'] = f"Import failed: {str(e)}"
            result['errors'].append(str(e))
        return result

    def export_items_to_excel(self) -> Optional[str]:
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()
            df = pd.read_parquet(self.items_file)
            cols = ['sku', 'name', 'category', 'description', 'unit', 'unit_price', 'cost_price',
                    'current_stock', 'min_stock_level', 'reorder_point', 'reorder_quantity',
                    'location', 'serial_number', 'batch_number', 'barcode', 'is_rentable', 'status']
            export_df = df[[c for c in cols if c in df.columns]].copy()
            export_df.columns = [c.replace('_', ' ').title() for c in export_df.columns]
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                export_df.to_excel(writer, sheet_name='Items', index=False)
            return tmp.name
        except Exception as e:
            print(f"Error exporting items: {e}")
            return None

    def generate_sample_excel(self) -> Optional[str]:
        """Generate a sample/template Excel file for item imports."""
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
            tmp.close()
            sample = [
                {'Name': 'Sound System - JBL PRX', 'SKU': 'AUD-SND-001', 'Category': 'Audio Equipment',
                 'Unit': 'set', 'Unit Price': 45000, 'Cost Price': 35000, 'Current Stock': 10,
                 'Min Stock Level': 2, 'Reorder Point': 3, 'Reorder Quantity': 5, 'Location': 'Warehouse A'},
                {'Name': 'LED Stage Light 200W', 'SKU': 'LGT-LED-002', 'Category': 'Lighting',
                 'Unit': 'pcs', 'Unit Price': 8500, 'Cost Price': 6000, 'Current Stock': 50,
                 'Min Stock Level': 10, 'Reorder Point': 15, 'Reorder Quantity': 20, 'Location': 'Warehouse A'},
                {'Name': 'Round Banquet Table 6ft', 'SKU': 'FRN-TBL-003', 'Category': 'Furniture',
                 'Unit': 'pcs', 'Unit Price': 3500, 'Cost Price': 2200, 'Current Stock': 100,
                 'Min Stock Level': 20, 'Reorder Point': 30, 'Reorder Quantity': 25, 'Location': 'Warehouse B'},
                {'Name': 'White Chair Cover', 'SKU': 'DEC-CHR-004', 'Category': 'Decor',
                 'Unit': 'pcs', 'Unit Price': 150, 'Cost Price': 80, 'Current Stock': 500,
                 'Min Stock Level': 50, 'Reorder Point': 100, 'Reorder Quantity': 200, 'Location': 'Warehouse B'},
                {'Name': 'Projector Epson 5000L', 'SKU': 'AV-PRJ-005', 'Category': 'AV Equipment',
                 'Unit': 'pcs', 'Unit Price': 65000, 'Cost Price': 52000, 'Current Stock': 5,
                 'Min Stock Level': 1, 'Reorder Point': 2, 'Reorder Quantity': 3, 'Location': 'Warehouse A',
                 'Serial Number': 'EP-5K-2026-001'},
            ]
            instructions = pd.DataFrame({
                'Column': ['Name', 'SKU', 'Category', 'Unit', 'Unit Price', 'Cost Price',
                           'Current Stock', 'Min Stock Level', 'Reorder Point', 'Reorder Quantity',
                           'Location', 'Serial Number', 'Batch Number', 'Barcode', 'Description'],
                'Required': ['Yes', 'Auto-gen if blank', 'No', 'No (default: pcs)', 'No', 'No',
                             'No (default: 0)', 'No', 'No', 'No', 'No', 'No', 'No', 'No', 'No'],
                'Description': [
                    'Item name', 'Stock keeping unit code', 'Item category/group',
                    'Unit of measure (pcs, kg, set, etc.)', 'Selling price in ETB', 'Purchase/cost price in ETB',
                    'Current quantity on hand', 'Minimum stock before alert', 'Stock level that triggers reorder',
                    'Quantity to order when reorder triggered', 'Warehouse/bin location',
                    'Serial number for tracked items', 'Batch/lot number', 'Barcode/UPC', 'Item description',
                ],
            })
            with pd.ExcelWriter(tmp.name, engine='openpyxl') as writer:
                pd.DataFrame(sample).to_excel(writer, sheet_name='Items', index=False)
                instructions.to_excel(writer, sheet_name='Instructions', index=False)
            return tmp.name
        except Exception as e:
            print(f"Error generating sample: {e}")
            return None

    # ======================================================================
    # REPORTING / SUMMARY
    # ======================================================================
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics."""
        try:
            items = self.get_all_items()
            active_items = [i for i in items if i.get('status') == 'active']
            movements = self.get_all_movements()
            allocations = self.get_all_allocations()
            active_allocs = [a for a in allocations if a.get('status') in ('allocated', 'partial_return', 'overdue')]
            maintenance = self.get_all_maintenance()
            upcoming_maint = self.get_upcoming_maintenance(days=7)
            overdue_maint = self.get_overdue_maintenance()
            low_stock = self.get_low_stock_items()
            requisitions = self.get_all_requisitions()
            pending_reqs = [r for r in requisitions if r.get('status') == 'pending']

            total_stock_value = sum(
                float(i.get('current_stock', 0)) * float(i.get('cost_price', 0))
                for i in active_items
            )

            categories = list(set(i.get('category', 'Uncategorized') for i in items if i.get('category')))

            return {
                'total_items': len(items),
                'active_items': len(active_items),
                'total_stock_value': round(total_stock_value, 2),
                'categories': len(categories),
                'total_movements': len(movements),
                'active_allocations': len(active_allocs),
                'low_stock_count': len(low_stock),
                'upcoming_maintenance': len(upcoming_maint),
                'overdue_maintenance': len(overdue_maint),
                'pending_requisitions': len(pending_reqs),
                'low_stock_items': low_stock[:5],
                'recent_movements': sorted(movements, key=lambda x: x.get('created_at', ''), reverse=True)[:5],
                'upcoming_maint_list': upcoming_maint[:5],
                'overdue_maint_list': overdue_maint[:5],
            }
        except Exception as e:
            print(f"Error getting dashboard summary: {e}")
            return {
                'total_items': 0, 'active_items': 0, 'total_stock_value': 0,
                'categories': 0, 'total_movements': 0, 'active_allocations': 0,
                'low_stock_count': 0, 'upcoming_maintenance': 0, 'overdue_maintenance': 0,
                'pending_requisitions': 0, 'low_stock_items': [], 'recent_movements': [],
                'upcoming_maint_list': [], 'overdue_maint_list': [],
            }

    def get_stock_report(self) -> List[Dict]:
        """Stock level report for all items."""
        items = self.get_all_items(status='active')
        report = []
        for item in items:
            stock = float(item.get('current_stock', 0))
            min_lvl = float(item.get('min_stock_level', 0))
            reorder = float(item.get('reorder_point', 0))

            if stock == 0:
                stock_status = 'out_of_stock'
            elif reorder > 0 and stock <= reorder:
                stock_status = 'reorder'
            elif min_lvl > 0 and stock <= min_lvl:
                stock_status = 'low'
            else:
                stock_status = 'adequate'

            report.append({
                'id': item['id'],
                'sku': item.get('sku', ''),
                'name': item.get('name', ''),
                'category': item.get('category', ''),
                'current_stock': stock,
                'unit': item.get('unit', ''),
                'min_stock_level': min_lvl,
                'reorder_point': reorder,
                'location': item.get('location', ''),
                'stock_status': stock_status,
                'value': round(stock * float(item.get('cost_price', 0)), 2),
            })
        return report

    def get_movement_report(self, start_date: str = '', end_date: str = '') -> Dict:
        """Movement summary report."""
        movements = self.get_all_movements()
        if start_date:
            movements = [m for m in movements if m.get('date', '') >= start_date]
        if end_date:
            movements = [m for m in movements if m.get('date', '') <= end_date]

        receipts = [m for m in movements if m['movement_type'] == 'receipt']
        issues = [m for m in movements if m['movement_type'] == 'issue']
        transfers = [m for m in movements if m['movement_type'] == 'transfer']
        adjustments = [m for m in movements if m['movement_type'] == 'adjustment']

        return {
            'total': len(movements),
            'receipts': len(receipts),
            'issues': len(issues),
            'transfers': len(transfers),
            'adjustments': len(adjustments),
            'total_receipt_value': sum(float(m.get('total_cost', 0)) for m in receipts),
            'total_issue_value': sum(float(m.get('total_cost', 0)) for m in issues),
            'movements': movements,
        }

    # ======================================================================
    # HELPERS
    # ======================================================================
    def _save_import_history(self, import_type: str, filename: str, result: Dict):
        try:
            df = pd.read_parquet(self.import_history_file)
            row = {
                'id': f"IMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}",
                'filename': os.path.basename(filename) if filename else 'unknown',
                'import_type': import_type,
                'import_date': datetime.now().isoformat(),
                'total_rows': result.get('total_rows', 0),
                'imported_rows': result.get('imported', 0),
                'errors': len(result.get('errors', [])),
                'status': 'success' if result.get('success') else 'failed',
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df.to_parquet(self.import_history_file, index=False)
        except Exception as e:
            print(f"Error saving import history: {e}")

    @staticmethod
    def _find_col(columns, aliases: List[str]) -> Optional[str]:
        for alias in aliases:
            if alias in columns:
                return alias
        return None

    @staticmethod
    def _safe_str(row, col) -> str:
        if not col or col not in row.index:
            return ''
        val = row[col]
        if pd.isna(val):
            return ''
        return str(val).strip()

    @staticmethod
    def _safe_float(row, col) -> float:
        if not col or col not in row.index:
            return 0.0
        val = row[col]
        if pd.isna(val):
            return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

__all__ = ['InventoryDataStore']
