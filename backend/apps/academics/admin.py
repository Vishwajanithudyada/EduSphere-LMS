
from django.contrib import admin

from .models import (
    AcademicYear,
    Stream,
    Subject,
    Course,
    CourseApprovalLog,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("year", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("year",)


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active", "streams")
    search_fields = ("name", "code")
    filter_horizontal = ("streams",)


class CourseApprovalLogInline(admin.TabularInline):
    model = CourseApprovalLog
    extra = 0
    can_delete = False
    show_change_link = False

    readonly_fields = (
        "action",
        "performed_by",
        "remarks",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):

    list_display = (
        "title",
        "code",
        "academic_year",
        "stream",
        "subject",
        "course_type",
        "approval_status",
        "created_by",
        "is_active",
    )

    list_filter = (
        "academic_year",
        "stream",
        "subject",
        "course_type",
        "delivery_mode",
        "approval_status",
    )

    search_fields = ("title", "code")

    # Workflow-managed fields cannot be changed directly
    # through Django Admin.
    readonly_fields = (
        "approval_status",
        "created_by",
        "reviewed_by",
        "reviewed_at",
        "rejection_reason",
        "created_at",
        "updated_at",
    )

    inlines = [CourseApprovalLogInline]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)


@admin.register(CourseApprovalLog)
class CourseApprovalLogAdmin(admin.ModelAdmin):

    list_display = (
        "course",
        "action",
        "performed_by",
        "created_at",
    )

    list_filter = ("action", "created_at")

    search_fields = (
        "course__title",
        "course__code",
        "remarks",
    )

    readonly_fields = (
        "course",
        "action",
        "performed_by",
        "remarks",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
