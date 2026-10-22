"""Self-service donor API contract from SAD 4.3 (BBMS-F-006 to F-008)."""
import json

from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from accounts.forms import UserProfileUpdateForm
from accounts.models import User
from accounts.rbac import role_required
from .services import donation_summary


def profile_data(user):
    return {
        'id': user.pk, 'full_name': user.get_full_name(), 'email': user.email,
        'date_of_birth': user.date_of_birth.isoformat() if user.date_of_birth else None,
        'gender': user.gender, 'phone': user.phone, 'address': user.address,
        'blood_group': user.blood_group,
    }


@role_required(User.Role.DONOR)
@never_cache
@require_http_methods(['GET', 'PUT'])
def profile(request):
    if request.method == 'PUT':
        if request.content_type != 'application/json':
            return JsonResponse({'error': 'Use application/json for profile updates.'}, status=415)
        try:
            updates = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'Invalid JSON body.'}, status=400)
        allowed = ('phone', 'address', 'blood_group')
        if not isinstance(updates, dict) or any(key not in allowed for key in updates):
            return JsonResponse({'error': 'Only phone, address and blood_group can be updated.'}, status=400)
        if any(not isinstance(value, str) for value in updates.values()):
            return JsonResponse({'error': 'Profile field values must be strings.'}, status=400)
        data = {key: getattr(request.user, key) for key in allowed}
        data.update(updates)
        form = UserProfileUpdateForm(data, instance=request.user)
        if not form.is_valid():
            return JsonResponse({'errors': form.errors}, status=400)
        form.save()
    return JsonResponse({'profile': profile_data(request.user)})


@role_required(User.Role.DONOR)
@never_cache
@require_safe
def donations(request):
    summary = donation_summary(request.user)
    page = Paginator(summary['donations'], 25).get_page(request.GET.get('page'))
    records = [{
        'bag_id': unit.bag_id, 'collection_date': unit.collection_date.isoformat(),
        'location': unit.location, 'volume_ml': unit.volume_ml,
    } for unit in page]
    return JsonResponse({
        'donations': records, 'count': page.paginator.count,
        'page': page.number, 'pages': page.paginator.num_pages,
    })


@role_required(User.Role.DONOR)
@never_cache
@require_safe
def eligibility(request):
    summary = donation_summary(request.user)
    latest = request.user.get_latest_eligibility()
    date = summary['next_eligible_date']
    return JsonResponse({
        'next_eligible_date': date.isoformat() if date else None,
        'minimum_interval_days': summary['minimum_interval_days'],
        'can_donate_by_interval': summary['can_donate_by_interval'],
        'medical_screening_status': latest.status if latest else 'Pending Screening',
        'is_eligible': summary['can_donate_by_interval'] and bool(latest and latest.is_eligible),
    })
