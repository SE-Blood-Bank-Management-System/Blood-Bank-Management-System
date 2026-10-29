from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from accounts.models import User
from accounts.rbac import role_required
from .api import json_errors
from .compatibility import get_compatible_donor_groups
from .delivery import deliveries
from .forms import CrossMatchForm, PriorityForm, ReceiptForm, RequisitionForm, ReviewForm
from .models import Requisition
from .services import (
    RequisitionConflict,
    confirm_receipt,
    get_compatible_inventory_for_requisition,
    pending_stat_summary,
    record_cross_match,
    require_hospital,
    require_staff,
    review_requisition,
    set_priority,
    submit_requisition,
    visible_requisitions,
)


ACCESS = (User.Role.HOSPITAL, User.Role.STAFF, User.Role.ADMIN)


def _form_error(form, error):
    if hasattr(error, 'message_dict'):
        for key, errors in error.message_dict.items():
            form.add_error(key if key in form.fields else None, errors)
    else:
        form.add_error(None, error)


@role_required(*ACCESS)
@never_cache
@require_GET
def request_list(request):
    queryset = visible_requisitions(request.user)
    is_hospital = request.user.role == User.Role.HOSPITAL
    selected = request.GET.get('status', '' if is_hospital else Requisition.Status.PENDING)
    if selected and selected not in Requisition.Status.values:
        return HttpResponseBadRequest('Unknown requisition status.')
    if selected:
        queryset = queryset.filter(status=selected)
    return render(request, 'requisitions/list.html', {
        'page': Paginator(queryset, 25).get_page(request.GET.get('page')),
        'statuses': Requisition.Status.choices, 'selected_status': selected, 'is_hospital': is_hospital,
    })


@role_required(User.Role.HOSPITAL)
@never_cache
@require_http_methods(['GET', 'POST'])
def create(request):
    require_hospital(request.user)
    form = RequisitionForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            requisition = submit_requisition(actor=request.user, **form.cleaned_data)
        except ValidationError as error:
            _form_error(form, error)
        else:
            messages.success(request, 'Requisition submitted for staff review.')
            return redirect('requisitions:detail', pk=requisition.pk)
    return render(request, 'requisitions/form.html', {'form': form})


def _detail_context(request, requisition, **overrides):
    dispatched = list(deliveries(requisition))
    context = {
        'deliveries': dispatched,
        'receipt_form': ReceiptForm(deliveries=dispatched, initial={'version': requisition.version}),
        'requisition': requisition,
        'events': requisition.events.all(),
        'review_form': ReviewForm(initial={'version': requisition.version}),
        'priority_form': PriorityForm(initial={'version': requisition.version, 'is_stat': requisition.is_stat}),
        'is_hospital': request.user.role == User.Role.HOSPITAL,
    }

    # Clinical cross-matching context for staff/admin (SRS BBMS-F-049 to BBMS-F-051)
    if request.user.role in (User.Role.STAFF, User.Role.ADMIN):
        context['compatible_groups'] = get_compatible_donor_groups(
            requisition.blood_group, requisition.component_type
        )
        context['compatible_inventory'] = get_compatible_inventory_for_requisition(requisition)[:10]
        context['cross_matches'] = requisition.cross_matches.select_related('blood_unit', 'performed_by').all()[:15]
        context['cross_match_form'] = CrossMatchForm(initial={'version': requisition.version})

    context.update(overrides)
    return context


@role_required(*ACCESS)
@never_cache
@require_GET
def detail(request, pk):
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    return render(request, 'requisitions/detail.html', _detail_context(request, requisition))


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_POST
def review(request, pk):
    require_staff(request.user)
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    form = ReviewForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            review_requisition(pk, actor=request.user, action=form.cleaned_data['action'],
                               reason=form.cleaned_data['reason'], expected_version=form.cleaned_data['version'])
        except ValidationError as error:
            status = 409 if isinstance(error, RequisitionConflict) else 400
            _form_error(form, error)
        else:
            messages.success(request, 'Staff review recorded.')
            return redirect('requisitions:detail', pk=pk)
    return render(request, 'requisitions/detail.html', _detail_context(request, requisition, review_form=form), status=status)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_POST
def cross_match(request, pk):
    """
    Staff action to record cross-matching and clinical override decisions.
    SRS References:
    - BBMS-F-049: Compatibility calculation.
    - BBMS-F-050: Incompatible units blocked unless authorized override is supplied.
    - BBMS-F-051: Cross-match outcome recorded against allocation.
    """
    require_staff(request.user)
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    form = CrossMatchForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            decision = record_cross_match(
                requisition.pk,
                form.cleaned_data['bag_id'],
                actor=request.user,
                override_reason=form.cleaned_data.get('override_reason', ''),
                expected_version=form.cleaned_data.get('version')
            )
        except ValidationError as error:
            _form_error(form, error)
        else:
            if decision.is_overridden:
                messages.warning(
                    request,
                    f"Cross-match recorded with OVERRIDE: Unit {decision.blood_unit.bag_id} "
                    f"({decision.donor_blood_group}) is biologically incompatible with request "
                    f"({decision.requested_blood_group}), but clinical override was authorized (SRS BBMS-F-050)."
                )
            else:
                messages.success(
                    request,
                    f"Cross-match successful: Unit {decision.blood_unit.bag_id} ({decision.donor_blood_group}) "
                    f"is COMPATIBLE with request ({decision.requested_blood_group}) (SRS BBMS-F-049)."
                )
            return redirect('requisitions:detail', pk=pk)

    return render(
        request, 'requisitions/detail.html',
        _detail_context(request, requisition, cross_match_form=form),
        status=status
    )


@role_required(User.Role.HOSPITAL)
@never_cache
@require_POST
def priority(request, pk):
    require_hospital(request.user)
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    form = PriorityForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            set_priority(pk, actor=request.user, is_stat=form.cleaned_data['is_stat'],
                         expected_version=form.cleaned_data['version'])
        except ValidationError as error:
            status = 409 if isinstance(error, RequisitionConflict) else 400
            _form_error(form, error)
        else:
            messages.success(request, 'Request priority updated.')
            return redirect('requisitions:detail', pk=pk)
    return render(
        request, 'requisitions/detail.html', _detail_context(request, requisition, priority_form=form), status=status,
    )


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_GET
@json_errors
def stat_alerts(request):
    return JsonResponse({**pending_stat_summary(request.user), 'queue_url': reverse('requisitions:list')})


@role_required(User.Role.HOSPITAL)
@never_cache
@require_POST
def receipt(request, pk):
    requisition = get_object_or_404(visible_requisitions(request.user), pk=pk)
    form = ReceiptForm(request.POST, deliveries=list(deliveries(requisition)))
    status = 400
    if form.is_valid():
        try:
            confirm_receipt(pk, actor=request.user, bag_ids=form.cleaned_data['bag_ids'],
                            expected_version=form.cleaned_data['version'])
        except ValidationError as error:
            status = 409 if isinstance(error, RequisitionConflict) else 400
            _form_error(form, error)
        else:
            messages.success(request, 'Receipt confirmed. Selected bags are now Delivered.')
            return redirect('requisitions:detail', pk=pk)
    return render(request, 'requisitions/detail.html', _detail_context(request, requisition, receipt_form=form), status=status)
