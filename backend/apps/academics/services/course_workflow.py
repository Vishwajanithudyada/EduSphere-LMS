
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.academics.models import Course, CourseApprovalLog


def _get_locked_course(course_id):

    return Course.objects.select_for_update().select_related(
        "academic_year",
        "stream",
        "subject",
    ).get(
        pk=course_id,
    )


def _require_roles(user, allowed_roles):

    if not user.is_authenticated:
        raise PermissionDenied(
            "Authentication required."
        )

    if user.role not in allowed_roles:
        raise PermissionDenied(
            "You do not have permission to perform this action."
        )


def _require_admin(user):

    _require_roles(
        user,
        [
            User.Role.INSTITUTE_ADMIN,
            User.Role.SYSTEM_ADMIN,
        ],
    )


def _record_action(course, action, user, remarks=""):

    CourseApprovalLog.objects.create(
        course=course,
        action=action,
        performed_by=user,
        remarks=remarks,
    )


def _validate_course_for_publishing(course):
    """
    Validate all important course details before publishing.
    """

    errors = {}

    if not course.is_active:
        errors["is_active"] = (
            "Inactive courses cannot be published."
        )

    if not course.academic_year.is_active:
        errors["academic_year"] = (
            "The selected Academic Year is inactive."
        )

    if not course.stream.is_active:
        errors["stream"] = (
            "The selected Stream is inactive."
        )

    if not course.subject.is_active:
        errors["subject"] = (
            "The selected Subject is inactive."
        )

    if not course.subject.streams.filter(
        pk=course.stream_id,
        is_active=True,
    ).exists():
        errors["subject"] = (
            "The selected Subject is not assigned "
            "to the selected active Stream."
        )

    if errors:
        raise ValidationError(errors)

    # Run the model's complete validation rules.
    # This also checks required fields, price and model.clean().
    course.full_clean()


@transaction.atomic
def submit_course(course_id, user):
    """
    Teachers and Institute Admins can submit
    their own Draft or Rejected courses.
    """

    _require_roles(
        user,
        [
            User.Role.TEACHER,
            User.Role.INSTITUTE_ADMIN,
        ],
    )

    course = _get_locked_course(course_id)

    if course.created_by_id != user.id:
        raise PermissionDenied(
            "You can only submit your own courses."
        )

    if course.approval_status not in [
        Course.ApprovalStatus.DRAFT,
        Course.ApprovalStatus.REJECTED,
    ]:
        raise ValidationError(
            "This course cannot be submitted in its current status."
        )

    course.approval_status = Course.ApprovalStatus.PENDING
    course.rejection_reason = ""
    course.reviewed_by = None
    course.reviewed_at = None

    course.save(
        update_fields=[
            "approval_status",
            "rejection_reason",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    _record_action(
        course,
        CourseApprovalLog.Action.SUBMITTED,
        user,
        "Course submitted for review.",
    )

    return course


@transaction.atomic
def approve_course(course_id, user, remarks=""):
    """
    Institute Admin and System Admin can approve
    pending courses.

    Course creators cannot approve their own courses.
    """

    _require_admin(user)

    course = _get_locked_course(course_id)

    if course.created_by_id == user.id:
        raise PermissionDenied(
            "You cannot approve a course created by yourself."
        )

    if course.approval_status != Course.ApprovalStatus.PENDING:
        raise ValidationError(
            "Only pending courses can be approved."
        )

    course.approval_status = Course.ApprovalStatus.APPROVED
    course.reviewed_by = user
    course.reviewed_at = timezone.now()
    course.rejection_reason = ""

    course.save(
        update_fields=[
            "approval_status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "updated_at",
        ]
    )

    _record_action(
        course,
        CourseApprovalLog.Action.APPROVED,
        user,
        remarks,
    )

    return course


@transaction.atomic
def reject_course(course_id, user, reason):
    """
    Institute Admin and System Admin can reject
    pending courses with a mandatory reason.
    """

    _require_admin(user)

    if not reason or not reason.strip():
        raise ValidationError(
            "A rejection reason is required."
        )

    course = _get_locked_course(course_id)

    if course.created_by_id == user.id:
        raise PermissionDenied(
            "You cannot reject a course created by yourself."
        )

    if course.approval_status != Course.ApprovalStatus.PENDING:
        raise ValidationError(
            "Only pending courses can be rejected."
        )

    clean_reason = reason.strip()

    course.approval_status = Course.ApprovalStatus.REJECTED
    course.reviewed_by = user
    course.reviewed_at = timezone.now()
    course.rejection_reason = clean_reason

    course.save(
        update_fields=[
            "approval_status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "updated_at",
        ]
    )

    _record_action(
        course,
        CourseApprovalLog.Action.REJECTED,
        user,
        clean_reason,
    )

    return course


@transaction.atomic
def publish_course(course_id, user, remarks=""):
    """
    Institute Admin and System Admin can publish
    approved courses.

    Course creators cannot publish their own courses.
    All course details are validated before publishing.
    """

    _require_admin(user)

    course = _get_locked_course(course_id)

    if course.created_by_id == user.id:
        raise PermissionDenied(
            "You cannot publish a course created by yourself."
        )

    if course.approval_status != Course.ApprovalStatus.APPROVED:
        raise ValidationError(
            "Only approved courses can be published."
        )

    # Validate course details before publishing.
    _validate_course_for_publishing(course)

    course.approval_status = Course.ApprovalStatus.PUBLISHED

    course.save(
        update_fields=[
            "approval_status",
            "updated_at",
        ]
    )

    _record_action(
        course,
        CourseApprovalLog.Action.PUBLISHED,
        user,
        remarks,
    )

    return course
