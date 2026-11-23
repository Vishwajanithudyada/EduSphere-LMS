
from django.core.exceptions import (
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)

from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User

from .models import (
    EnrollmentPayment,
    PaymentAttempt,
    PaymentRefund,
)

from .payment_serializers import (
    PaymentObligationCreateSerializer,
    PaymentObligationReadSerializer,
    PaymentAttemptReadSerializer,
    PaymentRefundCreateSerializer,
    PaymentRefundReadSerializer,
)

from .services.payment_services import (
    create_payment_obligation,
    request_payment_refund,
)


ADMIN_ROLES = [
    User.Role.SYSTEM_ADMIN,
    User.Role.INSTITUTE_ADMIN,
]


def handle_service_exception(exc):

    if isinstance(exc, DjangoPermissionDenied):
        raise PermissionDenied(str(exc))

    if isinstance(exc, DjangoValidationError):

        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        else:
            detail = exc.messages

        raise ValidationError(detail)


# ============================================================
# PAYMENT OBLIGATION VIEWSET
# ============================================================

class PaymentObligationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):

        user = self.request.user

        queryset = EnrollmentPayment.objects.select_related(
            "enrollment",
            "enrollment__course",
            "enrollment__student",
        ).prefetch_related(
            "attempts",
            "refunds",
            "refunds__requested_by",
        )

        if user.role in ADMIN_ROLES:
            return queryset

        if user.role == User.Role.STUDENT:
            return queryset.filter(
                enrollment__student=user,
            )

        return queryset.none()

    def get_serializer_class(self):

        if self.action == "create":
            return PaymentObligationCreateSerializer

        return PaymentObligationReadSerializer

    def create(self, request, *args, **kwargs):

        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied(
                "Only students can create their payment obligations."
            )

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        data = serializer.validated_data

        try:

            payment = create_payment_obligation(
                enrollment_id=data["enrollment"].pk,
                user=request.user,
                billing_period_start=data.get(
                    "billing_period_start"
                ),
                billing_period_end=data.get(
                    "billing_period_end"
                ),
                currency=data.get("currency", "LKR"),
            )

        except (
            DjangoPermissionDenied,
            DjangoValidationError,
        ) as exc:

            handle_service_exception(exc)

        response_serializer = PaymentObligationReadSerializer(
            payment,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


# ============================================================
# PAYMENT ATTEMPT VIEWSET
# ============================================================

class PaymentAttemptViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "head",
        "options",
    ]

    def get_queryset(self):

        user = self.request.user

        queryset = PaymentAttempt.objects.select_related(
            "payment",
            "payment__enrollment",
            "payment__enrollment__student",
        )

        if user.role in ADMIN_ROLES:
            return queryset

        if user.role == User.Role.STUDENT:
            return queryset.filter(
                payment__enrollment__student=user,
            )

        return queryset.none()

    serializer_class = PaymentAttemptReadSerializer


# ============================================================
# PAYMENT REFUND VIEWSET
# ============================================================

class PaymentRefundViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):

        user = self.request.user

        queryset = PaymentRefund.objects.select_related(
            "payment",
            "payment__enrollment",
            "payment__enrollment__course",
            "payment__enrollment__student",
            "requested_by",
        )

        if user.role in ADMIN_ROLES:
            return queryset

        if user.role == User.Role.STUDENT:
            return queryset.filter(
                payment__enrollment__student=user,
            )

        return queryset.none()

    def get_serializer_class(self):

        if self.action == "create":
            return PaymentRefundCreateSerializer

        return PaymentRefundReadSerializer

    def create(self, request, *args, **kwargs):

        if request.user.role not in ADMIN_ROLES:
            raise PermissionDenied(
                "Only administrators can request payment refunds."
            )

        serializer = self.get_serializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True,
        )

        data = serializer.validated_data

        try:

            refund = request_payment_refund(
                payment_id=data["payment"].pk,
                user=request.user,
                amount=data["amount"],
                reason=data.get("reason", ""),
            )

        except (
            DjangoPermissionDenied,
            DjangoValidationError,
        ) as exc:

            handle_service_exception(exc)

        response_serializer = PaymentRefundReadSerializer(
            refund,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )
