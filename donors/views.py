import json
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from accounts.models import User
from accounts.rbac import role_required, _is_api_request
from .forms import MedicalEligibilityForm
from .models import MedicalEligibilityResponse, QUESTIONNAIRE_QUESTIONS
from .services import donation_summary


@role_required(User.Role.DONOR, User.Role.ADMIN)
@never_cache
@require_safe
def dashboard(request):
    """
    Donor Dashboard (SRS 4.2: BBMS-F-006 to BBMS-F-008).
    Accessible by Donors and Administrators.
    """
    latest_eligibility = request.user.get_latest_eligibility()
    if latest_eligibility:
        eligibility_status = latest_eligibility.status
    else:
        eligibility_status = 'Pending Screening'

    upcoming_appointments = []
    if hasattr(request.user, 'appointments'):
        upcoming_appointments = list(
            request.user.appointments.filter(
                status__in=['SCHEDULED', 'CONFIRMED']
            ).select_related('location', 'slot').order_by('date', 'slot__start_time')[:3]
        )

    summary = donation_summary(request.user)
    context = {
        **summary,
        'title': 'Donor Dashboard',
        'donor': request.user,
        'recent_donations': summary['donations'][:5],
        'upcoming_appointments': upcoming_appointments,
        'eligibility_status': eligibility_status,
        'latest_eligibility': latest_eligibility,
        'is_eligible': getattr(request.user, 'is_eligible', False),
    }
    return render(request, 'donors/dashboard.html', context)


def _donor_for_request(request, donor_id=None):
    if donor_id is None:
        if request.user.role == User.Role.STAFF:
            raise PermissionDenied('Select a donor to review their history.')
        return request.user
    if request.user.is_donor and donor_id != request.user.pk:
        raise PermissionDenied('You can only view your own donor information.')
    return get_object_or_404(User, pk=donor_id, role=User.Role.DONOR)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_safe
def donor_profile(request, donor_id):
    donor = _donor_for_request(request, donor_id)
    summary = donation_summary(donor)
    return render(request, 'donors/profile.html', {
        **summary, 'donor': donor, 'recent_donations': summary['donations'][:5],
    })


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_safe
def donation_history(request, donor_id=None):
    """
    View donation history including Bag IDs, dates, and locations (SRS 4.2: BBMS-F-007).
    """
    donor = _donor_for_request(request, donor_id)
    summary = donation_summary(donor)
    page = Paginator(summary['donations'], 25).get_page(request.GET.get('page'))
    context = {
        **summary,
        'donor': donor,
        'title': 'Donation History',
        'donations': page,
        'page_obj': page,
    }
    return render(request, 'donors/history.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def eligibility_check(request):
    """
    Standardized Medical Eligibility Questionnaire (SRS 4.3: BBMS-F-009 to BBMS-F-011).
    Evaluates health screening answers, persists outcome/responses for audit,
    and displays clear outcome and respectful disqualifying reasons.
    """
    latest_response = request.user.get_latest_eligibility()

    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                post_data = json.loads(request.body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                post_data = {}
        else:
            post_data = request.POST

        form = MedicalEligibilityForm(post_data)
        if form.is_valid():
            is_eligible, reasons, answers = form.evaluate()
            status = (
                MedicalEligibilityResponse.Status.ELIGIBLE
                if is_eligible
                else MedicalEligibilityResponse.Status.INELIGIBLE
            )
            reason_text = (
                "Based on your responses, you are temporarily ineligible for the following reason(s):\n- "
                + "\n- ".join(reasons)
                if reasons
                else ""
            )

            record = MedicalEligibilityResponse.objects.create(
                donor=request.user,
                status=status,
                responses=answers,
                ineligibility_reason=reason_text,
            )

            if _is_api_request(request):
                return JsonResponse({
                    'status': record.status,
                    'is_eligible': record.is_eligible,
                    'ineligibility_reason': record.ineligibility_reason,
                    'created_at': record.created_at.isoformat(),
                }, status=200)

            context = {
                'title': 'Medical Eligibility Screening Result',
                'form': form,
                'result': record,
                'status': record.status,
                'is_eligible': record.is_eligible,
                'ineligibility_reason': record.ineligibility_reason,
                'reasons': reasons,
                'submitted': True,
                'questions': QUESTIONNAIRE_QUESTIONS,
            }
            return render(request, 'donors/eligibility.html', context)
        else:
            if _is_api_request(request):
                return JsonResponse({'errors': form.errors, 'status': 'Error'}, status=400)

            context = {
                'title': 'Medical Eligibility Screening',
                'form': form,
                'latest_eligibility': latest_response,
                'questions': QUESTIONNAIRE_QUESTIONS,
            }
            return render(request, 'donors/eligibility.html', context)

    # GET request
    if _is_api_request(request):
        return JsonResponse({
            'is_eligible': getattr(request.user, 'is_eligible', False),
            'status': latest_response.status if latest_response else 'Pending Screening',
            'latest_eligibility': {
                'status': latest_response.status,
                'reason': latest_response.ineligibility_reason,
                'created_at': latest_response.created_at.isoformat(),
            } if latest_response else None,
        })

    form = MedicalEligibilityForm()
    context = {
        'title': 'Medical Eligibility Screening',
        'form': form,
        'latest_eligibility': latest_response,
        'questions': QUESTIONNAIRE_QUESTIONS,
    }
    return render(request, 'donors/eligibility.html', context)
