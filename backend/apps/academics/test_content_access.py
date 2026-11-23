
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.academics.models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseEnrollment,
    EnrollmentPayment,
    CourseModule,
    Lesson,
)


class ContentAccessSecurityTests(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.teacher = self.create_user(
            "content_teacher",
            User.Role.TEACHER,
        )
        self.student = self.create_user(
            "content_student",
            User.Role.STUDENT,
        )
        self.other_teacher = self.create_user(
            "other_content_teacher",
            User.Role.TEACHER,
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
            name="ICT",
            code="ICT",
            description="ICT subject",
            is_active=True,
        )
        self.subject.streams.add(self.stream)

        self.course = Course.objects.create(
            code="CONTENT-001",
            title="Content Security Course",
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

        self.module = CourseModule.objects.create(
            course=self.course,
            title="Introduction",
            description="Introduction module",
            order=1,
            is_active=True,
        )

        self.lesson = Lesson.objects.create(
            module=self.module,
            title="Monthly Lesson",
            description="Test lesson",
            content="CONFIDENTIAL LESSON CONTENT",
            video_url="https://example.com/lesson-video",
            billing_period_start=date(2029, 1, 1),
            billing_period_end=date(2029, 1, 31),
            order=1,
            is_published=True,
        )

        self.enrollment = CourseEnrollment.objects.create(
            course=self.course,
            student=self.student,
            status=CourseEnrollment.Status.ACTIVE,
        )

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_monthly_payment(
        self,
        start=date(2029, 1, 1),
        end=date(2029, 1, 31),
        status=EnrollmentPayment.Status.PAID,
    ):
        return EnrollmentPayment.objects.create(
            enrollment=self.enrollment,
            payment_type=EnrollmentPayment.PaymentType.MONTHLY,
            amount=Decimal("1500.00"),
            currency="LKR",
            billing_period_start=start,
            billing_period_end=end,
            status=status,
        )

    def test_unpaid_student_cannot_receive_lesson_content(self):
        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)

        lesson_data = response.data[0]

        self.assertEqual(lesson_data["content"], "")
        self.assertEqual(lesson_data["video_url"], "")
        self.assertTrue(lesson_data["is_locked"])

    def test_paid_monthly_student_can_access_matching_period(self):
        self.create_monthly_payment()
        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)

        lesson_data = response.data[0]

        self.assertEqual(
            lesson_data["content"],
            "CONFIDENTIAL LESSON CONTENT",
        )
        self.assertEqual(
            lesson_data["video_url"],
            "https://example.com/lesson-video",
        )
        self.assertFalse(lesson_data["is_locked"])

    def test_payment_for_different_period_does_not_unlock_lesson(self):
        self.create_monthly_payment(
            start=date(2029, 2, 1),
            end=date(2029, 2, 28),
        )
        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)

        lesson_data = response.data[0]

        self.assertEqual(lesson_data["content"], "")
        self.assertEqual(lesson_data["video_url"], "")
        self.assertTrue(lesson_data["is_locked"])

    def test_refunded_payment_does_not_unlock_lesson(self):
        self.create_monthly_payment(
            status=EnrollmentPayment.Status.REFUNDED,
        )
        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)

        lesson_data = response.data[0]

        self.assertEqual(lesson_data["content"], "")
        self.assertTrue(lesson_data["is_locked"])

    def test_student_without_active_enrollment_cannot_list_lessons(self):
        self.enrollment.status = CourseEnrollment.Status.SUSPENDED
        self.enrollment.save(update_fields=["status"])

        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_student_cannot_create_module(self):
        self.authenticate(self.student)

        response = self.client.post(
            "/api/academics/modules/",
            {
                "course": self.course.id,
                "title": "Unauthorized Module",
                "description": "Should not be created",
                "order": 2,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CourseModule.objects.filter(
                title="Unauthorized Module"
            ).exists()
        )

    def test_teacher_cannot_create_module_for_another_teacher(self):
        other_course = Course.objects.create(
            code="CONTENT-002",
            title="Other Teacher Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            price=Decimal("1500.00"),
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            approval_status=Course.ApprovalStatus.PUBLISHED,
            is_active=True,
            created_by=self.other_teacher,
        )

        self.authenticate(self.teacher)

        response = self.client.post(
            "/api/academics/modules/",
            {
                "course": other_course.id,
                "title": "Unauthorized Module",
                "description": "",
                "order": 1,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CourseModule.objects.filter(
                course=other_course,
                title="Unauthorized Module",
            ).exists()
        )

    def test_completion_course_requires_paid_one_time_payment(self):
        completion_course = Course.objects.create(
            code="CONTENT-003",
            title="Completion Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            price=Decimal("5000.00"),
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.COMPLETION,
            approval_status=Course.ApprovalStatus.PUBLISHED,
            is_active=True,
            created_by=self.teacher,
        )

        completion_module = CourseModule.objects.create(
            course=completion_course,
            title="Completion Module",
            order=1,
            is_active=True,
        )

        completion_lesson = Lesson.objects.create(
            module=completion_module,
            title="Completion Lesson",
            content="COMPLETION COURSE CONTENT",
            video_url="https://example.com/completion-video",
            order=1,
            is_published=True,
        )

        completion_enrollment = CourseEnrollment.objects.create(
            course=completion_course,
            student=self.student,
            status=CourseEnrollment.Status.ACTIVE,
        )

        self.authenticate(self.student)

        response = self.client.get("/api/academics/lessons/")

        self.assertEqual(response.status_code, 200)

        lesson_data = next(
            item for item in response.data
            if item["id"] == completion_lesson.id
        )

        self.assertEqual(lesson_data["content"], "")
        self.assertTrue(lesson_data["is_locked"])

        EnrollmentPayment.objects.create(
            enrollment=completion_enrollment,
            payment_type=EnrollmentPayment.PaymentType.ONE_TIME,
            amount=Decimal("5000.00"),
            currency="LKR",
            status=EnrollmentPayment.Status.PAID,
        )

        response = self.client.get("/api/academics/lessons/")

        lesson_data = next(
            item for item in response.data
            if item["id"] == completion_lesson.id
        )

        self.assertEqual(
            lesson_data["content"],
            "COMPLETION COURSE CONTENT",
        )
        self.assertFalse(lesson_data["is_locked"])
