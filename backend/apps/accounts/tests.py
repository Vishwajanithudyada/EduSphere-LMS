
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django import forms


from .admin import CustomUserAdmin


User = get_user_model()


class CustomUserAdminSecurityTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = admin.AdminSite()

        self.model_admin = CustomUserAdmin(
            User,
            self.admin_site,
        )

        self.superuser = User.objects.create_superuser(
            username="superadmin",
            email="superadmin@example.com",
            password="TestPassword123!",
        )

        self.normal_staff = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="TestPassword123!",
            role=User.Role.TEACHER,
            is_staff=True,
        )

        self.student = User.objects.create_user(
            username="studentuser",
            email="student@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )

        change_permission = Permission.objects.get(
            content_type__app_label=User._meta.app_label,
            codename=f"change_{User._meta.model_name}",
        )

        self.normal_staff.user_permissions.add(change_permission)

    def get_request(self, user):
        request = self.factory.get("/admin/accounts/user/")
        request.user = user
        return request

    def get_visible_fields(self, request, obj=None):
        fieldsets = self.model_admin.get_fieldsets(request, obj)

        return {
            field
            for _, options in fieldsets
            for item in options.get("fields", ())
            for field in (
                item if isinstance(item, (tuple, list))
                else (item,)
            )
        }

    def test_non_superuser_cannot_access_staff_accounts(self):
        request = self.get_request(self.normal_staff)
        queryset = self.model_admin.get_queryset(request)

        self.assertNotIn(self.normal_staff, queryset)
        self.assertNotIn(self.superuser, queryset)
        self.assertIn(self.student, queryset)

    def test_non_superuser_cannot_see_privileged_fields(self):
        request = self.get_request(self.normal_staff)

        add_fields = self.get_visible_fields(request)
        change_fields = self.get_visible_fields(
            request,
            self.student,
        )

        restricted_fields = {
            "role",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
            "is_email_verified",
        }

        self.assertTrue(restricted_fields.isdisjoint(add_fields))
        self.assertTrue(restricted_fields.isdisjoint(change_fields))

    def test_superuser_can_access_privileged_fields(self):
        request = self.get_request(self.superuser)

        change_fields = self.get_visible_fields(
            request,
            self.student,
        )

        self.assertIn("role", change_fields)
        self.assertIn("is_staff", change_fields)
        self.assertIn("is_superuser", change_fields)
        self.assertIn("groups", change_fields)
        self.assertIn("user_permissions", change_fields)

    def test_non_superuser_cannot_escalate_existing_user(self):
        request = self.get_request(self.normal_staff)

        self.student.role = User.Role.SYSTEM_ADMIN
        self.student.is_staff = True
        self.student.is_superuser = True
        self.student.is_email_verified = True

        self.model_admin.save_model(
            request,
            self.student,
            None,
            True,
        )

        self.student.refresh_from_db()

        self.assertEqual(
            self.student.role,
            User.Role.STUDENT,
        )
        self.assertFalse(self.student.is_staff)
        self.assertFalse(self.student.is_superuser)
        self.assertFalse(self.student.is_email_verified)

    def test_non_superuser_cannot_create_privileged_user(self):
        request = self.get_request(self.normal_staff)

        new_user = User(
            username="forgedadmin",
            email="forged@example.com",
            role=User.Role.SYSTEM_ADMIN,
            is_staff=True,
            is_superuser=True,
            is_email_verified=True,
        )

        self.model_admin.save_model(
            request,
            new_user,
            None,
            False,
        )

        new_user.refresh_from_db()

        self.assertEqual(
            new_user.role,
            User.Role.STUDENT,
        )
        self.assertFalse(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)
        self.assertFalse(new_user.is_email_verified)

    def test_http_staff_can_access_student_change_page(self):
        self.client.force_login(self.normal_staff)

        url = reverse(
            "admin:accounts_user_change",
            args=[self.student.pk],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    def test_http_forged_post_cannot_escalate_student(self):
        self.client.force_login(self.normal_staff)

        url = reverse(
            "admin:accounts_user_change",
            args=[self.student.pk],
        )

        get_response = self.client.get(url)

        self.assertEqual(get_response.status_code, 200)

        form = get_response.context["adminform"].form
        post_data = {}

        for name, field in form.fields.items():
            value = form.initial.get(name)

            if value is None and hasattr(self.student, name):
                value = getattr(self.student, name)

            if isinstance(field.widget, forms.SplitDateTimeWidget):
                date_value, time_value = field.widget.decompress(value)

                post_data[f"{name}_0"] = (
                    date_value.strftime("%Y-%m-%d")
                    if date_value else ""
                )

                post_data[f"{name}_1"] = (
                    time_value.strftime("%H:%M:%S")
                    if time_value else ""
                )

            elif isinstance(field, forms.BooleanField):
                post_data[name] = "on" if value else ""

            elif value is not None:
                post_data[name] = field.prepare_value(value)

            else:
                post_data[name] = ""

        post_data.update({
            "role": User.Role.SYSTEM_ADMIN,
            "is_staff": "on",
            "is_superuser": "on",
            "is_email_verified": "on",
            "_save": "Save",
        })

        response = self.client.post(url, post_data)

        self.assertEqual(response.status_code, 302)

        self.student.refresh_from_db()

        self.assertEqual(
            self.student.role,
            User.Role.STUDENT,
        )
        self.assertFalse(self.student.is_staff)
        self.assertFalse(self.student.is_superuser)
        self.assertFalse(self.student.is_email_verified)
