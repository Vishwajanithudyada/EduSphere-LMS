
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AcademicYear(models.Model):
    year = models.PositiveIntegerField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return str(self.year)


class Stream(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    streams = models.ManyToManyField(
        Stream,
        related_name="subjects",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Course(models.Model):

    class CourseType(models.TextChoices):
        THEORY = "THEORY", "Theory"
        REVISION = "REVISION", "Revision"
        PAPER = "PAPER", "Paper Class"
        OTHER = "OTHER", "Other"

    class DeliveryMode(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        PHYSICAL = "PHYSICAL", "Physical"
        HYBRID = "HYBRID", "Hybrid"
        RECORDED = "RECORDED", "Recorded"

    class ApprovalStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    class EnrollmentMethod(models.TextChoices):
        OPEN = "OPEN", "Open Enrollment"
        PAID = "PAID", "Payment Required (Legacy)"
        INVITATION = "INVITATION", "Invitation Only"
        APPROVAL = "APPROVAL", "Admin Approval Required"

    class AccessPolicy(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly Subscription"
        COMPLETION = "COMPLETION", "Completion Based"

    code = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)

    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="courses",
    )

    stream = models.ForeignKey(
        Stream,
        on_delete=models.PROTECT,
        related_name="courses",
    )

    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name="courses",
    )

    course_type = models.CharField(
        max_length=20,
        choices=CourseType.choices,
        default=CourseType.THEORY,
    )

    delivery_mode = models.CharField(
        max_length=20,
        choices=DeliveryMode.choices,
        default=DeliveryMode.ONLINE,
    )

    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "For MONTHLY courses, this is the monthly fee. "
            "For COMPLETION courses, this is the one-time fee."
        ),
    )

    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )

    enrollment_method = models.CharField(
        max_length=20,
        choices=EnrollmentMethod.choices,
        default=EnrollmentMethod.OPEN,
    )

    access_policy = models.CharField(
        max_length=20,
        choices=AccessPolicy.choices,
        default=AccessPolicy.MONTHLY,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_courses",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_courses",
        null=True,
        blank=True,
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    rejection_reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        if self.subject_id and self.stream_id:
            if not self.subject.streams.filter(
                pk=self.stream_id
            ).exists():
                raise ValidationError({
                    "subject": (
                        "This subject is not assigned "
                        "to the selected stream."
                    )
                })

        if self.price < 0:
            raise ValidationError({
                "price": "Course price cannot be negative."
            })

        if (
            self.approval_status == self.ApprovalStatus.REJECTED
            and not self.rejection_reason.strip()
        ):
            raise ValidationError({
                "rejection_reason": "A rejection reason is required."
            })

    def __str__(self):
        return f"{self.title} ({self.code})"


class CourseApprovalLog(models.Model):

    class Action(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted for Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PUBLISHED = "PUBLISHED", "Published"

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="approval_history",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="course_approval_actions",
    )

    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Course Approval History"
        verbose_name_plural = "Course Approval Histories"

    def __str__(self):
        return f"{self.course.title} - {self.action}"


class CourseEnrollment(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="course_enrollments",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    enrolled_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student"],
                name="unique_student_course_enrollment",
            ),
        ]

    def __str__(self):
        return f"{self.student} - {self.course}"


class EnrollmentPayment(models.Model):
    """
    Represents a payment obligation.

    Monthly courses:
        One obligation per billing period.

    Completion courses:
        One obligation for the entire course.

    Individual payment attempts are stored separately.
    """

    class PaymentType(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly Payment"
        ONE_TIME = "ONE_TIME", "One-Time Payment"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        REFUNDED = "REFUNDED", "Refunded"

    enrollment = models.ForeignKey(
        CourseEnrollment,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="LKR",
    )

    billing_period_start = models.DateField(
        null=True,
        blank=True,
    )

    billing_period_end = models.DateField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="enrollment_payment_amount_positive",
            ),
            models.UniqueConstraint(
                fields=["enrollment", "billing_period_start"],
                condition=models.Q(payment_type="MONTHLY"),
                name="unique_monthly_enrollment_payment_period",
            ),
            models.UniqueConstraint(
                fields=["enrollment"],
                condition=models.Q(payment_type="ONE_TIME"),
                name="unique_one_time_enrollment_payment",
            ),
        ]

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError({
                "amount": "Payment amount must be greater than zero."
            })

        if self.payment_type == self.PaymentType.MONTHLY:
            if not self.billing_period_start or not self.billing_period_end:
                raise ValidationError({
                    "billing_period_start": (
                        "Monthly payments require a billing period."
                    ),
                })

            if self.billing_period_end <= self.billing_period_start:
                raise ValidationError({
                    "billing_period_end": (
                        "Billing period end must be after start."
                    ),
                })

        elif self.payment_type == self.PaymentType.ONE_TIME:
            if self.billing_period_start or self.billing_period_end:
                raise ValidationError({
                    "billing_period_start": (
                        "One-time payments cannot have a billing period."
                    ),
                })

    def __str__(self):
        return f"{self.enrollment} - {self.amount} {self.currency}"


