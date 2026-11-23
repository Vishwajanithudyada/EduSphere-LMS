
from decimal import Decimal

from rest_framework import serializers

from .models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseApprovalLog,
    CourseModule,
    Lesson,
)


class AcademicYearSerializer(serializers.ModelSerializer):

    class Meta:
        model = AcademicYear
        fields = [
            "id",
            "year",
            "is_active",
        ]


class StreamSerializer(serializers.ModelSerializer):

    class Meta:
        model = Stream
        fields = [
            "id",
            "name",
            "code",
            "description",
            "is_active",
        ]


class SubjectSerializer(serializers.ModelSerializer):

    streams = StreamSerializer(
        many=True,
        read_only=True,
    )

    stream_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Stream.objects.filter(is_active=True),
        source="streams",
        write_only=True,
    )

    class Meta:
        model = Subject
        fields = [
            "id",
            "name",
            "code",
            "streams",
            "stream_ids",
            "description",
            "is_active",
        ]


class CourseSerializer(serializers.ModelSerializer):

    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.filter(is_active=True),
    )

    stream = serializers.PrimaryKeyRelatedField(
        queryset=Stream.objects.filter(is_active=True),
    )

    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.filter(is_active=True),
    )

    academic_year_details = AcademicYearSerializer(
        source="academic_year",
        read_only=True,
    )

    stream_details = StreamSerializer(
        source="stream",
        read_only=True,
    )

    subject_details = SubjectSerializer(
        source="subject",
        read_only=True,
    )

    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
    )

    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username",
        read_only=True,
        allow_null=True,
    )

    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
    )

    class Meta:
        model = Course

        fields = [
            "id",
            "code",
            "title",
            "academic_year",
            "academic_year_details",
            "stream",
            "stream_details",
            "subject",
            "subject_details",
            "course_type",
            "delivery_mode",
            "description",
            "price",
            "approval_status",
            "enrollment_method",
            "access_policy",
            "created_by",
            "created_by_username",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_at",
            "rejection_reason",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "approval_status",
            "created_by",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):

        stream = attrs.get(
            "stream",
            getattr(self.instance, "stream", None),
        )

        subject = attrs.get(
            "subject",
            getattr(self.instance, "subject", None),
        )

        if stream and subject:
            if not subject.streams.filter(
                pk=stream.pk,
                is_active=True,
            ).exists():
                raise serializers.ValidationError({
                    "subject": (
                        "This subject is not assigned "
                        "to the selected active stream."
                    )
                })

        return attrs


class CourseModuleSerializer(serializers.ModelSerializer):

    class Meta:
        model = CourseModule
        fields = [
            "id",
            "course",
            "title",
            "description",
            "order",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class LessonSerializer(serializers.ModelSerializer):

    content = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    video_url = serializers.URLField(
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = Lesson
        fields = [
            "id",
            "module",
            "title",
            "description",
            "content",
            "video_url",
            "billing_period_start",
            "billing_period_end",
            "order",
            "is_published",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):

        module = attrs.get(
            "module",
            getattr(self.instance, "module", None),
        )

        if module is None:
            return attrs

        course = module.course

        start = attrs.get(
            "billing_period_start",
            getattr(self.instance, "billing_period_start", None),
        )

        end = attrs.get(
            "billing_period_end",
            getattr(self.instance, "billing_period_end", None),
        )

        if course.access_policy == Course.AccessPolicy.MONTHLY:

            if not start or not end:
                raise serializers.ValidationError({
                    "billing_period_start": (
                        "Monthly course lessons require "
                        "a billing period start and end."
                    )
                })

            if end <= start:
                raise serializers.ValidationError({
                    "billing_period_end": (
                        "Billing period end must be after start."
                    )
                })

        elif start or end:

            raise serializers.ValidationError({
                "billing_period_start": (
                    "Completion-based course lessons "
                    "cannot have billing periods."
                )
            })

        return attrs


class ApproveCourseSerializer(serializers.Serializer):

    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        trim_whitespace=True,
    )


class RejectCourseSerializer(serializers.Serializer):

    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=2000,
        trim_whitespace=True,
    )


class PublishCourseSerializer(serializers.Serializer):

    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        trim_whitespace=True,
    )


class CourseApprovalLogSerializer(serializers.ModelSerializer):

    performed_by_username = serializers.CharField(
        source="performed_by.username",
        read_only=True,
    )

    action_display = serializers.CharField(
        source="get_action_display",
        read_only=True,
    )

    class Meta:
        model = CourseApprovalLog

        fields = [
            "id",
            "action",
            "action_display",
            "performed_by",
            "performed_by_username",
            "remarks",
            "created_at",
        ]

        read_only_fields = fields
