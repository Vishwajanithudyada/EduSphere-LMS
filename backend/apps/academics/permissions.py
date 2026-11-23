
from rest_framework.permissions import BasePermission


class IsTeacher(BasePermission):
    """Allow authenticated teachers only."""

    message = "Only teachers can perform this action."

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == "TEACHER"
        )


class IsInstituteAdmin(BasePermission):
    """Allow authenticated Institute Administrators only."""

    message = "Only Institute Administrators can perform this action."

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == "INSTITUTE_ADMIN"
        )


class IsCourseOwner(BasePermission):
    """Allow teachers to access only their own courses."""

    message = "You can only access your own courses."

    def has_object_permission(self, request, view, obj):
        return (
            request.user.is_authenticated
            and obj.created_by_id == request.user.id
        )


class IsCourseOwnerOrInstituteAdmin(BasePermission):
    """Allow course owners or Institute Administrators."""

    message = "You do not have permission to access this course."

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.user.role == "INSTITUTE_ADMIN":
            return True

        if request.user.role == "TEACHER":
            return obj.created_by_id == request.user.id

        return False
