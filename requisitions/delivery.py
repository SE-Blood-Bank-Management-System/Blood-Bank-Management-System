"""Hospital tracking projections; custody changes use the requisition service."""
from .models import RequisitionFulfilment


def deliveries(requisition):
    return RequisitionFulfilment.objects.filter(requisition=requisition).select_related(
        'blood_unit', 'recorded_by', 'delivery_confirmation__received_by',
    )


def tracking_data(requisition):
    return {
        'allocations': [{
            'bagId': allocation.blood_unit.bag_id, 'status': allocation.status,
            'unitStatus': allocation.blood_unit.status,
            'allocatedAt': allocation.allocated_at.isoformat(),
        } for allocation in requisition.allocations.select_related('blood_unit')],
        'dispatches': [{
            'manifestId': manifest.manifest_id, 'dispatchedBy': manifest.dispatched_by.username,
            'dispatchedAt': manifest.dispatched_at.isoformat(), 'notes': manifest.notes,
            'bagIds': [unit.bag_id for unit in manifest.units.all()],
        } for manifest in requisition.dispatch_manifests.select_related('dispatched_by').prefetch_related('units')],
        'deliveries': [delivery_data(item) for item in deliveries(requisition)],
    }


def delivery_data(item):
    receipt = getattr(item, 'delivery_confirmation', None)
    return {
        'id': item.pk, 'bagId': item.blood_unit.bag_id, 'status': item.blood_unit.status,
        'dispatchedBy': item.recorded_by.username, 'dispatchedAt': item.recorded_at.isoformat(),
        'receivedBy': receipt.receiver_label if receipt else None,
        'receivedAt': receipt.received_at.isoformat() if receipt else None,
    }
