
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()


class AuthenticationAPITests(APITestCase):

    def setUp(self):
        # Reset throttle cache before each test.
        cache.clear()

        self.register_url = reverse("account-register")
        self.login_url = reverse("token-obtain-pair")
        self.refresh_url = reverse("token-refresh")
        self.logout_url = reverse("account-logout")

        self.user = User.objects.create_user(
            username="teststudent",
            email="student@example.com",
            password="StrongTestPassword123!",
            role=User.Role.STUDENT,
        )

    def test_student_registration_success(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "newstudent",
                "email": "newstudent@example.com",
                "password": "StrongRegistrationPass123!",
                "first_name": "New",
                "last_name": "Student",
                "phone_number": "0771234567",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_user = User.objects.get(username="newstudent")

        self.assertEqual(new_user.role, User.Role.STUDENT)
        self.assertFalse(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)
        self.assertFalse(new_user.is_email_verified)
        self.assertTrue(
            new_user.check_password("StrongRegistrationPass123!")
        )

    def test_registration_prevents_privilege_escalation(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "forgedadmin",
                "email": "forged@example.com",
                "password": "StrongRegistrationPass123!",
                "role": User.Role.SYSTEM_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_email_verified": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_user = User.objects.get(username="forgedadmin")

        self.assertEqual(new_user.role, User.Role.STUDENT)
        self.assertFalse(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)
        self.assertFalse(new_user.is_email_verified)

    def test_registration_rejects_duplicate_email(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "anotherstudent",
                "email": "STUDENT@example.com",
                "password": "StrongRegistrationPass123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_registration_rejects_weak_password(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "weakpassworduser",
                "email": "weak@example.com",
                "password": "123",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            User.objects.filter(username="weakpassworduser").exists()
        )

    def test_jwt_login_success(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "teststudent",
                "password": "StrongTestPassword123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_jwt_login_rejects_invalid_password(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "teststudent",
                "password": "WrongPassword123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_refresh_token_rotation(self):
        refresh = RefreshToken.for_user(self.user)

        response = self.client.post(
            self.refresh_url,
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

        self.assertNotEqual(
            response.data["refresh"],
            str(refresh),
        )

    def test_logout_blacklists_own_refresh_token(self):
        refresh = RefreshToken.for_user(self.user)

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.logout_url,
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with self.assertRaises(TokenError):
            RefreshToken(str(refresh))

    def test_logout_rejects_another_users_refresh_token(self):
        another_user = User.objects.create_user(
            username="anotheruser",
            email="another@example.com",
            password="AnotherStrongPassword123!",
        )

        refresh = RefreshToken.for_user(another_user)

        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            self.logout_url,
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_login_rate_limit(self):
        for _ in range(5):
            response = self.client.post(
                self.login_url,
                {
                    "username": "teststudent",
                    "password": "WrongPassword123!",
                },
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
            )

        response = self.client.post(
            self.login_url,
            {
                "username": "teststudent",
                "password": "WrongPassword123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_registration_rate_limit(self):
        for index in range(3):
            response = self.client.post(
                self.register_url,
                {
                    "username": f"ratelimituser{index}",
                    "email": f"ratelimit{index}@example.com",
                    "password": "StrongRegistrationPass123!",
                },
                format="json",
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
            )

        response = self.client.post(
            self.register_url,
            {
                "username": "ratelimituser4",
                "email": "ratelimit4@example.com",
                "password": "StrongRegistrationPass123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
