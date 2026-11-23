
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
)
from apps.academics.services.payment_services import (
    create_payment_obligation,
    create_payment_attempt,
    _record_payment_attempt_failure,
)


class PaymentServiceTestCase(TestCase):

    def setUp(self):
        # Users
        self.student = self.create_user(
            "student1",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "student2",
            User.Role.STUDENT,
        )

        self.teacher = self.create_user(
            "teacher1",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "admin1",
            User.Role.INSTITUTE_ADMIN,
        )

        # Academic data
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

        # Published monthly course
        self.course = Course.objects.create(
            code="ICT2029-PAY-001",
            title="ICT Payment Test Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            course_type=Course.CourseType.THEORY,
            delivery_mode=Course.DeliveryMode.ONLINE,
            description="Payment service test course",
            price=Decimal("1500.00"),
            approval_status="PUBLISHED",
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            created_by=self.teacher,
            is_active=True,
        )

        # Student enrollments
        self.enrollment = self.create_enrollment(
            self.student,
        )

        self.other_enrollment = self.create_enrollment(
            self.other_student,
        )

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def create_enrollment(self, student):
        return CourseEnrollment.objects.create(
            course=self.course,
            student=student,
            status=CourseEnrollment.Status.PENDING,
        )

    def create_monthly_payment(self):
        return create_payment_obligation(
            enrollment_id=self.enrollment.id,
            user=self.student,
            billing_period_start=date(2029, 1, 1),
            billing_period_end=date(2029, 1, 31),
            currency="LKR",
        )

    # --------------------------------------------------
    # PAYMENT OBLIGATION TESTS
    # --------------------------------------------------

    def test_student_can_create_monthly_payment_obligation(self):
        payment = self.create_monthly_payment()

        self.assertIsNotNone(payment.id)
        self.assertEqual(
            payment.enrollment_id,
            self.enrollment.id,
        )
        self.assertEqual(
            payment.payment_type,
            EnrollmentPayment.PaymentType.MONTHLY,
        )
        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )
        self.assertEqual(
            payment.amount,
            Decimal("1500.00"),
        )
        self.assertEqual(payment.currency, "LKR")

    def test_same_monthly_obligation_is_not_duplicated(self):
        first_payment = self.create_monthly_payment()
        second_payment = self.create_monthly_payment()

        self.assertEqual(
            first_payment.id,
            second_payment.id,
        )

        self.assertEqual(
            EnrollmentPayment.objects.filter(
                enrollment=self.enrollment,
                payment_type=EnrollmentPayment.PaymentType.MONTHLY,
                billing_period_start=date(2029, 1, 1),
            ).count(),
            1,
        )

    def test_different_billing_period_end_is_rejected(self):
        self.create_monthly_payment()

        with self.assertRaises(ValidationError):
            create_payment_obligation(
                enrollment_id=self.enrollment.id,
                user=self.student,
                billing_period_start=date(2029, 1, 1),
                billing_period_end=date(2029, 2, 1),
                currency="LKR",
            )

    def test_other_student_cannot_create_payment_for_someone_elses_enrollment(self):
        with self.assertRaises(PermissionDenied):
            create_payment_obligation(
                enrollment_id=self.enrollment.id,
                user=self.other_student,
                billing_period_start=date(2029, 1, 1),
                billing_period_end=date(2029, 1, 31),
                currency="LKR",
            )

    def test_teacher_cannot_create_student_payment_obligation(self):
        with self.assertRaises(PermissionDenied):
            create_payment_obligation(
                enrollment_id=self.enrollment.id,
                user=self.teacher,
                billing_period_start=date(2029, 1, 1),
                billing_period_end=date(2029, 1, 31),
                currency="LKR",
            )

    def test_completion_course_creates_one_time_obligation(self):
        self.course.access_policy = Course.AccessPolicy.COMPLETION
        self.course.save(update_fields=["access_policy"])

        payment = create_payment_obligation(
            enrollment_id=self.enrollment.id,
            user=self.student,
            currency="LKR",
        )

        self.assertEqual(
            payment.payment_type,
            EnrollmentPayment.PaymentType.ONE_TIME,
        )

        self.assertIsNone(payment.billing_period_start)
        self.assertIsNone(payment.billing_period_end)

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

    def test_completion_course_rejects_billing_period_dates(self):
        self.course.access_policy = Course.AccessPolicy.COMPLETION
        self.course.save(update_fields=["access_policy"])

        with self.assertRaises(ValidationError):
            create_payment_obligation(
                enrollment_id=self.enrollment.id,
                user=self.student,
                billing_period_start=date(2029, 1, 1),
                billing_period_end=date(2029, 1, 31),
                currency="LKR",
            )

    # --------------------------------------------------
    # PAYMENT ATTEMPT TESTS
    # --------------------------------------------------

    def test_student_can_create_payment_attempt(self):
        payment = self.create_monthly_payment()
        idempotency_key = uuid4()

        attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=idempotency_key,
        )

        self.assertIsNotNone(attempt.id)
        self.assertEqual(attempt.payment_id, payment.id)
        self.assertEqual(
            attempt.status,
            PaymentAttempt.Status.INITIATED,
        )
        self.assertEqual(
            attempt.amount,
            payment.amount,
        )
        self.assertEqual(
            attempt.currency,
            payment.currency,
        )

    def test_same_idempotency_key_returns_existing_attempt(self):
        payment = self.create_monthly_payment()
        idempotency_key = uuid4()

        first_attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=idempotency_key,
        )

        second_attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=idempotency_key,
        )

        self.assertEqual(
            first_attempt.id,
            second_attempt.id,
        )

        self.assertEqual(
            PaymentAttempt.objects.filter(
                payment=payment,
            ).count(),
            1,
        )

    def test_other_student_cannot_create_payment_attempt(self):
        payment = self.create_monthly_payment()

        with self.assertRaises(PermissionDenied):
            create_payment_attempt(
                payment_id=payment.id,
                user=self.other_student,
                provider="TEST_PROVIDER",
                idempotency_key=uuid4(),
            )

    def test_teacher_cannot_create_payment_attempt(self):
        payment = self.create_monthly_payment()

        with self.assertRaises(PermissionDenied):
            create_payment_attempt(
                payment_id=payment.id,
                user=self.teacher,
                provider="TEST_PROVIDER",
                idempotency_key=uuid4(),
            )

    def test_failed_attempt_allows_new_retry(self):
        payment = self.create_monthly_payment()

        first_attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=uuid4(),
        )

        _record_payment_attempt_failure(
            attempt_id=first_attempt.id,
            failure_code="TEST_FAILURE",
            failure_message="Simulated payment failure",
        )

        first_attempt.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(
            first_attempt.status,
            PaymentAttempt.Status.FAILED,
        )

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

        second_attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=uuid4(),
        )

        self.assertNotEqual(
            first_attempt.id,
            second_attempt.id,
        )

        self.assertEqual(
            second_attempt.status,
            PaymentAttempt.Status.INITIATED,
        )

        self.assertEqual(
            PaymentAttempt.objects.filter(
                payment=payment,
            ).count(),
            2,
        )

    def test_pending_payment_cannot_be_marked_paid_by_student(self):
        payment = self.create_monthly_payment()

        attempt = create_payment_attempt(
            payment_id=payment.id,
            user=self.student,
            provider="TEST_PROVIDER",
            idempotency_key=uuid4(),
        )

        payment.refresh_from_db()
        attempt.refresh_from_db()

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
