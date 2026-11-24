
from decimal import Decimal
from datetime import timedelta

from django.utils import timezone

from django.core.exceptions import (
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User

from apps.academics.models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseApprovalLog,
    CourseEnrollment,
    EnrollmentRequest,
    CourseInvitation,
)
from apps.academics.services.course_workflow import (
    submit_course,
    approve_course,
    reject_course,
    publish_course,
)


class AcademicsTestDataMixin:
    """
    Shared test data and helper methods.
    """

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def create_course(self, creator, code="ICT2029-001"):
        return Course.objects.create(
            code=code,
            title="ICT Theory",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            course_type=Course.CourseType.THEORY,
            delivery_mode=Course.DeliveryMode.ONLINE,
            description="Test course description",
            price=Decimal("1500.00"),
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            created_by=creator,
        )


class CourseWorkflowTests(AcademicsTestDataMixin, TestCase):

    def setUp(self):
        self.teacher = self.create_user(
            "teacher",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "admin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.admin2 = self.create_user(
            "admin2",
            User.Role.INSTITUTE_ADMIN,
        )

        self.system_admin = self.create_user(
            "systemadmin",
            User.Role.SYSTEM_ADMIN,
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

        self.course = self.create_course(self.teacher)

    def test_teacher_can_create_course(self):
        course = self.create_course(
            self.teacher,
            code="ICT2029-002",
        )

        self.assertEqual(course.created_by, self.teacher)
        self.assertEqual(
            course.approval_status,
            Course.ApprovalStatus.DRAFT,
        )

    def test_teacher_can_submit_own_course(self):
        submit_course(self.course.id, self.teacher)

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.PENDING,
        )

    def test_teacher_cannot_submit_other_teachers_course(self):
        another_teacher = self.create_user(
            "anotherteacher",
            User.Role.TEACHER,
        )

        with self.assertRaises(DjangoPermissionDenied):
            submit_course(self.course.id, another_teacher)

    def test_teacher_cannot_approve_course(self):
        submit_course(self.course.id, self.teacher)

        with self.assertRaises(DjangoPermissionDenied):
            approve_course(self.course.id, self.teacher)

    def test_creator_cannot_approve_own_course(self):
        admin_course = self.create_course(
            self.admin,
            code="ICT2029-003",
        )

        submit_course(admin_course.id, self.admin)

        with self.assertRaises(DjangoPermissionDenied):
            approve_course(admin_course.id, self.admin)

    def test_different_admin_can_approve_course(self):
        submit_course(self.course.id, self.teacher)

        approve_course(self.course.id, self.admin)

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.APPROVED,
        )

        self.assertEqual(self.course.reviewed_by, self.admin)

    def test_course_creator_cannot_approve_own_admin_created_course(self):
        admin_course = self.create_course(
            self.admin,
            code="ICT2029-004",
        )

        submit_course(admin_course.id, self.admin)

        with self.assertRaises(DjangoPermissionDenied):
            approve_course(admin_course.id, self.admin)

    def test_creator_cannot_publish_own_course(self):
        admin_course = self.create_course(
            self.admin,
            code="ICT2029-005",
        )

        submit_course(admin_course.id, self.admin)

        approve_course(admin_course.id, self.admin2)

        with self.assertRaises(DjangoPermissionDenied):
            publish_course(admin_course.id, self.admin)

    def test_different_admin_can_publish_approved_course(self):
        submit_course(self.course.id, self.teacher)

        approve_course(self.course.id, self.admin)

        publish_course(self.course.id, self.admin2)

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.PUBLISHED,
        )

    def test_admin_can_reject_course_with_reason(self):
        submit_course(self.course.id, self.teacher)

        reject_course(
            self.course.id,
            self.admin,
            "Course information needs improvement.",
        )

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.REJECTED,
        )

        self.assertEqual(
            self.course.rejection_reason,
            "Course information needs improvement.",
        )

        self.assertEqual(self.course.reviewed_by, self.admin)

    def test_rejection_requires_reason(self):
        submit_course(self.course.id, self.teacher)

        with self.assertRaises(DjangoValidationError):
            reject_course(
                self.course.id,
                self.admin,
                "",
            )

    def test_system_admin_can_approve_course(self):
        submit_course(self.course.id, self.teacher)

        approve_course(self.course.id, self.system_admin)

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.APPROVED,
        )

        self.assertEqual(
            self.course.reviewed_by,
            self.system_admin,
        )

    def test_cannot_approve_non_pending_course(self):
        with self.assertRaises(DjangoValidationError):
            approve_course(self.course.id, self.admin)

    def test_approval_history_records_all_actions(self):
        submit_course(self.course.id, self.teacher)

        approve_course(self.course.id, self.admin)

        publish_course(self.course.id, self.admin2)

        history = CourseApprovalLog.objects.filter(
            course=self.course,
        ).order_by("created_at")

        self.assertEqual(history.count(), 3)

        actions = list(
            history.values_list("action", flat=True)
        )

        self.assertEqual(
            actions,
            [
                CourseApprovalLog.Action.SUBMITTED,
                CourseApprovalLog.Action.APPROVED,
                CourseApprovalLog.Action.PUBLISHED,
            ],
        )


