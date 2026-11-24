
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.academics.models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseInvitation,
    CourseEnrollment,
)

from apps.academics.tests import AcademicsTestDataMixin


class CourseInvitationSecurityTests(AcademicsTestDataMixin, TestCase):

    def setUp(self):
        self.client = APIClient()

        self.teacher = self.create_user(
            "security_teacher",
            User.Role.TEACHER,
        )

        self.student = self.create_user(
            "security_student",
            User.Role.STUDENT,
        )

        self.other_student = self.create_user(
            "security_student2",
            User.Role.STUDENT,
        )

        self.academic_year = AcademicYear.objects.create(
            year=2042,
            is_active=True,
        )

        self.stream = Stream.objects.create(
            name="Security Technology",
            code="SECTECH",
            is_active=True,
        )

        self.subject = Subject.objects.create(
            name="Security ICT",
            code="SEC-ICT",
            is_active=True,
        )

        self.subject.streams.add(self.stream)

        self.course = self.create_course(
            self.teacher,
            code="SEC-INV-001",
        )

        self.course.price = Decimal("1500.00")
        self.course.approval_status = Course.ApprovalStatus.PUBLISHED
        self.course.enrollment_method = (
            Course.EnrollmentMethod.INVITATION
        )
        self.course.save()

        self.url = "/api/academics/course-invitations/"

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_unregistered_invitation(self):
        return CourseInvitation.objects.create(
            course=self.course,
            invited_user=None,
            invited_email=self.student.email,
            invited_by=self.teacher,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_registered_invitation_cannot_be_used_by_another_account(self):
        invitation = CourseInvitation.objects.create(
            course=self.course,
            invited_user=self.student,
            invited_email=self.student.email,
            invited_by=self.teacher,
            expires_at=timezone.now() + timedelta(days=7),
        )

        self.other_student.email = self.student.email
        self.other_student.save(update_fields=["email"])

        self.authenticate(self.other_student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.other_student,
            ).exists()
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.PENDING,
        )

    def test_unregistered_email_invitation_requires_verified_email(self):
        invitation = self.create_unregistered_invitation()

        self.student.is_email_verified = False
        self.student.save(update_fields=["is_email_verified"])

        self.authenticate(self.student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
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

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.student,
            ).exists()
        )

    def test_unregistered_invitation_is_hidden_from_other_students(self):
        invitation = self.create_unregistered_invitation()

        self.authenticate(self.other_student)

        response = self.client.get(
            f"{self.url}{invitation.id}/"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_registered_invitation_cannot_be_accepted_by_another_student(self):
        invitation = CourseInvitation.objects.create(
            course=self.course,
            invited_user=self.student,
            invited_email=self.student.email,
            invited_by=self.teacher,
            expires_at=timezone.now() + timedelta(days=7),
        )

        self.authenticate(self.other_student)

        response = self.client.post(
            f"{self.url}{invitation.id}/accept/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.other_student,
            ).exists()
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.PENDING,
        )

    def test_expired_invitation_cannot_be_accepted(self):
        invitation = CourseInvitation.objects.create(
            course=self.course,
            invited_user=self.student,
            invited_email=self.student.email,
            invited_by=self.teacher,
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

        self.assertFalse(
            CourseEnrollment.objects.filter(
                course=self.course,
                student=self.student,
            ).exists()
        )

        invitation.refresh_from_db()

        self.assertEqual(
            invitation.status,
            CourseInvitation.Status.EXPIRED,
        )
