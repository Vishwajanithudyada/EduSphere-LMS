
from decimal import Decimal

from django.db.models import Exists, OuterRef

from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User

from .models import (
    Course,
    CourseModule,
    CourseEnrollment,
    EnrollmentPayment,
    Lesson,
)
from .serializers import (
    CourseModuleSerializer,
    LessonSerializer,
)


ADMIN_ROLES = [
    User.Role.SYSTEM_ADMIN,
    User.Role.INSTITUTE_ADMIN,
]

MANAGEMENT_ROLES = [
    User.Role.TEACHER,
    User.Role.INSTITUTE_ADMIN,
    User.Role.SYSTEM_ADMIN,
]


def can_manage_course(user, course):
    if user.role in ADMIN_ROLES:
        return True

    if user.role == User.Role.TEACHER:
        return course.created_by_id == user.id

    return False


def get_active_enrollment(user, course):
    return CourseEnrollment.objects.filter(
        course=course,
        student=user,
        status=CourseEnrollment.Status.ACTIVE,
    ).first()


def has_lesson_content_access(user, lesson):
    """
    Check whether a student can access the actual lesson content.

    Monthly:
        Requires a PAID payment for the exact lesson billing period.

    Completion:
        Requires a PAID one-time payment.

    Free courses:
        Active enrollment is sufficient.
    """

    course = lesson.module.course

    if (
        course.approval_status != Course.ApprovalStatus.PUBLISHED
        or not course.is_active
        or not lesson.module.is_active
        or not lesson.is_published
    ):
        return False

    enrollment = get_active_enrollment(user, course)

    if enrollment is None:
        return False

    if course.price == Decimal("0.00"):
        return True

    payments = EnrollmentPayment.objects.filter(
        enrollment=enrollment,
        status=EnrollmentPayment.Status.PAID,
    )

    if course.access_policy == Course.AccessPolicy.MONTHLY:

        if (
            lesson.billing_period_start is None
            or lesson.billing_period_end is None
        ):
            return False

        return payments.filter(
            payment_type=EnrollmentPayment.PaymentType.MONTHLY,
            billing_period_start=lesson.billing_period_start,
            billing_period_end=lesson.billing_period_end,
        ).exists()

    if course.access_policy == Course.AccessPolicy.COMPLETION:

        return payments.filter(
            payment_type=EnrollmentPayment.PaymentType.ONE_TIME,
        ).exists()

    return False


class StudentLessonSerializer(LessonSerializer):
    """
    Students can see published lesson metadata.

    Actual content and video URL are returned only when
    the student's enrollment and payment authorize access.
    """

    def to_representation(self, instance):

        data = super().to_representation(instance)

        request = self.context.get("request")

        if request is None or not request.user.is_authenticated:
            data["content"] = ""
            data["video_url"] = ""
            data["is_locked"] = True
            return data

        user = request.user

        if user.role == User.Role.STUDENT:

            allowed = has_lesson_content_access(
                user,
                instance,
            )

            if not allowed:
                data["content"] = ""
                data["video_url"] = ""

            data["is_locked"] = not allowed

        else:
            data["is_locked"] = False

        return data


class CourseModuleViewSet(viewsets.ModelViewSet):

    serializer_class = CourseModuleSerializer
    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "head",
        "options",
    ]

    def get_queryset(self):

        user = self.request.user

        queryset = CourseModule.objects.select_related(
            "course",
            "course__created_by",
        )

        if user.role in ADMIN_ROLES:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                course__created_by=user,
            )

        if user.role == User.Role.STUDENT:

            active_enrollment = CourseEnrollment.objects.filter(
                course_id=OuterRef("course_id"),
                student=user,
                status=CourseEnrollment.Status.ACTIVE,
            )

            return queryset.filter(
                course__approval_status=Course.ApprovalStatus.PUBLISHED,
                course__is_active=True,
                is_active=True,
            ).annotate(
                has_active_enrollment=Exists(active_enrollment),
            ).filter(
                has_active_enrollment=True,
            )

        return queryset.none()

    def create(self, request, *args, **kwargs):

        if request.user.role not in MANAGEMENT_ROLES:
            raise PermissionDenied(
                "You cannot create course modules."
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):

        course = serializer.validated_data["course"]

        if not can_manage_course(self.request.user, course):
            raise PermissionDenied(
                "You can only manage your own courses."
            )

        serializer.save()

    def perform_update(self, serializer):

        course = serializer.validated_data.get(
            "course",
            serializer.instance.course,
        )

        if not can_manage_course(self.request.user, course):
            raise PermissionDenied(
                "You can only manage your own courses."
            )

        serializer.save()

    def destroy(self, request, *args, **kwargs):

        return Response(
            {
                "detail": (
                    "Module deletion is disabled. "
                    "Deactivate the module instead."
                )
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class LessonViewSet(viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "head",
        "options",
    ]

    def get_serializer_class(self):

        if self.request.user.role == User.Role.STUDENT:
            return StudentLessonSerializer

        return LessonSerializer

    def get_queryset(self):

        user = self.request.user

        queryset = Lesson.objects.select_related(
            "module",
            "module__course",
            "module__course__created_by",
        )

        if user.role in ADMIN_ROLES:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                module__course__created_by=user,
            )

        if user.role == User.Role.STUDENT:

            active_enrollment = CourseEnrollment.objects.filter(
                course_id=OuterRef("module__course_id"),
                student=user,
                status=CourseEnrollment.Status.ACTIVE,
            )

            return queryset.filter(
                module__course__approval_status=(
                    Course.ApprovalStatus.PUBLISHED
                ),
                module__course__is_active=True,
                module__is_active=True,
                is_published=True,
            ).annotate(
                has_active_enrollment=Exists(active_enrollment),
            ).filter(
                has_active_enrollment=True,
            )

        return queryset.none()

    def create(self, request, *args, **kwargs):

        if request.user.role not in MANAGEMENT_ROLES:
            raise PermissionDenied(
                "You cannot create lessons."
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):

        module = serializer.validated_data["module"]

        if not can_manage_course(
            self.request.user,
            module.course,
        ):
            raise PermissionDenied(
                "You can only manage lessons in your own courses."
            )

        serializer.save()

    def perform_update(self, serializer):

        module = serializer.validated_data.get(
            "module",
            serializer.instance.module,
        )

        if not can_manage_course(
            self.request.user,
            module.course,
        ):
            raise PermissionDenied(
                "You can only manage lessons in your own courses."
            )

        serializer.save()

    def destroy(self, request, *args, **kwargs):

        return Response(
            {
                "detail": (
                    "Lesson deletion is disabled. "
                    "Unpublish the lesson instead."
                )
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
