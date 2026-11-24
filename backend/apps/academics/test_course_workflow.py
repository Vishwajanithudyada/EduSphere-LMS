
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.academics.models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseApprovalLog,
)
from apps.academics.services.course_workflow import (
    submit_course,
    approve_course,
    reject_course,
    publish_course,
)


class CourseWorkflowTests(TestCase):

    def setUp(self):
        self.teacher = self.create_user(
            "workflow_teacher",
            User.Role.TEACHER,
        )

        self.other_teacher = self.create_user(
            "workflow_other_teacher",
            User.Role.TEACHER,
        )

        self.admin = self.create_user(
            "workflow_admin",
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
            name="Information Technology",
            code="IT",
            description="IT subject",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course()

    def create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
            role=role,
        )

    def create_course(self, status=Course.ApprovalStatus.DRAFT):
        return Course.objects.create(
            code=f"WF-{status}",
            title="Workflow Test Course",
            academic_year=self.academic_year,
            stream=self.stream,
            subject=self.subject,
            course_type=Course.CourseType.THEORY,
            delivery_mode=Course.DeliveryMode.ONLINE,
            description="Workflow test description",
            price=Decimal("1500.00"),
            approval_status=status,
            enrollment_method=Course.EnrollmentMethod.PAID,
            access_policy=Course.AccessPolicy.MONTHLY,
            created_by=self.teacher,
            is_active=True,
        )

    def test_teacher_can_submit_own_draft_course(self):
        course = submit_course(
            self.course.id,
            self.teacher,
        )

        self.assertEqual(
            course.approval_status,
            Course.ApprovalStatus.PENDING,
        )

        self.assertTrue(
            CourseApprovalLog.objects.filter(
                course=course,
                action=CourseApprovalLog.Action.SUBMITTED,
                performed_by=self.teacher,
            ).exists()
        )

    def test_teacher_cannot_submit_another_teachers_course(self):
        with self.assertRaises(PermissionDenied):
            submit_course(
                self.course.id,
                self.other_teacher,
            )

    def test_admin_can_approve_pending_course(self):
        submit_course(self.course.id, self.teacher)

        course = approve_course(
            self.course.id,
            self.admin,
            remarks="Approved for testing.",
        )

        self.assertEqual(
            course.approval_status,
            Course.ApprovalStatus.APPROVED,
        )

        self.assertEqual(
            course.reviewed_by,
            self.admin,
        )

        self.assertTrue(
            CourseApprovalLog.objects.filter(
                course=course,
                action=CourseApprovalLog.Action.APPROVED,
            ).exists()
        )

    def test_teacher_cannot_approve_course(self):
        submit_course(self.course.id, self.teacher)

        with self.assertRaises(PermissionDenied):
            approve_course(
                self.course.id,
                self.teacher,
            )

    def test_creator_cannot_approve_own_course(self):
        submit_course(self.course.id, self.teacher)

        with self.assertRaises(PermissionDenied):
            approve_course(
                self.course.id,
                self.teacher,
            )

    def test_admin_can_reject_pending_course(self):
        submit_course(self.course.id, self.teacher)

        course = reject_course(
            self.course.id,
            self.admin,
            "Insufficient course details.",
        )

        self.assertEqual(
            course.approval_status,
            Course.ApprovalStatus.REJECTED,
        )

        self.assertEqual(
            course.rejection_reason,
            "Insufficient course details.",
        )

    def test_rejection_requires_reason(self):
        submit_course(self.course.id, self.teacher)

        with self.assertRaises(ValidationError):
            reject_course(
                self.course.id,
                self.admin,
                "   ",
            )

    def test_only_approved_course_can_be_published(self):
        with self.assertRaises(ValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )

    def test_admin_can_publish_approved_course(self):
        submit_course(self.course.id, self.teacher)
        approve_course(self.course.id, self.admin)

        course = publish_course(
            self.course.id,
            self.admin,
            remarks="Published for testing.",
        )

        self.assertEqual(
            course.approval_status,
            Course.ApprovalStatus.PUBLISHED,
        )

        self.assertTrue(
            CourseApprovalLog.objects.filter(
                course=course,
                action=CourseApprovalLog.Action.PUBLISHED,
            ).exists()
        )

    def test_inactive_course_cannot_be_published(self):
        submit_course(self.course.id, self.teacher)
        approve_course(self.course.id, self.admin)

        self.course.refresh_from_db()
        self.course.is_active = False
        self.course.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            publish_course(
                self.course.id,
                self.admin,
            )
