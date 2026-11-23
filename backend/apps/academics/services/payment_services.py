
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.academics.models import (
    Course,
    CourseEnrollment,
    EnrollmentPayment,
    PaymentAttempt,
    PaymentRefund,
)


# ============================================================
# PERMISSION HELPERS
# ============================================================

def _require_student(user):
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if user.role != User.Role.STUDENT:
        raise PermissionDenied(
            "Only students can perform this action."
        )


def _require_admin(user):
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if user.role not in [
        User.Role.INSTITUTE_ADMIN,
        User.Role.SYSTEM_ADMIN,
    ]:
        raise PermissionDenied(
            "Only administrators can perform this action."
        )


# ============================================================
# LOCKED OBJECT HELPERS
# ============================================================

def _get_locked_enrollment(enrollment_id):
    try:
        return (
            CourseEnrollment.objects
            .select_for_update()
            .select_related("course")
            .get(pk=enrollment_id)
        )
    except CourseEnrollment.DoesNotExist:
        raise ValidationError("Enrollment does not exist.")


def _get_locked_payment(payment_id):
    try:
        return EnrollmentPayment.objects.select_for_update().get(
            pk=payment_id
        )
    except EnrollmentPayment.DoesNotExist:
        raise ValidationError("Payment obligation does not exist.")


def _get_locked_attempt(attempt_id):
    try:
        return PaymentAttempt.objects.select_for_update().get(
            pk=attempt_id
        )
    except PaymentAttempt.DoesNotExist:
        raise ValidationError("Payment attempt does not exist.")


def _get_locked_refund(refund_id):
    try:
        return PaymentRefund.objects.select_for_update().get(
            pk=refund_id
        )
    except PaymentRefund.DoesNotExist:
        raise ValidationError("Refund does not exist.")


def _get_initial_attempt_payment_ids(attempt_id):
    """
    Read identifiers without acquiring locks.

    Actual lock order:
        Enrollment -> Payment -> Attempt
    """

    try:
        initial_attempt = PaymentAttempt.objects.only(
            "payment_id"
        ).get(pk=attempt_id)
    except PaymentAttempt.DoesNotExist:
        raise ValidationError("Payment attempt does not exist.")

    try:
        initial_payment = EnrollmentPayment.objects.only(
            "enrollment_id"
        ).get(pk=initial_attempt.payment_id)
    except EnrollmentPayment.DoesNotExist:
        raise ValidationError("Payment obligation does not exist.")

    return initial_attempt.payment_id, initial_payment.enrollment_id


# ============================================================
# VALIDATION
# ============================================================

def _validate_enrollment_for_payment(enrollment):
    course = enrollment.course

    if enrollment.status not in [
        CourseEnrollment.Status.PENDING,
        CourseEnrollment.Status.ACTIVE,
    ]:
        raise ValidationError(
            "This enrollment cannot receive payments."
        )

    if (
        not course.is_active
        or course.approval_status != Course.ApprovalStatus.PUBLISHED
    ):
        raise ValidationError(
            "Payments are only allowed for published active courses."
        )

    if course.price <= Decimal("0.00"):
        raise ValidationError(
            "Free courses do not require payment obligations."
        )


# ============================================================
# PAYMENT OBLIGATION
# ============================================================

