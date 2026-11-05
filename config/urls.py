"""Versioned REST routes."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from booking.views import (
    BookingViewSet,
    LoginView,
    LogoutView,
    MeView,
    RegistrationView,
    WorkshopViewSet,
)

router = DefaultRouter()
router.register("workshops", WorkshopViewSet, basename="workshop")
router.register("bookings", BookingViewSet, basename="booking")
urlpatterns = [
    path("api/v1/auth/register/", RegistrationView.as_view()),
    path("api/v1/auth/login/", LoginView.as_view()),
    path("api/v1/auth/logout/", LogoutView.as_view()),
    path("api/v1/auth/me/", MeView.as_view()),
    path("api/v1/", include(router.urls)),
]
