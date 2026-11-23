
from rest_framework import serializers

from apps.accounts.models import User

from .models import (
    Course,
    EnrollmentRequest,
    CourseEnrollment,
    CourseInvitation,
)


class EnrollmentRequestCreateSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.filter(
            approval_status=Course.ApprovalStatus.PUBLISHED,
            is_active=True,
        )
    )

    class Meta:
        model = EnrollmentRequest
        fields = [
            "id",
            "course",
            "student_message",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
        ]

    def validate_course(self, course):
        if course.enrollment_method != Course.EnrollmentMethod.APPROVAL:
            raise serializers.ValidationError(
                "This course does not require an enrollment approval request."
            )
        return course

    def validate(self, attrs):
        request = self.context.get("request")
        course = attrs["course"]

        if request is None or not request.user.is_authenticated:
            raise serializers.ValidationError(
                "Authentication is required."
            )

        if EnrollmentRequest.objects.filter(
            course=course,
            student=request.user,
            status=EnrollmentRequest.Status.PENDING,
        ).exists():
            raise serializers.ValidationError({
                "course": "You already have a pending request for this course."
            })

        if CourseEnrollment.objects.filter(
            course=course,
            student=request.user,
        ).exists():
            raise serializers.ValidationError({
                "course": "You already have an enrollment record for this course."
            })

        return attrs


class EnrollmentRequestSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(
        source="course.title",
        read_only=True,
    )
    student_username = serializers.CharField(
        source="student.username",
        read_only=True,
    )
    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username",
        read_only=True,
        allow_null=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = EnrollmentRequest
        fields = [
            "id",
            "course",
            "course_title",
            "student",
            "student_username",
            "status",
            "status_display",
            "student_message",
            "admin_remarks",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReviewEnrollmentRequestSerializer(serializers.Serializer):
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        trim_whitespace=True,
    )


# --------------------------------------------------
# COURSE INVITATION SERIALIZERS
# --------------------------------------------------

class CourseInvitationCreateSerializer(serializers.ModelSerializer):
    course = serializers.PrimaryKeyRelatedField(
        queryset=Course.objects.filter(
            approval_status=Course.ApprovalStatus.PUBLISHED,
            is_active=True,
        )
    )

    invited_email = serializers.EmailField()

    class Meta:
        model = CourseInvitation
        fields = [
            "id",
            "course",
            "invited_email",
            "expires_at",
        ]

    def validate_course(self, course):
        if course.enrollment_method != Course.EnrollmentMethod.INVITATION:
            raise serializers.ValidationError(
                "This course does not use invitation-based enrollment."
            )
        return course

    def validate_invited_email(self, email):
        email = email.strip().lower()

        existing_user = User.objects.filter(
            email__iexact=email,
        ).first()

        if existing_user and existing_user.role != User.Role.STUDENT:
            raise serializers.ValidationError(
                "Invitations can only be sent to student accounts."
            )

        return email

    def validate_expires_at(self, value):
        from django.utils import timezone

        if value <= timezone.now():
            raise serializers.ValidationError(
                "Invitation expiry must be in the future."
            )
        return value

    def validate(self, attrs):
        course = attrs["course"]
        email = attrs["invited_email"]

        if CourseInvitation.objects.filter(
            course=course,
            invited_email__iexact=email,
            status=CourseInvitation.Status.PENDING,
        ).exists():
            raise serializers.ValidationError({
                "invited_email": (
                    "A pending invitation already exists for this email."
                )
            })

        existing_user = User.objects.filter(
            email__iexact=email,
            role=User.Role.STUDENT,
        ).first()

        if existing_user and CourseEnrollment.objects.filter(
            course=course,
            student=existing_user,
        ).exists():
            raise serializers.ValidationError({
                "invited_email": (
                    "This student already has an enrollment record "
                    "for this course."
                )
            })

        return attrs


class CourseInvitationSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(
        source="course.title",
        read_only=True,
    )

    invited_by_username = serializers.CharField(
        source="invited_by.username",
        read_only=True,
    )

    invited_user_username = serializers.CharField(
        source="invited_user.username",
        read_only=True,
        allow_null=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = CourseInvitation
        fields = [
            "id",
            "course",
            "course_title",
            "invited_user",
            "invited_user_username",
            "invited_email",
            "token",
            "status",
            "status_display",
            "invited_by",
            "invited_by_username",
            "expires_at",
            "accepted_at",
            "created_at",
        ]
        read_only_fields = fields