@transaction.atomic
def create_payment_obligation(
    enrollment_id,
    user,
    billing_period_start=None,
    billing_period_end=None,
    currency="LKR",
):
    """
    Create or retrieve a payment obligation.

    MONTHLY:
        One obligation per billing period.

    COMPLETION:
        One one-time obligation.

    Repeated calls for the same obligation return the existing record.
    """

    _require_student(user)

    enrollment = _get_locked_enrollment(enrollment_id)

    if enrollment.student_id != user.id:
        raise PermissionDenied(
            "You can only create payments for your own enrollment."
        )

    _validate_enrollment_for_payment(enrollment)

    course = Course.objects.select_for_update().get(
        pk=enrollment.course_id
    )

    if not isinstance(currency, str):
        raise ValidationError("Invalid currency.")

    if not currency or len(currency.strip()) != 3:
        raise ValidationError(
            "A valid three-letter currency is required."
        )

    currency = currency.strip().upper()

    if course.access_policy == Course.AccessPolicy.MONTHLY:

        if not billing_period_start or not billing_period_end:
            raise ValidationError(
                "Monthly payments require billing period start and end dates."
            )

        if billing_period_end <= billing_period_start:
            raise ValidationError(
                "Billing period end must be after its start."
            )

        payment_type = EnrollmentPayment.PaymentType.MONTHLY

        lookup = {
            "enrollment": enrollment,
            "payment_type": payment_type,
            "billing_period_start": billing_period_start,
        }

        defaults = {
            "amount": course.price,
            "currency": currency,
            "billing_period_end": billing_period_end,
        }

    elif course.access_policy == Course.AccessPolicy.COMPLETION:

        if billing_period_start or billing_period_end:
            raise ValidationError(
                "Completion-based payments cannot have billing periods."
            )

        payment_type = EnrollmentPayment.PaymentType.ONE_TIME

        lookup = {
            "enrollment": enrollment,
            "payment_type": payment_type,
        }

        defaults = {
            "amount": course.price,
            "currency": currency,
            "billing_period_start": None,
            "billing_period_end": None,
        }

    else:
        raise ValidationError("Unsupported course access policy.")

    payment = EnrollmentPayment.objects.filter(**lookup).first()

    if payment:
        if payment.status == EnrollmentPayment.Status.REFUNDED:
            raise ValidationError(
                "This payment obligation has already been refunded."
            )

        if payment.currency != currency:
            raise ValidationError(
                "Currency does not match the existing payment obligation."
            )

        if payment.amount != course.price:
            raise ValidationError(
                "Course price does not match the existing obligation."
            )

        if (
            payment.payment_type == EnrollmentPayment.PaymentType.MONTHLY
            and payment.billing_period_end != billing_period_end
        ):
            raise ValidationError(
                "The billing period does not match the existing obligation."
            )

        return payment

    payment = EnrollmentPayment(
        **lookup,
        **defaults,
    )

    payment.full_clean()
    payment.save()

    return payment


# ============================================================
# PAYMENT ATTEMPT
# ============================================================

