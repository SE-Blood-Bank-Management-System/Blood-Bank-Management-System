"""SAD request API adapters; CSRF/session authentication remain enabled."""
import json
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import User
from accounts.rbac import role_required
from .forms import RequisitionForm, ReviewForm
from .models import Requisition
from .services import RequisitionConflict, review_requisition, set_priority, submit_requisition, visible_requisitions


class PayloadError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def json_errors(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PayloadError as error:
            return JsonResponse({'error': error.message}, status=error.status)
        except PermissionDenied as error:
            return JsonResponse({'error': str(error)}, status=403)
        except (Http404, Requisition.DoesNotExist):
            return JsonResponse({'error': 'Requisition not found.'}, status=404)
        except ValidationError as error:
            errors = error.message_dict if hasattr(error, 'message_dict') else {'__all__': error.messages}
            return JsonResponse({'errors': errors}, status=409 if isinstance(error, RequisitionConflict) else 400)
    return wrapped


def payload(request, allowed):
    if request.content_type != 'application/json':
        raise PayloadError('Use application/json.', 415)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise PayloadError('Invalid JSON body.')
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise PayloadError('Use a JSON object containing only the documented fields.')
    return data


def request_data(requisition, include_history=False):
    data = {
        'id': requisition.pk, 'requestId': requisition.requisition_id,
        'hospitalId': requisition.hospital_id, 'hospitalName': requisition.hospital.hospital_name,
        'bloodGroup': requisition.blood_group, 'component': requisition.component_type,
        'quantity': requisition.quantity, 'requiredBy': requisition.required_by.isoformat(),
        'isStat': requisition.is_stat, 'status': requisition.status, 'version': requisition.version,
        'dispatchedQuantity': requisition.dispatched_quantity, 'remainingQuantity': requisition.remaining_quantity,
        'rejectionReason': requisition.rejection_reason, 'submittedAt': requisition.created_at.isoformat(),
        'reviewedAt': requisition.reviewed_at.isoformat() if requisition.reviewed_at else None,
    }
    if include_history:
        data['history'] = [{
            'action': event.action, 'actor': event.actor_label, 'timestamp': event.created_at.isoformat(),
            'previousStatus': event.previous_status, 'status': event.new_status,
            'previousIsStat': event.previous_is_stat, 'isStat': event.new_is_stat, 'note': event.note,
        } for event in requisition.events.all()]
    return data


@role_required(User.Role.HOSPITAL, User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_http_methods(['GET', 'POST'])
@json_errors
def requests(request):
    if request.method == 'POST':
        data = payload(request, ['bloodGroup', 'component', 'quantity', 'requiredBy', 'isStat'])
        if 'quantity' in data and type(data['quantity']) is not int:
            raise PayloadError('quantity must be a positive integer.')
        if type(data.get('isStat', False)) is not bool:
            raise PayloadError('isStat must be true or false.')
        form = RequisitionForm({
            'blood_group': data.get('bloodGroup'), 'component_type': data.get('component'),
            'quantity': data.get('quantity'), 'required_by': data.get('requiredBy'), 'is_stat': data.get('isStat', False),
        })
        if not form.is_valid():
            return JsonResponse({'errors': form.errors}, status=400)
        return JsonResponse(request_data(submit_requisition(actor=request.user, **form.cleaned_data)), status=201)
    queryset = visible_requisitions(request.user)
    selected = request.GET.get('status', '' if request.user.is_hospital else Requisition.Status.PENDING)
    if selected and selected not in Requisition.Status.values:
        raise PayloadError('Unknown requisition status.')
    if selected:
        queryset = queryset.filter(status=selected)
    page = Paginator(queryset, 25).get_page(request.GET.get('page'))
    return JsonResponse({'requests': [request_data(item) for item in page],
                         'count': page.paginator.count, 'page': page.number, 'pages': page.paginator.num_pages})


@role_required(User.Role.HOSPITAL, User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_GET
@json_errors
def detail(request, pk):
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    return JsonResponse(request_data(requisition, include_history=True))


@role_required(User.Role.HOSPITAL)
@never_cache
@require_http_methods(['PATCH'])
@json_errors
def priority(request, pk):
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    data = payload(request, ['isStat', 'version'])
    if type(data.get('isStat')) is not bool or type(data.get('version')) is not int or data['version'] < 0:
        raise PayloadError('Provide a boolean isStat and a non-negative integer version.')
    result = set_priority(requisition.pk, actor=request.user, is_stat=data['isStat'], expected_version=data['version'])
    return JsonResponse(request_data(result))


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_http_methods(['POST'])
@json_errors
def review(request, pk):
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    data = payload(request, ['action', 'reason', 'version'])
    if type(data.get('version')) is not int or data['version'] < 0:
        raise PayloadError('Provide a non-negative integer version.')
    if not isinstance(data.get('reason', ''), str):
        raise PayloadError('reason must be text.')
    form = ReviewForm(data)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)
    result = review_requisition(requisition.pk, actor=request.user, action=form.cleaned_data['action'],
                                reason=form.cleaned_data['reason'], expected_version=form.cleaned_data['version'])
    return JsonResponse(request_data(result))
