"""
Reporting and CSV Analytics Service for Blood Bank Management System (BBMS).

SRS References:
- Section 4.22 (BBMS-F-064): Inventory stock report and CSV export following safe availability rules.
- Section 4.22 (BBMS-F-065): Donation activity report by date range (total donations, collected units,
  discarded units; separated components are not new donations).
- Section 4.22 (BBMS-F-066): Requisition received, fulfilled, partially fulfilled, and rejected totals
  from persisted request and dispatch records.
- Section 5.1.2 (BBMS-SR-003): Server-side role-based access control (Admin only).
- Section 5.1.5 (BBMS-SR-005): Safe CSV formula handling (Spreadsheet Formula Injection mitigation)
  and privacy protection (exclusion of unnecessary personal data).

STP Test Case References:
- TC-RPT-01: System reports & CSV exports verification.
- TC-SEC-03: Role-based authorization enforcement.
"""

import csv
import io
from datetime import datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from core.constants import VALID_BLOOD_GROUPS
from inventory.models import BloodUnit, BloodUnitStatus, DispatchManifest
from inventory.services import get_inventory_counts
from requisitions.models import Requisition, RequisitionFulfilment


def sanitize_csv_cell(value):
    """
    Sanitizes values against CSV Formula Injection (Spreadsheet Injection).
    Prepends a single quote "'" if the string starts with '=', '+', '-', '@', '\t', or '\r'.
    Handles numbers, booleans, and None safely.
    """
    if value is None:
        return ""
    val_str = str(value)
    if val_str and val_str[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{val_str}"
    return val_str


def parse_and_validate_date_range(start_date_str=None, end_date_str=None, default_days=30):
    """
    Parses and validates date range parameters.

    Returns:
        (start_date: date, end_date: date, error_message: str or None)

    Rules:
    - If neither is provided, defaults to the last `default_days` days up to today.
    - If only start_date is provided, end_date defaults to today.
    - If only end_date is provided, start_date defaults to `end_date - default_days`.
    - Returns an error message if the format is invalid (expected YYYY-MM-DD).
    - Returns an error message if start_date > end_date.
    """
    today = timezone.localdate()

    if not start_date_str and not end_date_str:
        start_date = today - timedelta(days=default_days)
        end_date = today
        return start_date, end_date, None

    start_date = None
    end_date = None

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str.strip(), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None, None, f"Invalid start date format '{start_date_str}'. Expected YYYY-MM-DD."

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str.strip(), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None, None, f"Invalid end date format '{end_date_str}'. Expected YYYY-MM-DD."

    if start_date and not end_date:
        end_date = today
    elif end_date and not start_date:
        start_date = end_date - timedelta(days=default_days)

    if start_date > end_date:
        return None, None, f"Start date ({start_date}) cannot be after end date ({end_date})."

    return start_date, end_date, None


# ==============================================================================
# 1. INVENTORY STOCK REPORT (BBMS-F-064)
# ==============================================================================

def get_inventory_report_data(location=None):
    """
    Reuses existing inventory aggregation in inventory.services.get_inventory_counts().
    Follows the same safe availability rules: only BloodUnit.objects.available() are counted.
    Quarantined, Discarded, Expired, Allocated, and Dispatched units are strictly excluded.
    """
    counts = get_inventory_counts(location=location)
    return counts


def generate_inventory_csv(location=None):
    """
    Generates a safe CSV report of inventory stock levels.
    Includes:
    1. Stock by Blood Group & Component Matrix
    2. Stock by Storage Location Matrix
    3. Inventory Safety Metrics (Available vs Quarantined vs Discarded vs Expiring Soon)
    """
    data = get_inventory_report_data(location=location)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header / Meta
    generated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    writer.writerow([sanitize_csv_cell('BBMS INVENTORY STOCK REPORT (BBMS-F-064)')])
    writer.writerow([sanitize_csv_cell('Generated At'), sanitize_csv_cell(generated_at)])
    writer.writerow([sanitize_csv_cell('Location Filter'), sanitize_csv_cell(location or 'ALL Locations')])
    writer.writerow([])

    # Safety Metrics Summary
    writer.writerow([sanitize_csv_cell('--- INVENTORY STATUS SUMMARY ---')])
    writer.writerow([
        sanitize_csv_cell('Metric'),
        sanitize_csv_cell('Count'),
        sanitize_csv_cell('Safe Availability Status'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Available Units'),
        sanitize_csv_cell(data['total_available']),
        sanitize_csv_cell('Included in active stock'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Quarantined Units'),
        sanitize_csv_cell(data['total_quarantined']),
        sanitize_csv_cell('Strictly Excluded (Under Testing/Quarantine)'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Discarded Units'),
        sanitize_csv_cell(data['total_discarded']),
        sanitize_csv_cell('Strictly Excluded (Failed Serology/Biohazard)'),
    ])
    writer.writerow([
        sanitize_csv_cell('Expiring Soon (<= 7 Days)'),
        sanitize_csv_cell(data['expiring_soon_count']),
        sanitize_csv_cell('FEFO Priority Warning'),
    ])
    writer.writerow([])

    # Table 1: Blood Group & Component Stock
    writer.writerow([sanitize_csv_cell('--- AVAILABLE STOCK BY BLOOD GROUP & COMPONENT ---')])
    writer.writerow([
        sanitize_csv_cell('Blood Group'),
        sanitize_csv_cell('Whole Blood'),
        sanitize_csv_cell('Red Blood Cells'),
        sanitize_csv_cell('Platelets'),
        sanitize_csv_cell('Fresh Frozen Plasma'),
        sanitize_csv_cell('Total Units'),
    ])

    for row in data['stock_matrix']:
        writer.writerow([
            sanitize_csv_cell(row['blood_group']),
            sanitize_csv_cell(row['whole_blood']),
            sanitize_csv_cell(row['rbc']),
            sanitize_csv_cell(row['platelets']),
            sanitize_csv_cell(row['plasma']),
            sanitize_csv_cell(row['total']),
        ])

    grand = data['grand_component_totals']
    writer.writerow([
        sanitize_csv_cell('GRAND TOTAL'),
        sanitize_csv_cell(grand['whole_blood']),
        sanitize_csv_cell(grand['rbc']),
        sanitize_csv_cell(grand['platelets']),
        sanitize_csv_cell(grand['plasma']),
        sanitize_csv_cell(grand['total']),
    ])
    writer.writerow([])

    # Table 2: Stock by Location
    writer.writerow([sanitize_csv_cell('--- AVAILABLE STOCK BY LOCATION ---')])
    loc_header = (
        [sanitize_csv_cell('Storage Location')] +
        [sanitize_csv_cell(bg) for bg in VALID_BLOOD_GROUPS] +
        [sanitize_csv_cell('Total')]
    )
    writer.writerow(loc_header)

    for loc in data['location_matrix']:
        row_vals = [sanitize_csv_cell(loc['location'])]
        for bg in VALID_BLOOD_GROUPS:
            row_vals.append(sanitize_csv_cell(loc['counts'].get(bg, 0)))
        row_vals.append(sanitize_csv_cell(loc['total']))
        writer.writerow(row_vals)

    loc_totals = data['loc_grand_totals']
    summary_row = (
        [sanitize_csv_cell('TOTAL')] +
        [sanitize_csv_cell(loc_totals.get(bg, 0)) for bg in VALID_BLOOD_GROUPS] +
        [sanitize_csv_cell(loc_totals.get('all', 0))]
    )
    writer.writerow(summary_row)

    return output.getvalue()


# ==============================================================================
# 2. DONATION ACTIVITY REPORT (BBMS-F-065)
# ==============================================================================

def get_donation_activity_report_data(start_date, end_date):
    """
    Calculates donation activity summary for the validated date range [start_date, end_date].
    SRS BBMS-F-065.

    Rules:
    - Separated components are not new donations (parent_unit__isnull=True).
    - Total donations: count of primary donation sessions / collected units.
    - Collected units: count of primary collected units.
    - Discarded units: count of units discarded in this period.
    """
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max))

    # Primary collections (original donations).
    # Separated components have parent_unit != None, so they are excluded from donations count.
    primary_collections = BloodUnit.objects.filter(
        parent_unit__isnull=True,
        collection_date__range=(start_dt, end_dt)
    )

    total_donations = primary_collections.count()
    collected_units = total_donations

    # Distinct donors who donated in this period
    unique_donors_count = primary_collections.exclude(donor__isnull=True).values('donor').distinct().count()

    # Breakdown by ABO/Rh blood group
    bg_counts = primary_collections.values('blood_group').annotate(total=Count('id'))
    bg_lookup = {r['blood_group']: r['total'] for r in bg_counts}
    donations_by_group = [{'blood_group': bg, 'count': bg_lookup.get(bg, 0)} for bg in VALID_BLOOD_GROUPS]

    # Breakdown by initial component type (Whole Blood vs Apheresis)
    comp_counts = primary_collections.values('component_type').annotate(total=Count('id'))
    comp_lookup = {r['component_type']: r['total'] for r in comp_counts}

    # Child components derived during this period (explicitly documented as NOT new donations)
    derived_components_count = BloodUnit.objects.filter(
        parent_unit__isnull=False,
        collection_date__range=(start_dt, end_dt)
    ).count()

    # Discarded units:
    # Captures units whose collection occurred in this range that are discarded,
    # or units with a recorded StatusChange transition to 'Discarded' within this date range.
    discarded_qs = BloodUnit.objects.filter(
        Q(status=BloodUnitStatus.DISCARDED, collection_date__range=(start_dt, end_dt)) |
        Q(status_changes__new_status=BloodUnitStatus.DISCARDED, status_changes__changed_at__range=(start_dt, end_dt))
    ).distinct()

    discarded_units = discarded_qs.count()

    discarded_by_group_counts = discarded_qs.values('blood_group').annotate(total=Count('id'))
    discarded_by_group_lookup = {r['blood_group']: r['total'] for r in discarded_by_group_counts}
    discarded_by_group = [
        {'blood_group': bg, 'count': discarded_by_group_lookup.get(bg, 0)}
        for bg in VALID_BLOOD_GROUPS
    ]

    # Discarded units detail list (privacy safe: only operational Bag ID, blood group, component, reason; NO PII)
    discarded_details = []
    for u in discarded_qs.order_by('-collection_date', '-pk')[:100]:
        reason = u.status_audit_log.strip().split('\n')[-1] if u.status_audit_log else 'Serology failure or expiry'
        discarded_details.append({
            'bag_id': u.bag_id,
            'blood_group': u.blood_group,
            'component_type': u.component_type,
            'collection_date': u.collection_date.strftime('%Y-%m-%d') if u.collection_date else '',
            'reason': reason,
        })

    # Summary collection rows (privacy safe: no donor names or phone numbers)
    collection_rows = []
    for u in primary_collections.order_by('-collection_date', '-pk')[:100]:
        collection_rows.append({
            'bag_id': u.bag_id,
            'blood_group': u.blood_group,
            'component_type': u.component_type,
            'volume_ml': u.volume_ml,
            'location': u.location or 'Main Blood Bank',
            'collection_date': u.collection_date.strftime('%Y-%m-%d %H:%M') if u.collection_date else '',
            'status': u.status,
        })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_donations': total_donations,
        'collected_units': collected_units,
        'unique_donors_count': unique_donors_count,
        'derived_components_count': derived_components_count,
        'discarded_units': discarded_units,
        'donations_by_group': donations_by_group,
        'initial_components': comp_lookup,
        'discarded_by_group': discarded_by_group,
        'discarded_details': discarded_details,
        'collection_rows': collection_rows,
    }


def generate_donations_csv(start_date, end_date):
    """
    Generates a safe CSV report of donation and collection activity.
    SRS BBMS-F-065, BBMS-SR-005.
    Excludes unnecessary personal data (donor names, emails, phones, medical records).
    Applies formula-safe sanitization to all cell text.
    """
    data = get_donation_activity_report_data(start_date, end_date)

    output = io.StringIO()
    writer = csv.writer(output)

    generated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    writer.writerow([sanitize_csv_cell('BBMS DONATION ACTIVITY REPORT (BBMS-F-065)')])
    writer.writerow([sanitize_csv_cell('Generated At'), sanitize_csv_cell(generated_at)])
    writer.writerow([sanitize_csv_cell('Date Range'), sanitize_csv_cell(f"{start_date} to {end_date}")])
    writer.writerow([])

    # Executive Summary
    writer.writerow([sanitize_csv_cell('--- DONATION SUMMARY METRICS ---')])
    writer.writerow([
        sanitize_csv_cell('Metric'),
        sanitize_csv_cell('Count'),
        sanitize_csv_cell('Rule & Definition'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Donations'),
        sanitize_csv_cell(data['total_donations']),
        sanitize_csv_cell('Original donor donation events (parent_unit is None)'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Collected Units'),
        sanitize_csv_cell(data['collected_units']),
        sanitize_csv_cell('Primary blood units collected'),
    ])
    writer.writerow([
        sanitize_csv_cell('Derived Components'),
        sanitize_csv_cell(data['derived_components_count']),
        sanitize_csv_cell('Separated child components; NOT counted as new donations'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Discarded Units'),
        sanitize_csv_cell(data['discarded_units']),
        sanitize_csv_cell('Units discarded due to serology failure or expiry'),
    ])
    writer.writerow([
        sanitize_csv_cell('Unique Participating Donors'),
        sanitize_csv_cell(data['unique_donors_count']),
        sanitize_csv_cell('Distinct registered donors'),
    ])
    writer.writerow([])

    # Blood Group Breakdown
    writer.writerow([sanitize_csv_cell('--- DONATIONS & DISCARDS BY BLOOD GROUP ---')])
    writer.writerow([
        sanitize_csv_cell('Blood Group'),
        sanitize_csv_cell('Donations Collected'),
        sanitize_csv_cell('Units Discarded'),
    ])

    discard_map = {row['blood_group']: row['count'] for row in data['discarded_by_group']}
    for row in data['donations_by_group']:
        bg = row['blood_group']
        writer.writerow([
            sanitize_csv_cell(bg),
            sanitize_csv_cell(row['count']),
            sanitize_csv_cell(discard_map.get(bg, 0)),
        ])
    writer.writerow([])

    # Primary Collections List (Privacy Safe: Bag ID, Blood Group, Component, Volume, Location, Date, Status)
    writer.writerow([sanitize_csv_cell('--- RECENT PRIMARY COLLECTIONS IN RANGE (PII EXCLUDED) ---')])
    writer.writerow([
        sanitize_csv_cell('Bag ID'),
        sanitize_csv_cell('Blood Group'),
        sanitize_csv_cell('Component Type'),
        sanitize_csv_cell('Volume (ml)'),
        sanitize_csv_cell('Location'),
        sanitize_csv_cell('Collection Date'),
        sanitize_csv_cell('Current Status'),
    ])

    if data['collection_rows']:
        for row in data['collection_rows']:
            writer.writerow([
                sanitize_csv_cell(row['bag_id']),
                sanitize_csv_cell(row['blood_group']),
                sanitize_csv_cell(row['component_type']),
                sanitize_csv_cell(row['volume_ml']),
                sanitize_csv_cell(row['location']),
                sanitize_csv_cell(row['collection_date']),
                sanitize_csv_cell(row['status']),
            ])
    else:
        writer.writerow([sanitize_csv_cell('No collections recorded in this date range.'), '', '', '', '', '', ''])

    writer.writerow([])

    # Discarded Units Summary
    writer.writerow([sanitize_csv_cell('--- DISCARDED UNITS IN RANGE ---')])
    writer.writerow([
        sanitize_csv_cell('Bag ID'),
        sanitize_csv_cell('Blood Group'),
        sanitize_csv_cell('Component Type'),
        sanitize_csv_cell('Collection Date'),
        sanitize_csv_cell('Reason / Audit Log'),
    ])

    if data['discarded_details']:
        for row in data['discarded_details']:
            writer.writerow([
                sanitize_csv_cell(row['bag_id']),
                sanitize_csv_cell(row['blood_group']),
                sanitize_csv_cell(row['component_type']),
                sanitize_csv_cell(row['collection_date']),
                sanitize_csv_cell(row['reason']),
            ])
    else:
        writer.writerow([sanitize_csv_cell('No discarded units recorded in this date range.'), '', '', '', ''])

    return output.getvalue()


# ==============================================================================
# 3. REQUISITION & FULFILMENT REPORT (BBMS-F-066)
# ==============================================================================

def get_requisition_report_data(start_date, end_date):
    """
    Calculates date-range requisition received/fulfilled/partially fulfilled/rejected totals
    from persisted request and dispatch records.
    SRS BBMS-F-066.
    """
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max))

    # All requisitions created within this date range
    reqs_qs = Requisition.objects.filter(
        created_at__range=(start_dt, end_dt)
    ).select_related('hospital')

    total_received = reqs_qs.count()
    total_fulfilled = reqs_qs.filter(status=Requisition.Status.FULFILLED).count()
    total_partially_fulfilled = reqs_qs.filter(status=Requisition.Status.PARTIALLY_FULFILLED).count()
    total_rejected = reqs_qs.filter(status=Requisition.Status.REJECTED).count()
    total_pending = reqs_qs.filter(status=Requisition.Status.PENDING).count()
    total_approved = reqs_qs.filter(status=Requisition.Status.APPROVED).count()

    total_units_requested = sum(r.quantity for r in reqs_qs) or 0

    # Persisted dispatch and fulfilment records recorded in this range
    fulfilments_in_range = RequisitionFulfilment.objects.filter(
        recorded_at__range=(start_dt, end_dt)
    ).select_related('requisition', 'blood_unit')

    total_units_dispatched = fulfilments_in_range.count()

    # Dispatch manifests generated in this range
    manifests_in_range = DispatchManifest.objects.filter(
        dispatched_at__range=(start_dt, end_dt)
    )
    manifests_count = manifests_in_range.count()

    # Calculation of fulfilment percentage
    fulfilment_rate = 0.0
    if total_received > 0:
        fulfilment_rate = round(((total_fulfilled + total_partially_fulfilled) / total_received) * 100, 1)

    # Breakdown by Blood Group
    req_by_group = {bg: 0 for bg in VALID_BLOOD_GROUPS}
    for row in reqs_qs.values('blood_group').annotate(total=Count('id')):
        req_by_group[row['blood_group']] = row['total']

    # Detail table rows (safe: hospital organization name and requisition reference; NO donor PII)
    requisition_rows = []
    for r in reqs_qs.order_by('-created_at', '-pk')[:100]:
        hosp_name = getattr(r.hospital, 'hospital_name', None) or r.hospital.get_full_name() or r.hospital.get_username()
        requisition_rows.append({
            'requisition_id': r.requisition_id,
            'hospital': hosp_name,
            'blood_group': r.blood_group,
            'component_type': r.component_type,
            'quantity': r.quantity,
            'dispatched_quantity': r.dispatched_quantity,
            'status': r.status,
            'is_stat': r.is_stat,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            'required_by': r.required_by.strftime('%Y-%m-%d') if r.required_by else '',
            'rejection_reason': r.rejection_reason or '',
        })

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_received': total_received,
        'total_fulfilled': total_fulfilled,
        'total_partially_fulfilled': total_partially_fulfilled,
        'total_rejected': total_rejected,
        'total_pending': total_pending,
        'total_approved': total_approved,
        'total_units_requested': total_units_requested,
        'total_units_dispatched': total_units_dispatched,
        'manifests_count': manifests_count,
        'fulfilment_rate': fulfilment_rate,
        'req_by_group': req_by_group,
        'requisition_rows': requisition_rows,
    }


def generate_requisitions_csv(start_date, end_date):
    """
    Generates a safe CSV report of requisition activity and fulfilment accounting.
    SRS BBMS-F-066, BBMS-SR-005.
    """
    data = get_requisition_report_data(start_date, end_date)

    output = io.StringIO()
    writer = csv.writer(output)

    generated_at = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    writer.writerow([sanitize_csv_cell('BBMS REQUISITION & FULFILMENT REPORT (BBMS-F-066)')])
    writer.writerow([sanitize_csv_cell('Generated At'), sanitize_csv_cell(generated_at)])
    writer.writerow([sanitize_csv_cell('Date Range'), sanitize_csv_cell(f"{start_date} to {end_date}")])
    writer.writerow([])

    # Executive Totals
    writer.writerow([sanitize_csv_cell('--- REQUISITION TOTALS & STATUS BREAKDOWN ---')])
    writer.writerow([
        sanitize_csv_cell('Status / Metric'),
        sanitize_csv_cell('Total Requisitions'),
        sanitize_csv_cell('Description'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Received'),
        sanitize_csv_cell(data['total_received']),
        sanitize_csv_cell('Total hospital requisitions submitted in date range'),
    ])
    writer.writerow([
        sanitize_csv_cell('Fulfilled'),
        sanitize_csv_cell(data['total_fulfilled']),
        sanitize_csv_cell('100% of requested units allocated and dispatched'),
    ])
    writer.writerow([
        sanitize_csv_cell('Partially Fulfilled'),
        sanitize_csv_cell(data['total_partially_fulfilled']),
        sanitize_csv_cell('Partial quantity dispatched; awaiting remaining units'),
    ])
    writer.writerow([
        sanitize_csv_cell('Rejected'),
        sanitize_csv_cell(data['total_rejected']),
        sanitize_csv_cell('Requisitions rejected by blood bank staff with recorded reason'),
    ])
    writer.writerow([
        sanitize_csv_cell('Pending Review'),
        sanitize_csv_cell(data['total_pending']),
        sanitize_csv_cell('Awaiting clinical review and approval'),
    ])
    writer.writerow([
        sanitize_csv_cell('Approved (Pending Dispatch)'),
        sanitize_csv_cell(data['total_approved']),
        sanitize_csv_cell('Approved for allocation; pending manifest generation'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Units Requested'),
        sanitize_csv_cell(data['total_units_requested']),
        sanitize_csv_cell('Sum of blood units ordered'),
    ])
    writer.writerow([
        sanitize_csv_cell('Total Units Dispatched'),
        sanitize_csv_cell(data['total_units_dispatched']),
        sanitize_csv_cell('Units dispatched under verified manifests in range'),
    ])
    writer.writerow([
        sanitize_csv_cell('Dispatch Manifests Issued'),
        sanitize_csv_cell(data['manifests_count']),
        sanitize_csv_cell('Formal manifest audit records generated'),
    ])
    writer.writerow([
        sanitize_csv_cell('Fulfilment Rate (%)'),
        sanitize_csv_cell(f"{data['fulfilment_rate']}%"),
        sanitize_csv_cell('(Fulfilled + Partially Fulfilled) / Received'),
    ])
    writer.writerow([])

    # Breakdown by Blood Group
    writer.writerow([sanitize_csv_cell('--- REQUISITIONS BY REQUESTED BLOOD GROUP ---')])
    writer.writerow([sanitize_csv_cell('Blood Group'), sanitize_csv_cell('Requisitions Count')])
    for bg in VALID_BLOOD_GROUPS:
        writer.writerow([sanitize_csv_cell(bg), sanitize_csv_cell(data['req_by_group'].get(bg, 0))])
    writer.writerow([])

    # Requisition Details Table
    writer.writerow([sanitize_csv_cell('--- REQUISITION RECORDS IN RANGE ---')])
    writer.writerow([
        sanitize_csv_cell('Requisition ID'),
        sanitize_csv_cell('Hospital'),
        sanitize_csv_cell('Blood Group'),
        sanitize_csv_cell('Component Type'),
        sanitize_csv_cell('Requested Units'),
        sanitize_csv_cell('Dispatched Units'),
        sanitize_csv_cell('Status'),
        sanitize_csv_cell('Emergency STAT'),
        sanitize_csv_cell('Submitted Date'),
        sanitize_csv_cell('Required By'),
        sanitize_csv_cell('Rejection Reason'),
    ])

    if data['requisition_rows']:
        for row in data['requisition_rows']:
            writer.writerow([
                sanitize_csv_cell(row['requisition_id']),
                sanitize_csv_cell(row['hospital']),
                sanitize_csv_cell(row['blood_group']),
                sanitize_csv_cell(row['component_type']),
                sanitize_csv_cell(row['quantity']),
                sanitize_csv_cell(row['dispatched_quantity']),
                sanitize_csv_cell(row['status']),
                sanitize_csv_cell('Yes' if row['is_stat'] else 'No'),
                sanitize_csv_cell(row['created_at']),
                sanitize_csv_cell(row['required_by']),
                sanitize_csv_cell(row['rejection_reason']),
            ])
    else:
        empty_msg = 'No requisitions recorded in this date range.'
        writer.writerow([sanitize_csv_cell(empty_msg), '', '', '', '', '', '', '', '', '', ''])

    return output.getvalue()