@transaction.atomic
def create_payment_attempt(
    payment_id,
    user,
    provider,
    idempotency_key,
):
    """
    Create a retryable payment attempt.

    Consistent lock order:
        Enrollment -> Payment -> Attempt

    This function never marks a payment as successful.
    """

    _require_student(user)

    if not isinstance(provider, str) or not provider.strip():
        raise ValidationError("Payment provider is required.")

    provider = provider.strip()

    if len(provider) > 100:
        raise ValidationError("Payment provider name is too long.")

    try:
        idempotency_key = UUID(str(idempotency_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(
            "A valid UUID idempotency key is required."
        )

    try:
        initial_payment = EnrollmentPayment.objects.only(
            "enrollment_id"
        ).get(pk=payment_id)
    except EnrollmentPayment.DoesNotExist:
        raise ValidationError("Payment obligation does not exist.")

    enrollment = CourseEnrollment.objects.select_for_update().get(
        pk=initial_payment.enrollment_id
    )

    payment = _get_locked_payment(payment_id)

    if payment.enrollment_id != enrollment.id:
        raise ValidationError(
            "Payment obligation does not match enrollment."
        )

    if enrollment.student_id != user.id:
        raise PermissionDenied(
            "You can only pay your own payment obligations."
        )

    if enrollment.status not in [
        CourseEnrollment.Status.PENDING,
        CourseEnrollment.Status.ACTIVE,
    ]:
        raise ValidationError(
            "This enrollment cannot receive payment attempts."
        )

    existing = PaymentAttempt.objects.filter(
        idempotency_key=idempotency_key
    ).first()

    if existing:
        if (
            existing.payment_id != payment.id
            or existing.provider != provider
        ):
            raise ValidationError(
                "This idempotency key has already been used."
            )

        return existing

    if payment.status != EnrollmentPayment.Status.PENDING:
        raise ValidationError(
            "Only pending payment obligations can receive attempts."
        )

    attempt = PaymentAttempt(
        payment=payment,
        provider=provider,
        amount=payment.amount,
        currency=payment.currency,
        status=PaymentAttempt.Status.INITIATED,
        idempotency_key=idempotency_key,
    )

    attempt.full_clean()
    attempt.save()

    return attempt


# ============================================================
# VERIFIED PAYMENT SUCCESS
# ============================================================

@transaction.atomic
def _record_verified_payment_success(
    attempt_id,
    provider,
    transaction_id,
    amount,
    currency,
):
    """
    INTERNAL PROVIDER ADAPTER FUNCTION.

    Call ONLY after independently verifying the provider's
    authenticity, signature and transaction response.

    Never expose this function through a student-facing API.
    """

    if not isinstance(transaction_id, str) or not transaction_id.strip():
        raise ValidationError("Provider transaction ID is required.")

    if not isinstance(provider, str) or not provider.strip():
        raise ValidationError("Provider is required.")

    if not isinstance(currency, str) or not currency.strip():
        raise ValidationError("Provider currency is required.")

    try:
        verified_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Invalid provider payment amount.")

    if not verified_amount.is_finite():
        raise ValidationError("Invalid provider payment amount.")

    transaction_id = transaction_id.strip()
    provider = provider.strip()
    currency = currency.strip().upper()

    payment_id, enrollment_id = _get_initial_attempt_payment_ids(
        attempt_id
    )

    enrollment = CourseEnrollment.objects.select_for_update().get(
        pk=enrollment_id
    )

    payment = _get_locked_payment(payment_id)
    attempt = _get_locked_attempt(attempt_id)

    if (
        attempt.payment_id != payment.id
        or payment.enrollment_id != enrollment.id
    ):
        raise ValidationError(
            "Payment attempt does not match obligation."
        )

    if attempt.provider != provider:
        raise ValidationError("Payment provider does not match.")

    if verified_amount != payment.amount:
        raise ValidationError(
            "Provider payment amount does not match the obligation."
        )

    if currency != payment.currency:
        raise ValidationError(
            "Provider payment currency does not match the obligation."
        )

    # Idempotent repeated successful callback.
    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        if (
            attempt.transaction_id == transaction_id
            and payment.status == EnrollmentPayment.Status.PAID
        ):
            return attempt

        raise ValidationError(
            "This payment attempt has already been completed."
        )

    if attempt.status not in [
        PaymentAttempt.Status.INITIATED,
        PaymentAttempt.Status.PENDING,
    ]:
        raise ValidationError(
            "This payment attempt cannot be marked successful."
        )

    if payment.status != EnrollmentPayment.Status.PENDING:
        raise ValidationError(
            "This payment obligation is no longer pending."
        )

    if enrollment.status not in [
        CourseEnrollment.Status.PENDING,
        CourseEnrollment.Status.ACTIVE,
    ]:
        raise ValidationError(
            "This enrollment cannot be activated by payment."
        )

    now = timezone.now()

    attempt.transaction_id = transaction_id
    attempt.status = PaymentAttempt.Status.SUCCEEDED
    attempt.completed_at = now

    attempt.full_clean()
    attempt.save(
        update_fields=[
            "transaction_id",
            "status",
            "completed_at",
            "updated_at",
        ]
    )

    payment.status = EnrollmentPayment.Status.PAID
    payment.paid_at = now

    payment.save(
        update_fields=[
            "status",
            "paid_at",
            "updated_at",
        ]
    )

    if enrollment.status == CourseEnrollment.Status.PENDING:
        enrollment.status = CourseEnrollment.Status.ACTIVE
        enrollment.activated_at = now

        enrollment.save(
            update_fields=[
                "status",
                "activated_at",
                "updated_at",
            ]
        )

    return attempt


# ============================================================
# PAYMENT FAILURE
# ============================================================

@transaction.atomic
def _record_payment_attempt_failure(
    attempt_id,
    failure_code="",
    failure_message="",
):
    """
    INTERNAL PROVIDER ADAPTER FUNCTION.

    A failed attempt does not change the payment obligation status.
    """

    payment_id, enrollment_id = _get_initial_attempt_payment_ids(
        attempt_id
    )

    CourseEnrollment.objects.select_for_update().get(
        pk=enrollment_id
    )

    payment = _get_locked_payment(payment_id)
    attempt = _get_locked_attempt(attempt_id)

    if attempt.payment_id != payment.id:
        raise ValidationError(
            "Payment attempt does not match obligation."
        )

    if payment.status != EnrollmentPayment.Status.PENDING:
        raise ValidationError(
            "Only pending payment obligations can have failed attempts."
        )

    if attempt.status == PaymentAttempt.Status.FAILED:
        return attempt

    if attempt.status not in [
        PaymentAttempt.Status.INITIATED,
        PaymentAttempt.Status.PENDING,
    ]:
        raise ValidationError(
            "This payment attempt cannot be marked failed."
        )

    attempt.status = PaymentAttempt.Status.FAILED
    attempt.failure_code = (failure_code or "")[:100]
    attempt.failure_message = failure_message or ""
    attempt.completed_at = timezone.now()

    attempt.save(
        update_fields=[
            "status",
            "failure_code",
            "failure_message",
            "completed_at",
            "updated_at",
        ]
    )

    return attempt


# ============================================================
# REFUND REQUEST
# ============================================================

@transaction.atomic
def request_payment_refund(
    payment_id,
    user,
    amount,
    reason="",
):
    """
    Administrators can request full or partial refunds.

    Pending and successful refunds are reserved against the
    remaining refundable amount.
    """

    _require_admin(user)

    try:
        refund_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Invalid refund amount.")

    if not refund_amount.is_finite() or refund_amount <= 0:
        raise ValidationError(
            "Refund amount must be greater than zero."
        )

    payment = _get_locked_payment(payment_id)

    if payment.status != EnrollmentPayment.Status.PAID:
        raise ValidationError(
            "Only paid obligations can be refunded."
        )

    reserved = payment.refunds.filter(
        status__in=[
            PaymentRefund.Status.PENDING,
            PaymentRefund.Status.SUCCEEDED,
        ]
    ).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    remaining = payment.amount - reserved

    if refund_amount > remaining:
        raise ValidationError(
            f"Refund exceeds the remaining refundable amount: {remaining}."
        )

    refund = PaymentRefund(
        payment=payment,
        amount=refund_amount,
        currency=payment.currency,
        status=PaymentRefund.Status.PENDING,
        reason=reason or "",
        requested_by=user,
    )

    refund.full_clean()
    refund.save()

    return refund


# ============================================================
# VERIFIED REFUND SUCCESS
# ============================================================

@transaction.atomic
def _record_verified_refund_success(
    refund_id,
    refund_reference,
):
    """
    INTERNAL PROVIDER ADAPTER FUNCTION.

    A partial refund keeps the obligation PAID.
    Cumulative full refunds change it to REFUNDED.
    """

    if (
        not isinstance(refund_reference, str)
        or not refund_reference.strip()
    ):
        raise ValidationError("Refund reference is required.")

    try:
        initial_refund = PaymentRefund.objects.only(
            "payment_id"
        ).get(pk=refund_id)
    except PaymentRefund.DoesNotExist:
        raise ValidationError("Refund does not exist.")

    payment = _get_locked_payment(initial_refund.payment_id)
    refund = _get_locked_refund(refund_id)

    refund_reference = refund_reference.strip()

    if refund.status == PaymentRefund.Status.SUCCEEDED:
        if refund.refund_reference == refund_reference:
            return refund

        raise ValidationError(
            "This refund has already been completed."
        )

    if refund.status != PaymentRefund.Status.PENDING:
        raise ValidationError(
            "Only pending refunds can be completed."
        )

    if payment.status != EnrollmentPayment.Status.PAID:
        raise ValidationError(
            "The payment obligation is not refundable."
        )

    refund.refund_reference = refund_reference
    refund.status = PaymentRefund.Status.SUCCEEDED
    refund.completed_at = timezone.now()

    refund.full_clean()
    refund.save(
        update_fields=[
            "refund_reference",
            "status",
            "completed_at",
        ]
    )

    successful_total = payment.refunds.filter(
        status=PaymentRefund.Status.SUCCEEDED
    ).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    if successful_total > payment.amount:
        raise ValidationError(
            "Total successful refunds cannot exceed the payment amount."
        )

    if successful_total == payment.amount:
        payment.status = EnrollmentPayment.Status.REFUNDED

        payment.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

    return refund


# ============================================================
# REFUND FAILURE
# ============================================================

@transaction.atomic
def _record_refund_failure(refund_id):
    """
    INTERNAL PROVIDER ADAPTER FUNCTION.
    """

    try:
        initial_refund = PaymentRefund.objects.only(
            "payment_id"
        ).get(pk=refund_id)
    except PaymentRefund.DoesNotExist:
        raise ValidationError("Refund does not exist.")

    payment = _get_locked_payment(initial_refund.payment_id)
    refund = _get_locked_refund(refund_id)

    if refund.payment_id != payment.id:
        raise ValidationError(
            "Refund does not match payment obligation."
        )

    if refund.status == PaymentRefund.Status.FAILED:
        return refund

    if refund.status != PaymentRefund.Status.PENDING:
        raise ValidationError(
            "Only pending refunds can be marked failed."
        )

    refund.status = PaymentRefund.Status.FAILED
    refund.completed_at = timezone.now()

    refund.save(
        update_fields=[
            "status",
            "completed_at",
        ]
    )

    return refund
