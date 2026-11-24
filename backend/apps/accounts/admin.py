
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):

    list_display = (
        "username",
        "email",
        "role",
        "is_staff",
        "is_active",
    )

    list_filter = (
        "role",
        "is_staff",
        "is_active",
    )

    fieldsets = UserAdmin.fieldsets + (
        (
            "EduSphere Information",
            {
                "fields": (
                    "role",
                    "phone_number",
                    "is_email_verified",
                ),
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "EduSphere Information",
            {
                "fields": (
                    "role",
                    "phone_number",
                    "is_email_verified",
                ),
            },
        ),
    )

    SUPERUSER_ONLY_FIELDS = {
        "role",
        "is_staff",
        "is_superuser",
        "groups",
        "user_permissions",
        "is_email_verified",
    }

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if not request.user.is_superuser:
            queryset = queryset.filter(
                is_staff=False,
                is_superuser=False,
            )

        return queryset

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)

        if request.user.is_superuser:
            return fieldsets

        filtered_fieldsets = []

        for name, options in fieldsets:
            filtered_fields = []

            for field in options.get("fields", ()):
                if isinstance(field, (tuple, list)):
                    remaining = tuple(
                        item
                        for item in field
                        if item not in self.SUPERUSER_ONLY_FIELDS
                    )

                    if remaining:
                        filtered_fields.append(remaining)

                elif field not in self.SUPERUSER_ONLY_FIELDS:
                    filtered_fields.append(field)

            if filtered_fields:
                new_options = {
                    **options,
                    "fields": tuple(filtered_fields),
                }

                filtered_fieldsets.append(
                    (name, new_options)
                )

        return tuple(filtered_fieldsets)

    def save_model(self, request, obj, form, change):

        if not request.user.is_superuser:

            if change:
                original = User.objects.get(pk=obj.pk)

                obj.role = original.role
                obj.is_staff = original.is_staff
                obj.is_superuser = original.is_superuser
                obj.is_email_verified = original.is_email_verified

            else:
                obj.role = User.Role.STUDENT
                obj.is_staff = False
                obj.is_superuser = False
                obj.is_email_verified = False

        super().save_model(request, obj, form, change)
