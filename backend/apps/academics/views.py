
from django.core.exceptions import (
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.db import transaction

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User

from .models import Course
from .serializers import (
    CourseSerializer,
    CourseApprovalLogSerializer,
    ApproveCourseSerializer,
    RejectCourseSerializer,
    PublishCourseSerializer,
)
from .services.course_workflow import (
    submit_course,
    approve_course,
    reject_course,
    publish_course,
)


class CourseViewSet(viewsets.ModelViewSet):

    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "put",
        "patch",
        "head",
        "options",
    ]

    ADMIN_ROLES = [
        User.Role.SYSTEM_ADMIN,
        User.Role.INSTITUTE_ADMIN,
    ]

    def get_queryset(self):

        user = self.request.user

        queryset = Course.objects.select_related(
            "academic_year",
            "stream",
            "subject",
            "created_by",
            "reviewed_by",
        ).prefetch_related(
            "subject__streams",
        )

        if user.role in self.ADMIN_ROLES:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(
                created_by=user,
            )

        if user.role == User.Role.STUDENT:
            return queryset.filter(
                approval_status=Course.ApprovalStatus.PUBLISHED,
                is_active=True,
            )

        return queryset.none()

    def create(self, request, *args, **kwargs):

        allowed_roles = [
            User.Role.TEACHER,
            User.Role.INSTITUTE_ADMIN,
        ]

        if request.user.role not in allowed_roles:
            raise PermissionDenied(
                "Only Teachers and Institute Admins can create courses."
            )

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):

        serializer.save(
            created_by=self.request.user,
            approval_status=Course.ApprovalStatus.DRAFT,
        )

    def update(self, request, *args, **kwargs):

        user = request.user

        if user.role not in [
            User.Role.TEACHER,
            User.Role.INSTITUTE_ADMIN,
            User.Role.SYSTEM_ADMIN,
        ]:
            raise PermissionDenied(
                "You do not have permission to edit courses."
            )

        partial = kwargs.pop("partial", False)

        with transaction.atomic():

            course = self.get_object()

            # Lock the course row until this transaction finishes.
            course = Course.objects.select_for_update().get(
                pk=course.pk,
            )

            if user.role == User.Role.TEACHER:
                if course.created_by_id != user.id:
                    raise PermissionDenied(
                        "You can only edit your own courses."
                    )

            if course.approval_status not in [
                Course.ApprovalStatus.DRAFT,
                Course.ApprovalStatus.REJECTED,
            ]:
                raise ValidationError(
                    "Only Draft or Rejected courses can be edited."
                )

            serializer = self.get_serializer(
                course,
                data=request.data,
                partial=partial,
            )

            serializer.is_valid(raise_exception=True)

            self.perform_update(serializer)

            if getattr(course, "_prefetched_objects_cache", None):
                course._prefetched_objects_cache = {}

        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):

        kwargs["partial"] = True

        return self.update(request, *args, **kwargs)

    def _validate_action_data(self, serializer_class, data):

        serializer = serializer_class(data=data)

        serializer.is_valid(
            raise_exception=True,
        )

        return serializer.validated_data

    def _execute_workflow(self, function, *args, **kwargs):

        try:

            course = function(
                *args,
                **kwargs,
            )

        except DjangoPermissionDenied as exc:

            raise PermissionDenied(str(exc))

        except DjangoValidationError as exc:

            if hasattr(exc, "message_dict"):
                detail = exc.message_dict
            else:
                detail = exc.messages

            raise ValidationError(detail)

        return Response(
            CourseSerializer(
                course,
                context={
                    "request": self.request,
                },
            ).data
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def submit(self, request, pk=None):

        course = self.get_object()

        return self._execute_workflow(
            submit_course,
            course.id,
            request.user,
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def approve(self, request, pk=None):

        course = self.get_object()

        validated_data = self._validate_action_data(
            ApproveCourseSerializer,
            request.data,
        )

        return self._execute_workflow(
            approve_course,
            course.id,
            request.user,
            remarks=validated_data.get("remarks", ""),
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def reject(self, request, pk=None):

        course = self.get_object()

        validated_data = self._validate_action_data(
            RejectCourseSerializer,
            request.data,
        )

        return self._execute_workflow(
            reject_course,
            course.id,
            request.user,
            reason=validated_data["reason"],
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def publish(self, request, pk=None):

        course = self.get_object()

        validated_data = self._validate_action_data(
            PublishCourseSerializer,
            request.data,
        )

        return self._execute_workflow(
            publish_course,
            course.id,
            request.user,
            remarks=validated_data.get("remarks", ""),
        )

    @action(
        detail=True,
        methods=["get"],
    )
    def history(self, request, pk=None):

        course = self.get_object()

        if request.user.role not in [
            User.Role.SYSTEM_ADMIN,
            User.Role.INSTITUTE_ADMIN,
            User.Role.TEACHER,
        ]:
            raise PermissionDenied(
                "You do not have permission to view approval history."
            )

        history = course.approval_history.select_related(
            "performed_by",
        ).all()

        serializer = CourseApprovalLogSerializer(
            history,
            many=True,
        )

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):

        return Response(
            {
                "detail": (
                    "Course deletion is not available through this API."
                )
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
