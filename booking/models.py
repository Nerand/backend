"""Users, workshops and unique single-seat bookings."""

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models


class User(AbstractUser):
    """Public registration always creates a regular user."""

    class Role(models.TextChoices):
        USER = "user", "Пользователь"
        ADMIN = "admin", "Администратор"

    role = models.CharField(
        max_length=10, choices=Role.choices, default=Role.USER
    )


class Workshop(models.Model):
    """A scheduled event; reserved is updated atomically by services."""

    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=250)
    starts_at = models.DateTimeField(db_index=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    reserved = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1), name="capacity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__lte=models.F("capacity")),
                name="reserved_within_capacity",
            ),
        ]


class Booking(models.Model):
    """One participant occupies one seat; cancellation deletes the record."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="bookings"
    )
    workshop = models.ForeignKey(
        Workshop, on_delete=models.CASCADE, related_name="bookings"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "workshop"], name="unique_user_workshop"
            ),
        ]
