import json
from django.http import JsonResponse
from django.shortcuts import render
from accounts.models import User
from accounts.rbac import role_required, _is_api_request
from .forms import MedicalEligibilityForm
from .models import MedicalEligibilityResponse, QUESTIONNAIRE_QUESTIONS


@role_required(User.Role.DONOR, User.Role.ADMIN)
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

    context = {
        'title': 'Donor Dashboard',
        'donor': request.user,
        'next_eligible_date': 'Available now (No prior donations recorded)',
        'total_donations': 0,
        'recent_donations': [],
        'eligibility_status': eligibility_status,
        'latest_eligibility': latest_eligibility,
        'is_eligible': getattr(request.user, 'is_eligible', False),
    }
    return render(request, 'donors/dashboard.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def donation_history(request):
    """
    View donation history including Bag IDs, dates, and locations (SRS 4.2: BBMS-F-007).
    """
    context = {
        'title': 'Donation History',
        'donations': [],
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
