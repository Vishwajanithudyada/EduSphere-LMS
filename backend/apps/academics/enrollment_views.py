from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User

from .models import (
    Course,
    CourseEnrollment,
    EnrollmentRequest,
    CourseInvitation,
)

from .enrollment_serializers import (
    EnrollmentRequestCreateSerializer,
    EnrollmentRequestSerializer,
    ReviewEnrollmentRequestSerializer,
    CourseInvitationCreateSerializer,
    CourseInvitationSerializer,
)


# ==================================================
# ENROLLMENT REQUEST VIEWSET
# ==================================================

class EnrollmentRequestViewSet(viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    ADMIN_ROLES = [
        User.Role.SYSTEM_ADMIN,
        User.Role.INSTITUTE_ADMIN,
    ]

    def get_queryset(self):
        user = self.request.user

        queryset = EnrollmentRequest.objects.select_related(
            "course",
            "student",
            "reviewed_by",
        )

        if user.role in self.ADMIN_ROLES:
            return queryset

        if user.role == User.Role.STUDENT:
            return queryset.filter(student=user)

        if user.role == User.Role.TEACHER:
            return queryset.filter(course__created_by=user)

        return queryset.none()

    def get_serializer_class(self):
        if self.action == "create":
            return EnrollmentRequestCreateSerializer

        if self.action in ["approve", "reject"]:
            return ReviewEnrollmentRequestSerializer

        return EnrollmentRequestSerializer

    def create(self, request, *args, **kwargs):

        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied(
                "Only students can request course enrollment."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course_id = serializer.validated_data["course"].pk

        try:
            with transaction.atomic():

                # Lock order: Course first.
                course = (
                    Course.objects
                    .select_for_update()
                    .get(pk=course_id)
                )

                if (
                    course.approval_status
                    != Course.ApprovalStatus.PUBLISHED
                    or not course.is_active
                ):
                    raise ValidationError({
                        "course": "This course is no longer available."
                    })

                if (
                    course.enrollment_method
                    != Course.EnrollmentMethod.APPROVAL
                ):
                    raise ValidationError({
                        "course": (
                            "This course does not accept approval requests."
                        )
                    })

                if EnrollmentRequest.objects.filter(
                    course=course,
                    student=request.user,
                    status=EnrollmentRequest.Status.PENDING,
                ).exists():
                    raise ValidationError({
                        "course": "You already have a pending request."
                    })

                if CourseEnrollment.objects.filter(
                    course=course,
                    student=request.user,
                ).exists():
                    raise ValidationError({
                        "course": "An enrollment record already exists."
                    })

                enrollment_request = serializer.save(
                    course=course,
                    student=request.user,
                )

        except IntegrityError:
            raise ValidationError({
                "course": (
                    "An enrollment request or enrollment record "
                    "already exists for this course."
                )
            })

        response_serializer = EnrollmentRequestSerializer(
            enrollment_request,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def _review_request(self, request, decision):

        if request.user.role not in self.ADMIN_ROLES:
            raise PermissionDenied(
                "Only Institute Admins and System Admins "
                "can review enrollment requests."
            )

        enrollment_request_object = self.get_object()

        review_data = self.get_serializer(data=request.data)
        review_data.is_valid(raise_exception=True)

        try:
            with transaction.atomic():

                # Lock order: Course → EnrollmentRequest.
                course = (
                    Course.objects
                    .select_for_update()
                    .get(pk=enrollment_request_object.course_id)
                )

                enrollment_request = (
                    EnrollmentRequest.objects
                    .select_for_update()
                    .get(pk=enrollment_request_object.pk)
                )

                if (
                    enrollment_request.status
                    != EnrollmentRequest.Status.PENDING
                ):
                    raise ValidationError(
                        "Only pending enrollment requests can be reviewed."
                    )

                if (
                    course.approval_status
                    != Course.ApprovalStatus.PUBLISHED
                    or not course.is_active
                ):
                    raise ValidationError(
                        "This course is no longer available."
                    )

                if (
                    course.enrollment_method
                    != Course.EnrollmentMethod.APPROVAL
                ):
                    raise ValidationError(
                        "This course no longer accepts approval requests."
                    )

                now = timezone.now()

                enrollment_request.reviewed_by = request.user
                enrollment_request.reviewed_at = now
                enrollment_request.admin_remarks = (
                    review_data.validated_data.get("remarks", "")
                )

                if decision == "APPROVE":

                    if CourseEnrollment.objects.filter(
                        course=course,
                        student=enrollment_request.student,
                    ).exists():
                        raise ValidationError(
                            "An enrollment record already exists."
                        )

                    enrollment = CourseEnrollment.objects.create(
                        course=course,
                        student=enrollment_request.student,
                        status=CourseEnrollment.Status.PENDING,
                    )

                    if course.price == 0:
                        enrollment.status = CourseEnrollment.Status.ACTIVE
                        enrollment.activated_at = now
                        enrollment.save(
                            update_fields=[
                                "status",
                                "activated_at",
                                "updated_at",
                            ],
                        )

                    enrollment_request.status = (
                        EnrollmentRequest.Status.APPROVED
                    )

                elif decision == "REJECT":

                    enrollment_request.status = (
                        EnrollmentRequest.Status.REJECTED
                    )

                else:
                    raise ValidationError(
                        "Invalid enrollment review decision."
                    )

                enrollment_request.save(
                    update_fields=[
                        "status",
                        "reviewed_by",
                        "reviewed_at",
                        "admin_remarks",
                        "updated_at",
                    ],
                )

        except IntegrityError:
            raise ValidationError(
                "An enrollment record already exists for this student."
            )

        response_serializer = EnrollmentRequestSerializer(
            enrollment_request,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._review_request(request, "APPROVE")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._review_request(request, "REJECT")


# ==================================================
# COURSE INVITATION VIEWSET
# ==================================================

class CourseInvitationViewSet(viewsets.ModelViewSet):

    permission_classes = [IsAuthenticated]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    ADMIN_ROLES = [
        User.Role.SYSTEM_ADMIN,
        User.Role.INSTITUTE_ADMIN,
    ]

    INVITER_ROLES = [
        User.Role.SYSTEM_ADMIN,
        User.Role.INSTITUTE_ADMIN,
        User.Role.TEACHER,
    ]

    def get_queryset(self):
        user = self.request.user

        queryset = CourseInvitation.objects.select_related(
            "course",
            "invited_user",
            "invited_by",
        )

        if user.role in self.ADMIN_ROLES:
            return queryset

        if user.role == User.Role.TEACHER:
            return queryset.filter(course__created_by=user)

        if user.role == User.Role.STUDENT:

            queryset = queryset.filter(
                Q(invited_user=user)
                | Q(
                    invited_user__isnull=True,
                    invited_email__iexact=(user.email or ""),
                )
            )

            return queryset.distinct()

        return queryset.none()

    def get_serializer_class(self):
        if self.action == "create":
            return CourseInvitationCreateSerializer

        return CourseInvitationSerializer

    def create(self, request, *args, **kwargs):

        if request.user.role not in self.INVITER_ROLES:
            raise PermissionDenied(
                "Only Teachers and Admins can send course invitations."
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        course_id = serializer.validated_data["course"].pk
        invited_email = serializer.validated_data["invited_email"]

        try:
            with transaction.atomic():

                # Lock order: Course first.
                course = (
                    Course.objects
                    .select_for_update()
                    .get(pk=course_id)
                )

                if (
                    course.approval_status
                    != Course.ApprovalStatus.PUBLISHED
                    or not course.is_active
                ):
                    raise ValidationError({
                        "course": (
                            "Only published active courses "
                            "can be invited to."
                        )
                    })

                if (
                    course.enrollment_method
                    != Course.EnrollmentMethod.INVITATION
                ):
                    raise ValidationError({
                        "course": (
                            "This course does not use "
                            "invitation-based enrollment."
                        )
                    })

                if (
                    request.user.role == User.Role.TEACHER
                    and course.created_by_id != request.user.id
                ):
                    raise PermissionDenied(
                        "You can only invite students to your own courses."
                    )

                invited_user = User.objects.filter(
                    email__iexact=invited_email,
                    role=User.Role.STUDENT,
                ).first()

                if invited_user and CourseEnrollment.objects.filter(
                    course=course,
                    student=invited_user,
                ).exists():
                    raise ValidationError({
                        "invited_email": (
                            "This student already has an enrollment record."
                        )
                    })

                if CourseInvitation.objects.filter(
                    course=course,
                    invited_email__iexact=invited_email,
                    status=CourseInvitation.Status.PENDING,
                ).exists():
                    raise ValidationError({
                        "invited_email": (
                            "A pending invitation already exists "
                            "for this email."
                        )
                    })

                invitation = serializer.save(
                    course=course,
                    invited_user=invited_user,
                    invited_by=request.user,
                )

        except IntegrityError:
            raise ValidationError({
                "invited_email": (
                    "A pending invitation already exists for this email."
                )
            })

        response_serializer = CourseInvitationSerializer(
            invitation,
            context=self.get_serializer_context(),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    def _respond_to_invitation(self, request, decision):

        if request.user.role != User.Role.STUDENT:
            raise PermissionDenied(
                "Only students can respond to course invitations."
            )

        invitation_object = self.get_object()
        expired = False

        try:
            with transaction.atomic():

                # Lock order: Course → CourseInvitation.
                course = (
                    Course.objects
                    .select_for_update()
                    .get(pk=invitation_object.course_id)
                )

                invitation = (
                    CourseInvitation.objects
                    .select_for_update()
                    .get(pk=invitation_object.pk)
                )

                if invitation.status != CourseInvitation.Status.PENDING:
                    raise ValidationError(
                        "This invitation is no longer pending."
                    )

                # Registered invitations are bound to the original account.
                if invitation.invited_user_id is not None:

                    if invitation.invited_user_id != request.user.id:
                        raise PermissionDenied(
                            "This invitation does not belong to your account."
                        )

                else:
                    # Unregistered invitations require matching verified email.
                    student_email = (
                        (request.user.email or "").strip().lower()
                    )

                    invitation_email = (
                        invitation.invited_email.strip().lower()
                    )

                    if not student_email or invitation_email != student_email:
                        raise PermissionDenied(
                            "This invitation does not belong to your account."
                        )

                    if not request.user.is_email_verified:
                        raise PermissionDenied(
                            "Verify your email address before responding "
                            "to this invitation."
                        )

                now = timezone.now()

                if invitation.expires_at <= now:

                    invitation.status = CourseInvitation.Status.EXPIRED
                    invitation.save(
                        update_fields=["status"]
                    )
                    expired = True

                else:

                    if (
                        course.approval_status
                        != Course.ApprovalStatus.PUBLISHED
                        or not course.is_active
                        or course.enrollment_method
                        != Course.EnrollmentMethod.INVITATION
                    ):
                        raise ValidationError(
                            "This course is no longer accepting invitations."
                        )

                    if decision == "ACCEPT":

                        if CourseEnrollment.objects.filter(
                            course=course,
                            student=request.user,
                        ).exists():
                            raise ValidationError(
                                "You already have an enrollment record."
                            )

                        enrollment = CourseEnrollment.objects.create(
                            course=course,
                            student=request.user,
                            status=CourseEnrollment.Status.PENDING,
                        )

                        if course.price == 0:
                            enrollment.status = (
                                CourseEnrollment.Status.ACTIVE
                            )
                            enrollment.activated_at = now
                            enrollment.save(
                                update_fields=[
                                    "status",
                                    "activated_at",
                                    "updated_at",
                                ],
                            )

                        invitation.invited_user = request.user
                        invitation.status = (
                            CourseInvitation.Status.ACCEPTED
                        )
                        invitation.accepted_at = now

                    elif decision == "DECLINE":

                        invitation.invited_user = request.user
                        invitation.status = (
                            CourseInvitation.Status.DECLINED
                        )

                    else:
                        raise ValidationError(
                            "Invalid invitation decision."
                        )

                    invitation.save(
                        update_fields=[
                            "invited_user",
                            "status",
                            "accepted_at",
                        ],
                    )

        except IntegrityError:
            raise ValidationError(
                "An enrollment record already exists for this course."
            )

        if expired:
            raise ValidationError(
                "This invitation has expired."
            )

        response_serializer = CourseInvitationSerializer(
            invitation,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond_to_invitation(request, "ACCEPT")

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond_to_invitation(request, "DECLINE")

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):

        if request.user.role not in self.INVITER_ROLES:
            raise PermissionDenied(
                "Only the inviter or an Admin can revoke invitations."
            )

        invitation_object = self.get_object()

        with transaction.atomic():

            # Lock order: Course → CourseInvitation.
            course = (
                Course.objects
                .select_for_update()
                .get(pk=invitation_object.course_id)
            )

            invitation = (
                CourseInvitation.objects
                .select_for_update()
                .get(pk=invitation_object.pk)
            )

            if (
                request.user.role == User.Role.TEACHER
                and invitation.invited_by_id != request.user.id
            ):
                raise PermissionDenied(
                    "You can only revoke invitations sent by you."
                )

            if invitation.status != CourseInvitation.Status.PENDING:
                raise ValidationError(
                    "Only pending invitations can be revoked."
                )

            invitation.status = CourseInvitation.Status.REVOKED
            invitation.save(update_fields=["status"])

        response_serializer = CourseInvitationSerializer(
            invitation,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data)