class PaymentAttempt(models.Model):
    """
    Stores each individual attempt to pay an EnrollmentPayment.

    Multiple failed attempts are allowed.
    Only one successful attempt is allowed per obligation.
    """

    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    payment = models.ForeignKey(
        EnrollmentPayment,
        on_delete=models.PROTECT,
        related_name="attempts",
    )

    provider = models.CharField(
        max_length=100,
    )

    transaction_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="LKR",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIATED,
    )

    failure_code = models.CharField(
        max_length=100,
        blank=True,
    )

    failure_message = models.TextField(
        blank=True,
    )

    initiated_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-initiated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_attempt_amount_positive",
            ),
            models.UniqueConstraint(
                fields=["provider", "transaction_id"],
                condition=(
                    models.Q(transaction_id__isnull=False)
                    & ~models.Q(transaction_id="")
                ),
                name="unique_provider_transaction_id",
            ),
            models.UniqueConstraint(
                fields=["payment"],
                condition=models.Q(status="SUCCEEDED"),
                name="unique_successful_payment_attempt",
            ),
        ]

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError({
                "amount": "Payment attempt amount must be greater than zero."
            })

        if self.payment_id:
            if self.amount != self.payment.amount:
                raise ValidationError({
                    "amount": (
                        "Payment attempt amount must match "
                        "the payment obligation amount."
                    )
                })

            if self.currency != self.payment.currency:
                raise ValidationError({
                    "currency": (
                        "Payment attempt currency must match "
                        "the payment obligation currency."
                    )
                })

    def __str__(self):
        return (
            f"{self.payment} - "
            f"{self.provider} - {self.status}"
        )


class PaymentWebhookEvent(models.Model):
    """
    Stores incoming payment-provider webhook events.

    Events are uniquely identified by provider + event_id.
    Signature verification and event processing are tracked separately.
    """

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        FAILED = "FAILED", "Failed"
        IGNORED = "IGNORED", "Ignored"

    payment_attempt = models.ForeignKey(
        PaymentAttempt,
        on_delete=models.PROTECT,
        related_name="webhook_events",
        null=True,
        blank=True,
    )

    provider = models.CharField(
        max_length=100,
    )

    event_id = models.CharField(
        max_length=255,
    )

    event_type = models.CharField(
        max_length=100,
    )

    payload = models.JSONField(
        default=dict,
    )

    signature_verified = models.BooleanField(
        default=False,
    )

    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )

    error_message = models.TextField(
        blank=True,
    )

    received_at = models.DateTimeField(
        auto_now_add=True,
    )

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="unique_provider_webhook_event",
            ),
        ]

    def __str__(self):
        return f"{self.provider} - {self.event_id}"


class PaymentRefund(models.Model):
    """
    Stores refund requests and their processing history.

    A payment can have multiple partial refunds.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    payment = models.ForeignKey(
        EnrollmentPayment,
        on_delete=models.PROTECT,
        related_name="refunds",
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="LKR",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    refund_reference = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    reason = models.TextField(
        blank=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_payment_refunds",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_refund_amount_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.amount is not None and self.amount <= 0:
            raise ValidationError({
                "amount": "Refund amount must be greater than zero."
            })

        if self.payment_id:
            if self.payment.status != EnrollmentPayment.Status.PAID:
                raise ValidationError({
                    "payment": (
                        "Only successfully paid obligations "
                        "can be refunded."
                    )
                })

            if self.currency != self.payment.currency:
                raise ValidationError({
                    "currency": (
                        "Refund currency must match "
                        "the original payment currency."
                    )
                })

            if self.amount > self.payment.amount:
                raise ValidationError({
                    "amount": (
                        "Refund amount cannot exceed "
                        "the original payment amount."
                    )
                })

    def __str__(self):
        return (
            f"Refund - {self.payment} - "
            f"{self.amount} {self.currency}"
        )


class CourseInvitation(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="invitations",
    )

    invited_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="course_invitations",
        null=True,
        blank=True,
    )

    invited_email = models.EmailField()

    token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_course_invitations",
    )

    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "invited_email"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_course_invitation_email",
            ),
        ]

    def __str__(self):
        return f"{self.invited_email} - {self.course}"


class EnrollmentRequest(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name="enrollment_requests",
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="enrollment_requests",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    student_message = models.TextField(blank=True)
    admin_remarks = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_enrollment_requests",
        null=True,
        blank=True,
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "student"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_enrollment_request",
            ),
        ]

    def __str__(self):
        return f"{self.student} - {self.course} ({self.status})"


class CourseModule(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "order"],
                name="unique_course_module_order",
            ),
        ]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


class Lesson(models.Model):
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    content = models.TextField(blank=True)
    video_url = models.URLField(blank=True)

    billing_period_start = models.DateField(
        null=True,
        blank=True,
    )

    billing_period_end = models.DateField(
        null=True,
        blank=True,
    )

    order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["module", "order"],
                name="unique_module_lesson_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        billing_period_start__isnull=True,
                        billing_period_end__isnull=True,
                    )
                    | models.Q(
                        billing_period_start__isnull=False,
                        billing_period_end__isnull=False,
                        billing_period_end__gt=models.F(
                            "billing_period_start"
                        ),
                    )
                ),
                name="lesson_valid_billing_period",
            ),
        ]

    def clean(self):
        super().clean()

        if not self.module_id:
            return

        access_policy = self.module.course.access_policy

        if access_policy == Course.AccessPolicy.MONTHLY:
            if not self.billing_period_start or not self.billing_period_end:
                raise ValidationError(
                    "Monthly course lessons require a billing period."
                )

        elif self.billing_period_start or self.billing_period_end:
            raise ValidationError(
                "Completion course lessons cannot have a billing period."
            )

    def __str__(self):
        return self.title
