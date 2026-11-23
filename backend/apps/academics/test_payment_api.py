
from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

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


class PaymentAPISecurityTests(TestCase):

    def setUp(self):

        self.client = APIClient()

        self.student = self.create_user(
            "payment_student",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "payment_student2",
            User.Role.STUDENT,
        )

        self.teacher = self.create_user(
            "payment_teacher",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "payment_admin",
            User.Role.SYSTEM_ADMIN,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2045,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Payment Technology",
            code="PAYTECH",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Payment ICT",
            code="PAY-ICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = Course.objects.create(
            code="PAY-001",
            title="Payment Security Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            price=Decimal("1500.00"),
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            approval_status=Course.ApprovalStatus.PUBLISHED,
            is_active=True,
            created_by=self.teacher,
        )

        self.enrollment = CourseEnrollment.objects.create(
            course=self.course,
            student=self.student,
            status=CourseEnrollment.Status.ACTIVE,
        )

        self.other_enrollment = CourseEnrollment.objects.create(
            course=self.course,
            student=self.other_student,
            status=CourseEnrollment.Status.ACTIVE,
        )

        self.payments_url = "/api/academics/payments/"
        self.attempts_url = "/api/academics/payment-attempts/"
        self.refunds_url = "/api/academics/payment-refunds/"

    def create_user(self, username, role):

        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def authenticate(self, user):

        self.client.force_authenticate(user=user)

    def create_payment(
        self,
        enrollment=None,
        payment_status=EnrollmentPayment.Status.PAID,
        start=date(2045, 1, 1),
        end=date(2045, 1, 31),
    ):

        return EnrollmentPayment.objects.create(
            enrollment=enrollment or self.enrollment,
            payment_type=EnrollmentPayment.PaymentType.MONTHLY,
            amount=Decimal("1500.00"),
            currency="LKR",
            billing_period_start=start,
            billing_period_end=end,
            status=payment_status,
        )

    def get_response_items(self, response):

        if isinstance(response.data, dict):
            return response.data.get("results", [])

        return response.data

    # AUTHENTICATION

    def test_unauthenticated_user_cannot_access_payments(self):

        response = self.client.get(self.payments_url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    # PAYMENT OBLIGATION ACCESS

    def test_student_can_only_list_own_payments(self):

        self.create_payment()

        self.create_payment(
            enrollment=self.other_enrollment,
            start=date(2045, 2, 1),
            end=date(2045, 2, 28),
        )

        self.authenticate(self.student)

        response = self.client.get(self.payments_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        items = self.get_response_items(response)

        self.assertEqual(len(items), 1)

        self.assertEqual(
            items[0]["enrollment"],
            self.enrollment.id,
        )

    def test_student_cannot_retrieve_another_students_payment(self):

        other_payment = self.create_payment(
            enrollment=self.other_enrollment,
        )

        self.authenticate(self.student)

        response = self.client.get(
            f"{self.payments_url}{other_payment.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_student_can_create_own_payment_obligation(self):

        self.authenticate(self.student)

        response = self.client.post(
            self.payments_url,
            {
                "enrollment": self.enrollment.id,
                "billing_period_start": "2045-01-01",
                "billing_period_end": "2045-01-31",
                "currency": "lkr",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        payment = EnrollmentPayment.objects.get(
            enrollment=self.enrollment,
        )

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PENDING,
        )

        self.assertEqual(payment.currency, "LKR")

    def test_student_cannot_create_payment_for_another_students_enrollment(self):

        self.authenticate(self.student)

        response = self.client.post(
            self.payments_url,
            {
                "enrollment": self.other_enrollment.id,
                "billing_period_start": "2045-01-01",
                "billing_period_end": "2045-01-31",
                "currency": "LKR",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            EnrollmentPayment.objects.filter(
                enrollment=self.other_enrollment,
            ).exists()
        )

    def test_admin_can_list_all_payment_obligations(self):

        self.create_payment()

        self.create_payment(
            enrollment=self.other_enrollment,
            start=date(2045, 2, 1),
            end=date(2045, 2, 28),
        )

        self.authenticate(self.admin)

        response = self.client.get(self.payments_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        items = self.get_response_items(response)

        self.assertEqual(len(items), 2)

    def test_teacher_cannot_access_payment_obligations(self):

        self.create_payment()

        self.authenticate(self.teacher)

        response = self.client.get(self.payments_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        items = self.get_response_items(response)

        self.assertEqual(len(items), 0)

    # PAYMENT ATTEMPT ACCESS

    def test_student_cannot_create_payment_attempt_through_api(self):

        payment = self.create_payment(
            payment_status=EnrollmentPayment.Status.PENDING,
        )

        self.authenticate(self.student)

        response = self.client.post(
            self.attempts_url,
            {
                "payment": payment.id,
                "provider": "TEST_PROVIDER",
                "idempotency_key": str(uuid4()),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertEqual(
            PaymentAttempt.objects.filter(
                payment=payment,
            ).count(),
            0,
        )

    def test_student_cannot_view_another_students_payment_attempt(self):

        payment = self.create_payment(
            enrollment=self.other_enrollment,
            payment_status=EnrollmentPayment.Status.PENDING,
        )

        attempt = PaymentAttempt.objects.create(
            payment=payment,
            provider="TEST_PROVIDER",
            idempotency_key=uuid4(),
            amount=payment.amount,
            currency=payment.currency,
        )

        self.authenticate(self.student)

        response = self.client.get(
            f"{self.attempts_url}{attempt.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # REFUND ACCESS

    def test_student_cannot_request_payment_refund(self):

        payment = self.create_payment()

        self.authenticate(self.student)

        response = self.client.post(
            self.refunds_url,
            {
                "payment": payment.id,
                "amount": "500.00",
                "reason": "Refund request",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertEqual(payment.refunds.count(), 0)

    def test_admin_can_request_payment_refund(self):

        payment = self.create_payment()

        self.authenticate(self.admin)

        response = self.client.post(
            self.refunds_url,
            {
                "payment": payment.id,
                "amount": "500.00",
                "reason": "Approved partial refund",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertEqual(payment.refunds.count(), 1)

        refund = payment.refunds.get()

        self.assertEqual(
            refund.status,
            refund.Status.PENDING,
        )

        self.assertEqual(
            refund.amount,
            Decimal("500.00"),
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            EnrollmentPayment.Status.PAID,
        )