class CourseModelValidationTests(AcademicsTestDataMixin, TestCase):

    def setUp(self):
        self.teacher = self.create_user(
            "validationteacher",
            User.Role.TEACHER,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2030,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Technology",
            code="TECH",
            is_active=True,
        )

        self.other_stream = Stream.objects.create(
            name="Science",
            code="SCI",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Information and Communication Technology",
            code="ICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course(self.teacher)

    def test_negative_course_price_is_rejected(self):
        self.course.price = Decimal("-100.00")

        with self.assertRaises(DjangoValidationError):
            self.course.full_clean()

    def test_subject_must_belong_to_selected_stream(self):
        self.course.stream = self.other_stream

        with self.assertRaises(DjangoValidationError):
            self.course.full_clean()

    def test_rejected_course_requires_reason(self):
        self.course.approval_status = (
            Course.ApprovalStatus.REJECTED
        )

        self.course.rejection_reason = ""

        with self.assertRaises(DjangoValidationError):
            self.course.full_clean()


class CourseAPITests(AcademicsTestDataMixin, TestCase):

    def setUp(self):
        self.client = APIClient()

        self.teacher = self.create_user(
            "apiteacher",
            User.Role.TEACHER,
        )

        self.another_teacher = self.create_user(
            "apiteacher2",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "apiadmin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.student = self.create_user(
            "apistudent",
            User.Role.STUDENT,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2029,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Technology",
            code="TECH",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Information and Communication Technology",
            code="ICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course(
            self.teacher,
            code="API-ICT-001",
        )

        self.course_url = "/api/academics/courses/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_course_payload(self, code="API-ICT-002"):
        return {
            "code": code,
            "title": "New ICT Course",
            "academic_year": self.academic_year.id,
            "stream": self.stream.id,
            "subject": self.subject.id,
            "course_type": Course.CourseType.THEORY,
            "delivery_mode": Course.DeliveryMode.ONLINE,
            "description": "API test course",
            "price": "1500.00",
            "enrollment_method": Course.EnrollmentMethod.PAID,
            "access_policy": Course.AccessPolicy.MONTHLY,
        }

    def get_response_ids(self, response):
        data = response.data

        if isinstance(data, dict) and "results" in data:
            data = data["results"]

        return [item["id"] for item in data]

    def test_unauthenticated_user_cannot_list_courses(self):
        response = self.client.get(self.course_url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_teacher_can_only_list_own_courses(self):
        another_course = self.create_course(
            self.another_teacher,
            code="API-ICT-003",
        )

        self.authenticate(self.teacher)

        response = self.client.get(self.course_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = self.get_response_ids(response)

        self.assertIn(self.course.id, returned_ids)
        self.assertNotIn(another_course.id, returned_ids)

    def test_student_can_only_see_published_active_courses(self):
        published_course = self.create_course(
            self.teacher,
            code="API-ICT-004",
        )

        published_course.approval_status = (
            Course.ApprovalStatus.PUBLISHED
        )
        published_course.save()

        self.authenticate(self.student)

        response = self.client.get(self.course_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = self.get_response_ids(response)

        self.assertIn(published_course.id, returned_ids)
        self.assertNotIn(self.course.id, returned_ids)

    def test_teacher_can_create_course_as_draft(self):
        self.authenticate(self.teacher)

        response = self.client.post(
            self.course_url,
            self.create_course_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        created_course = Course.objects.get(
            code="API-ICT-002",
        )

        self.assertEqual(
            created_course.created_by,
            self.teacher,
        )

        self.assertEqual(
            created_course.approval_status,
            Course.ApprovalStatus.DRAFT,
        )

    def test_student_cannot_create_course(self):
        self.authenticate(self.student)

        response = self.client.post(
            self.course_url,
            self.create_course_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_teacher_can_update_own_draft_course(self):
        self.authenticate(self.teacher)

        response = self.client.patch(
            f"{self.course_url}{self.course.id}/",
            {"title": "Updated ICT Course"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.title,
            "Updated ICT Course",
        )

    def test_teacher_cannot_update_another_teachers_course(self):
        another_course = self.create_course(
            self.another_teacher,
            code="API-ICT-005",
        )

        self.authenticate(self.teacher)

        response = self.client.patch(
            f"{self.course_url}{another_course.id}/",
            {"title": "Unauthorized Update"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_teacher_can_submit_own_course_through_api(self):
        self.authenticate(self.teacher)

        response = self.client.post(
            f"{self.course_url}{self.course.id}/submit/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.PENDING,
        )

    def test_teacher_cannot_approve_course_through_api(self):
        submit_course(self.course.id, self.teacher)

        self.authenticate(self.teacher)

        response = self.client.post(
            f"{self.course_url}{self.course.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_can_approve_pending_course_through_api(self):
        submit_course(self.course.id, self.teacher)

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.course_url}{self.course.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.APPROVED,
        )

    def test_admin_can_reject_course_through_api(self):
        submit_course(self.course.id, self.teacher)

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.course_url}{self.course.id}/reject/",
            {
                "reason": "Please improve the course description.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.course.refresh_from_db()

        self.assertEqual(
            self.course.approval_status,
            Course.ApprovalStatus.REJECTED,
        )

    def test_teacher_can_view_own_course_history(self):
        submit_course(self.course.id, self.teacher)

        self.authenticate(self.teacher)

        response = self.client.get(
            f"{self.course_url}{self.course.id}/history/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )


class CoursePublishingValidationTests(AcademicsTestDataMixin, TestCase):
    """
    Tests for course publishing validation.
    """

    def setUp(self):

        self.teacher = self.create_user(
            "publishtestteacher",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "publishtestadmin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2031,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Technology",
            code="PUBTECH",
            is_active=True,
        )

        self.other_stream = Stream.objects.create(
            name="Science",
            code="PUBSCI",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Information and Communication Technology",
            code="PUBICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course(
            self.teacher,
            code="PUB-ICT-001",
        )

        self.course.approval_status = (
            Course.ApprovalStatus.APPROVED
        )

        self.course.reviewed_by = self.admin

        self.course.save()

    def test_inactive_course_cannot_be_published(self):

        self.course.is_active = False
        self.course.save()

        with self.assertRaises(DjangoValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )

    def test_inactive_academic_year_prevents_publishing(self):

        self.academic_year.is_active = False
        self.academic_year.save()

        with self.assertRaises(DjangoValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )

    def test_inactive_stream_prevents_publishing(self):

        self.stream.is_active = False
        self.stream.save()

        with self.assertRaises(DjangoValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )

    def test_inactive_subject_prevents_publishing(self):

        self.subject.is_active = False
        self.subject.save()

        with self.assertRaises(DjangoValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )

    def test_subject_stream_mismatch_prevents_publishing(self):

        self.subject.streams.remove(self.stream)

        self.subject.streams.add(self.other_stream)

        with self.assertRaises(DjangoValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )


class EnrollmentRequestAPITests(AcademicsTestDataMixin, TestCase):
    """
    API tests for student enrollment requests and admin reviews.
    """

    def setUp(self):
        self.client = APIClient()

        self.teacher = self.create_user(
            "enrollment_teacher",
            User.Role.TEACHER,
        )

        self.other_teacher = self.create_user(
            "enrollment_teacher2",
            User.Role.TEACHER,
        )

        self.student = self.create_user(
            "enrollment_student",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "enrollment_student2",
            User.Role.STUDENT,
        )

        self.admin = self.create_user(
            "enrollment_admin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.system_admin = self.create_user(
            "enrollment_sysadmin",
            User.Role.SYSTEM_ADMIN,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2040,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Enrollment Technology",
            code="ENRTECH",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Enrollment ICT",
            code="ENRICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course(
            self.teacher,
            code="ENR-ICT-001",
        )

        self.course.approval_status = Course.ApprovalStatus.PUBLISHED
        self.course.enrollment_method = Course.EnrollmentMethod.APPROVAL
        self.course.save()

        self.url = (
            "/api/academics/enrollment-requests/"
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_published_approval_course(
        self,
        creator,
        code,
        price=Decimal("1500.00"),
    ):
        course = self.create_course(
            creator,
            code=code,
        )

        course.price = price
        course.approval_status = Course.ApprovalStatus.PUBLISHED
        course.enrollment_method = Course.EnrollmentMethod.APPROVAL
        course.save()

        return course

    def create_request(self, course=None, student=None):
        return EnrollmentRequest.objects.create(
            course=course or self.course,
            student=student or self.student,
        )

    def test_student_can_create_enrollment_request(self):
        self.authenticate(self.student)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
                "student_message": "I want to join this course.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertTrue(
            EnrollmentRequest.objects.filter(
                course=self.course,
                student=self.student,
                status=EnrollmentRequest.Status.PENDING,
            ).exists()
        )

    def test_non_student_cannot_create_enrollment_request(self):
        self.authenticate(self.teacher)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_student_cannot_request_non_approval_course(self):
        self.course.enrollment_method = Course.EnrollmentMethod.OPEN
        self.course.save()

        self.authenticate(self.student)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_student_cannot_request_unpublished_course(self):
        self.course.approval_status = Course.ApprovalStatus.DRAFT
        self.course.save()

        self.authenticate(self.student)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_student_cannot_create_duplicate_pending_request(self):
        self.create_request()

        self.authenticate(self.student)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            EnrollmentRequest.objects.filter(
                course=self.course,
                student=self.student,
                status=EnrollmentRequest.Status.PENDING,
            ).count(),
            1,
        )

    def test_student_can_only_list_own_requests(self):
        another_course = self.create_published_approval_course(
            self.teacher,
            "ENR-ICT-002",
        )

        own_request = self.create_request()

        other_request = self.create_request(
            course=another_course,
            student=self.other_student,
        )

        self.authenticate(self.student)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = [
            item["id"] for item in response.data
        ]

        self.assertIn(own_request.id, returned_ids)
        self.assertNotIn(other_request.id, returned_ids)

    def test_student_cannot_view_another_students_request(self):
        enrollment_request = self.create_request(
            student=self.other_student,
        )

        self.authenticate(self.student)

        response = self.client.get(
            f"{self.url}{enrollment_request.id}/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_teacher_cannot_approve_enrollment_request(self):
        enrollment_request = self.create_request()

        self.authenticate(self.teacher)

        response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_can_approve_paid_course_request(self):
        enrollment_request = self.create_request()

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {
                "remarks": "Approved.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        enrollment_request.refresh_from_db()

        self.assertEqual(
            enrollment_request.status,
            EnrollmentRequest.Status.APPROVED,
        )

        enrollment = CourseEnrollment.objects.get(
            course=self.course,
            student=self.student,
        )

        self.assertEqual(
            enrollment.status,
            CourseEnrollment.Status.PENDING,
        )

        self.assertIsNone(enrollment.activated_at)

    def test_admin_approval_activates_free_course(self):
        free_course = self.create_published_approval_course(
            self.teacher,
            "ENR-FREE-001",
            price=Decimal("0.00"),
        )

        enrollment_request = self.create_request(
            course=free_course,
        )

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        enrollment = CourseEnrollment.objects.get(
            course=free_course,
            student=self.student,
        )

        self.assertEqual(
            enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

        self.assertIsNotNone(enrollment.activated_at)

    def test_admin_can_reject_enrollment_request(self):
        enrollment_request = self.create_request()

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.url}{enrollment_request.id}/reject/",
            {
                "remarks": "Please contact the institute.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        enrollment_request.refresh_from_db()

        self.assertEqual(
            enrollment_request.status,
            EnrollmentRequest.Status.REJECTED,
        )

        self.assertEqual(
            enrollment_request.admin_remarks,
            "Please contact the institute.",
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.student,
            ).exists()
        )

    def test_system_admin_can_approve_enrollment_request(self):
        enrollment_request = self.create_request()

        self.authenticate(self.system_admin)

        response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        enrollment_request.refresh_from_db()

        self.assertEqual(
            enrollment_request.status,
            EnrollmentRequest.Status.APPROVED,
        )

    def test_already_reviewed_request_cannot_be_approved_again(self):
        enrollment_request = self.create_request()

        self.authenticate(self.admin)

        first_response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        second_response = self.client.post(
            f"{self.url}{enrollment_request.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_teacher_can_only_list_requests_for_own_courses(self):
        another_course = self.create_published_approval_course(
            self.other_teacher,
            "ENR-ICT-003",
        )

        own_request = self.create_request()
        other_request = self.create_request(
            course=another_course,
            student=self.other_student,
        )

        self.authenticate(self.teacher)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = [item["id"] for item in response.data]

        self.assertIn(own_request.id, returned_ids)
        self.assertNotIn(other_request.id, returned_ids)

    def test_teacher_cannot_view_another_teachers_request(self):
        another_course = self.create_published_approval_course(
            self.other_teacher,
            "ENR-ICT-004",
        )

        other_request = self.create_request(
            course=another_course,
            student=self.other_student,
        )

        self.authenticate(self.teacher)

        response = self.client.get(
            f"{self.url}{other_request.id}/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_user_cannot_list_enrollment_requests(self):
        response = self.client.get(self.url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )


class CourseInvitationAPITests(AcademicsTestDataMixin, TestCase):
    """
    API tests for course invitations.
    """

    def setUp(self):
        self.client = APIClient()

        self.teacher = self.create_user(
            "invitation_teacher",
            User.Role.TEACHER,
        )

        self.other_teacher = self.create_user(
            "invitation_teacher2",
            User.Role.TEACHER,
        )

        self.student = self.create_user(
            "invitation_student",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "invitation_student2",
            User.Role.STUDENT,
        )

        self.admin = self.create_user(
            "invitation_admin",
            User.Role.INSTITUTE_ADMIN,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2041,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Invitation Technology",
            code="INVTECH",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Invitation ICT",
            code="INVICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_published_invitation_course(
            self.teacher,
            "INV-ICT-001",
        )

        self.url = "/api/academics/course-invitations/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_published_invitation_course(
        self,
        creator,
        code,
        price=Decimal("1500.00"),
    ):
        course = self.create_course(
            creator,
            code=code,
        )

        course.price = price
        course.approval_status = Course.ApprovalStatus.PUBLISHED
        course.enrollment_method = Course.EnrollmentMethod.INVITATION
        course.save()

        return course

    def create_invitation(
        self,
        course=None,
        student=None,
        invited_by=None,
        expires_at=None,
    ):
        student = student or self.student

        return CourseInvitation.objects.create(
            course=course or self.course,
            invited_user=student,
            invited_email=student.email,
            invited_by=invited_by or self.teacher,
            expires_at=expires_at or (
                timezone.now() + timedelta(days=7)
            ),
        )

    def test_teacher_can_create_course_invitation(self):
        self.authenticate(self.teacher)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
                "invited_email": self.student.email,
                "expires_at": (
                    timezone.now() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.assertTrue(
            CourseInvitation.objects.filter(
                course=self.course,
                invited_email=self.student.email,
                status=CourseInvitation.Status.PENDING,
            ).exists()
        )

    def test_student_cannot_create_invitation(self):
        self.authenticate(self.student)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
                "invited_email": self.other_student.email,
                "expires_at": (
                    timezone.now() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_teacher_cannot_invite_to_another_teachers_course(self):
        other_course = self.create_published_invitation_course(
            self.other_teacher,
            "INV-ICT-002",
        )

        self.authenticate(self.teacher)

        response = self.client.post(
            self.url,
            {
                "course": other_course.id,
                "invited_email": self.student.email,
                "expires_at": (
                    timezone.now() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_student_can_accept_paid_course_invitation(self):
        invitation = self.create_invitation()

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.ACCEPTED,
        )

        enrollment = CourseEnrollment.objects.get(
            course=self.course,
            student=self.student,
        )

        self.assertEqual(
            enrollment.status,
            CourseEnrollment.Status.PENDING,
        )

        self.assertIsNone(enrollment.activated_at)

    def test_student_can_accept_free_course_invitation(self):
        free_course = self.create_published_invitation_course(
            self.teacher,
            "INV-FREE-001",
            price=Decimal("0.00"),
        )

        invitation = self.create_invitation(
            course=free_course,
        )

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        enrollment = CourseEnrollment.objects.get(
            course=free_course,
            student=self.student,
        )

        self.assertEqual(
            enrollment.status,
            CourseEnrollment.Status.ACTIVE,
        )

        self.assertIsNotNone(enrollment.activated_at)

    def test_student_can_decline_invitation(self):
        invitation = self.create_invitation()

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/decline/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.DECLINED,
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.student,
            ).exists()
        )

    def test_expired_invitation_cannot_be_accepted(self):
        invitation = self.create_invitation(
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.EXPIRED,
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.student,
            ).exists()
        )

    def test_student_cannot_accept_another_students_invitation(self):
        invitation = self.create_invitation(
            student=self.other_student,
        )

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_teacher_can_revoke_own_invitation(self):
        invitation = self.create_invitation()

        self.authenticate(self.teacher)

        response = self.client.post(
            f"{self.url}{invitation.id}/revoke/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.REVOKED,
        )

    def test_admin_can_revoke_invitation(self):
        invitation = self.create_invitation()

        self.authenticate(self.admin)

        response = self.client.post(
            f"{self.url}{invitation.id}/revoke/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.REVOKED,
        )

    def test_teacher_cannot_view_another_teachers_invitation(self):
        another_course = self.create_published_invitation_course(
            self.other_teacher,
            "INV-ICT-003",
        )

        invitation = self.create_invitation(
            course=another_course,
            invited_by=self.other_teacher,
        )

        self.authenticate(self.teacher)

        response = self.client.get(
            f"{self.url}{invitation.id}/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_teacher_cannot_revoke_invitation_sent_by_another_inviter(self):
        invitation = self.create_invitation(
            invited_by=self.other_teacher,
        )

        self.authenticate(self.teacher)

        response = self.client.post(
            f"{self.url}{invitation.id}/revoke/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.PENDING,
        )

    def test_duplicate_pending_invitation_is_rejected(self):
        self.create_invitation()

        self.authenticate(self.teacher)

        response = self.client.post(
            self.url,
            {
                "course": self.course.id,
                "invited_email": self.student.email,
                "expires_at": (
                    timezone.now() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            CourseInvitation.objects.filter(
                course=self.course,
                invited_email=self.student.email,
                status=CourseInvitation.Status.PENDING,
            ).count(),
            1,
        )

    def test_invitation_cannot_be_accepted_twice(self):
        invitation = self.create_invitation()

        self.authenticate(self.student)

        first_response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        second_response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
