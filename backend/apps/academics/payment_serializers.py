
from decimal import Decimal

from rest_framework import serializers

from .models import (
    CourseEnrollment,
    EnrollmentPayment,
    PaymentAttempt,
    PaymentRefund,
)


class PaymentAttemptReadSerializer(serializers.ModelSerializer):

    class Meta:
        model = PaymentAttempt

        fields = [
            "id",
            "provider",
            "transaction_id",
            "idempotency_key",
            "amount",
            "currency",
            "status",
            "failure_code",
            "failure_message",
            "initiated_at",
            "completed_at",
            "updated_at",
        ]

        read_only_fields = fields


class PaymentRefundReadSerializer(serializers.ModelSerializer):

    requested_by_username = serializers.CharField(
        source="requested_by.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = PaymentRefund

        fields = [
            "id",
            "amount",
            "currency",
            "status",
            "refund_reference",
            "reason",
            "requested_by",
            "requested_by_username",
            "created_at",
            "completed_at",
        ]

        read_only_fields = fields


class PaymentObligationCreateSerializer(serializers.Serializer):

    enrollment = serializers.PrimaryKeyRelatedField(
        queryset=CourseEnrollment.objects.all(),
    )

    billing_period_start = serializers.DateField(
        required=False,
        allow_null=True,
    )

    billing_period_end = serializers.DateField(
        required=False,
        allow_null=True,
    )

    currency = serializers.CharField(
        max_length=3,
        required=False,
        default="LKR",
    )

    def validate_currency(self, value):

        value = value.strip().upper()

        if len(value) != 3:
            raise serializers.ValidationError(
                "Currency must contain exactly three characters."
            )

        return value


class PaymentObligationReadSerializer(serializers.ModelSerializer):

    course_id = serializers.IntegerField(
        source="enrollment.course_id",
        read_only=True,
    )

    course_title = serializers.CharField(
        source="enrollment.course.title",
        read_only=True,
    )

    student_id = serializers.IntegerField(
        source="enrollment.student_id",
        read_only=True,
    )

    student_username = serializers.CharField(
        source="enrollment.student.username",
        read_only=True,
    )

    attempts = PaymentAttemptReadSerializer(
        many=True,
        read_only=True,
    )

    refunds = PaymentRefundReadSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = EnrollmentPayment

        fields = [
            "id",
            "enrollment",
            "course_id",
            "course_title",
            "student_id",
            "student_username",
            "payment_type",
            "amount",
            "currency",
            "billing_period_start",
            "billing_period_end",
            "status",
            "paid_at",
            "attempts",
            "refunds",
            "created_at",
            "updated_at",
        ]

        read_only_fields = fields


class PaymentRefundCreateSerializer(serializers.Serializer):

    payment = serializers.PrimaryKeyRelatedField(
        queryset=EnrollmentPayment.objects.all(),
    )

    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        trim_whitespace=True,
    )
