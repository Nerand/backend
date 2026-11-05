"""Public event catalogue, administrator-only event changes."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import User


class WorkshopPermission(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMIN
        )
