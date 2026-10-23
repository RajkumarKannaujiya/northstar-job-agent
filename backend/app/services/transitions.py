from app.models import ApplicationStatus

ALLOWED_TRANSITIONS = {
    ApplicationStatus.DISCOVERED: {ApplicationStatus.ANALYZING, ApplicationStatus.SKIPPED, ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.ANALYZING: {ApplicationStatus.MATCHED, ApplicationStatus.FAILED, ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.MATCHED: {ApplicationStatus.ELIGIBLE, ApplicationStatus.SKIPPED, ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.ELIGIBLE: {ApplicationStatus.APPLICATION_STARTED, ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.SKIPPED},
    ApplicationStatus.APPLICATION_STARTED: {ApplicationStatus.FORM_ANALYZING, ApplicationStatus.FAILED, ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.FORM_ANALYZING: {ApplicationStatus.FORM_FILLED, ApplicationStatus.FAILED, ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.FORM_FILLED: {ApplicationStatus.RESUME_UPLOADED, ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.FAILED},
    ApplicationStatus.RESUME_UPLOADED: {ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.FAILED},
    ApplicationStatus.READY_TO_SUBMIT: {ApplicationStatus.SUBMITTED, ApplicationStatus.MANUAL_ACTION_REQUIRED, ApplicationStatus.FAILED},
    ApplicationStatus.MANUAL_ACTION_REQUIRED: {ApplicationStatus.APPLICATION_STARTED, ApplicationStatus.FORM_ANALYZING, ApplicationStatus.FORM_FILLED, ApplicationStatus.RESUME_UPLOADED, ApplicationStatus.READY_TO_SUBMIT, ApplicationStatus.SUBMITTED, ApplicationStatus.FAILED, ApplicationStatus.SKIPPED},
    ApplicationStatus.SUBMITTED: {ApplicationStatus.ASSESSMENT, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.ASSESSMENT: {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.INTERVIEW: {ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.OFFER: {ApplicationStatus.WITHDRAWN},
    ApplicationStatus.FAILED: {ApplicationStatus.MANUAL_ACTION_REQUIRED},
    ApplicationStatus.SKIPPED: set(),
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.WITHDRAWN: set(),
}


def transition(current: ApplicationStatus, target: ApplicationStatus, *, confirmed_submission: bool = False) -> None:
    if target == ApplicationStatus.SUBMITTED and not confirmed_submission:
        raise ValueError("SUBMITTED requires a verified platform confirmation")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid application transition: {current.value} -> {target.value}")
