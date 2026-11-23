
from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.academics.models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseEnrollment,
    EnrollmentPayment,
    PaymentAttempt,
    PaymentRefund,
)
from apps.academics.services.payment_services import (
    create_payment_obligation,
    create_payment_attempt,
    _record_verified_payment_success,
    request_payment_refund,
    _record_verified_refund_success,
)


class PaymentProcessingTestCase(TestCase):

    def setUp(self):
        self.student = self.create_user(
            "processing_student",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "processing_other_student",
            User.Role.STUDENT,
        )

        self.teacher = self.create_user(
            "processing_teacher",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "processing_admin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2029,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Technology",
            code="TECH",
            description="Technology stream",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Information and Communication Technology",
            code="ICT",
            description="ICT subject",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = Course.objects.create(
            code="ICT2029-PROC-001",
            title="Payment Processing Test Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            course_type=Course.CourseType.THEORY,
            delivery_mode=Course.DeliveryMode.ONLINE,
            description="Payment processing test course",
            price=Decimal("1500.00"),
            approval_status="PUBLISHED",
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            created_by=self.teacher,
            is_active=True,
        )

        self.enrollment = CourseEnrollment.objects.create(
            course=self.course,
            student=self.student,
            status=CourseEnrollment.Status.PENDING,
        )

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def create_paid_attempt(self):
        payment = create_payment_obligation(
            enrollment_id=self.enrollment.id,
            user=self.student,
            billing_period_start=date(2029, 1, 1),
            billing_period_end=date(2029, 1, 31),
            currency="LKR",
        )

        attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=uuid4(),
        )

        return payment, attempt

    def verify_success(self, attempt):
        return _record_verified_payment_success(
            attempt_id=attempt.id,
            provider="TEST_PROVIDER",
            transaction_id=f"TX-{uuid4().hex}",
            amount=Decimal("1500.00"),
            currency="LKR",
        )

    # --------------------------------------------------
    # VERIFIED PAYMENT SUCCESS
    # --------------------------------------------------

    def test_verified_payment_success_marks_payment_paid(self):
        payment, attempt = self.create_paid_attempt()

        self.verify_success(attempt)

        payment.refresh_from_db()
        attempt.refresh_from_db()
        self.enrollment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PAID,
        )

        self.assertEqual(
            attempt.status,
            PaymentAttempt.Status.SUCCEEDED,
        )

        self.assertIsNotNone(payment.paid_at)
        self.assertIsNotNone(attempt.completed_at)

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

        self.assertIsNotNone(self.enrollment.activated_at)

    def test_wrong_payment_amount_is_rejected(self):
        payment, attempt = self.create_paid_attempt()

        with self.assertRaises(ValidationError):
            _record_verified_payment_success(
                attempt_id=attempt.id,
                provider="TEST_PROVIDER",
                transaction_id=f"TX-{uuid4().hex}",
                amount=Decimal("1000.00"),
                currency="LKR",
            )

        payment.refresh_from_db()
        attempt.refresh_from_db()
        self.enrollment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

        self.assertEqual(
            attempt.status,
            PaymentAttempt.Status.INITIATED,
        )

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.PENDING,
        )

    def test_wrong_currency_is_rejected(self):
        payment, attempt = self.create_paid_attempt()

        with self.assertRaises(ValidationError):
            _record_verified_payment_success(
                attempt_id=attempt.id,
                provider="TEST_PROVIDER",
                transaction_id=f"TX-{uuid4().hex}",
                amount=Decimal("1500.00"),
                currency="USD",
            )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

    def test_wrong_provider_is_rejected(self):
        payment, attempt = self.create_paid_attempt()

        with self.assertRaises(ValidationError):
            _record_verified_payment_success(
                attempt_id=attempt.id,
                provider="UNEXPECTED_PROVIDER",
                transaction_id=f"TX-{uuid4().hex}",
                amount=Decimal("1500.00"),
                currency="LKR",
            )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

    def test_repeated_success_callback_is_idempotent(self):
        payment, attempt = self.create_paid_attempt()

        transaction_id = f"TX-{uuid4().hex}"

        first_result = _record_verified_payment_success(
            attempt_id=attempt.id,
            provider="TEST_PROVIDER",
            transaction_id=transaction_id,
            amount=Decimal("1500.00"),
            currency="LKR",
        )

        second_result = _record_verified_payment_success(
            attempt_id=attempt.id,
            provider="TEST_PROVIDER",
            transaction_id=transaction_id,
            amount=Decimal("1500.00"),
            currency="LKR",
        )

        self.assertEqual(first_result.id, second_result.id)

        self.assertEqual(
            PaymentAttempt.objects.filter(
                payment=payment,
                status=PaymentAttempt.Status.SUCCEEDED,
            ).count(),
            1,
        )

    # --------------------------------------------------
    # REFUND TESTS
    # --------------------------------------------------

    def test_student_cannot_request_refund(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        with self.assertRaises(PermissionDenied):
            request_payment_refund(
                payment_id=payment.id,
                user=self.student,
                amount=Decimal("500.00"),
                reason="Test refund",
            )

    def test_admin_can_request_partial_refund(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        refund = request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("500.00"),
            reason="Partial refund test",
        )

        self.assertEqual(
            refund.status,
            PaymentRefund.Status.PENDING,
        )

        self.assertEqual(
            refund.amount,
            Decimal("500.00"),
        )

    def test_partial_refund_keeps_payment_paid(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        refund = request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("500.00"),
            reason="Partial refund",
        )

        _record_verified_refund_success(
            refund_id=refund.id,
            refund_reference=f"REF-{uuid4().hex}",
        )

        payment.refresh_from_db()
        refund.refresh_from_db()

        self.assertEqual(
            refund.status,
            PaymentRefund.Status.SUCCEEDED,
        )

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PAID,
        )

        self.enrollment.refresh_from_db()

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

    def test_full_cumulative_refund_marks_payment_refunded(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        first_refund = request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("500.00"),
            reason="First partial refund",
        )

        second_refund = request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("1000.00"),
            reason="Remaining refund",
        )

        _record_verified_refund_success(
            refund_id=first_refund.id,
            refund_reference=f"REF-{uuid4().hex}",
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PAID,
        )

        _record_verified_refund_success(
            refund_id=second_refund.id,
            refund_reference=f"REF-{uuid4().hex}",
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.REFUNDED,
        )

        self.enrollment.refresh_from_db()

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

    def test_refund_requests_cannot_exceed_payment_amount(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("1000.00"),
            reason="First refund",
        )

        with self.assertRaises(ValidationError):
            request_payment_refund(
                payment_id=payment.id,
                user=self.admin,
                amount=Decimal("600.00"),
                reason="Excess refund",
            )

    def test_full_refund_revokes_only_payment_period(self):
        payment, attempt = self.create_paid_attempt()
        self.verify_success(attempt)

        refund = request_payment_refund(
            payment_id=payment.id,
            user=self.admin,
            amount=Decimal("1500.00"),
            reason="Full refund",
        )

        _record_verified_refund_success(
            refund_id=refund.id,
            refund_reference=f"REF-{uuid4().hex}",
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.REFUNDED,
        )

        self.enrollment.refresh_from_db()

        self.assertEqual(
            self.enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

        # A different paid billing period remains independent.
        february_payment = EnrollmentPayment.objects.create(
            enrollment=self.enrollment,
            payment_type=EnrollmentPayment.PaymentType.MONTHLY,
            status=EnrollmentPayment.Status.PAID,
            amount=Decimal("1500.00"),
            currency="LKR",
            billing_period_start=date(2029, 2, 1),
            billing_period_end=date(2029, 2, 28),
        )

        february_payment.refresh_from_db()

        self.assertEqual(
            february_payment.status,
            EnrollmentPayment.Status.PAID,
        )
