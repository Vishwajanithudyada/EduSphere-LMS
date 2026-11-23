
from rest_framework.routers import DefaultRouter

from .views import CourseViewSet

from .enrollment_views import (
    EnrollmentRequestViewSet,
    CourseInvitationViewSet,
)

from .content_views import (
    CourseModuleViewSet,
    LessonViewSet,
)

from .payment_views import (
    PaymentObligationViewSet,
    PaymentAttemptViewSet,
    PaymentRefundViewSet,
)


router = DefaultRouter()

router.register(
    r"courses",
    CourseViewSet,
    basename="course",
)

router.register(
    r"enrollment-requests",
    EnrollmentRequestViewSet,
    basename="enrollment-request",
)

router.register(
    r"course-invitations",
    CourseInvitationViewSet,
    basename="course-invitation",
)

router.register(
    r"modules",
    CourseModuleViewSet,
    basename="course-module",
)

router.register(
    r"lessons",
    LessonViewSet,
    basename="lesson",
)

router.register(
    r"payments",
    PaymentObligationViewSet,
    basename="payment",
)

router.register(
    r"payment-attempts",
    PaymentAttemptViewSet,
    basename="payment-attempt",
)

router.register(
    r"payment-refunds",
    PaymentRefundViewSet,
    basename="payment-refund",
)


urlpatterns = router.urls
