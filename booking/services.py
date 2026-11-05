"""Transactional business rules shared by API write operations."""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from .models import Booking, Workshop


def _reserve_seat(workshop_id):
    """Claim one future seat; callers must wrap this in a transaction."""
    claimed = Workshop.objects.filter(
        pk=workshop_id,
        starts_at__gt=timezone.now(),
        reserved__lt=F("capacity"),
    ).update(reserved=F("reserved") + 1)
    if not claimed:
        if not Workshop.objects.filter(pk=workshop_id).exists():
            raise ValidationError({"workshop_id": "Мастер-класс не найден."})
        raise ValidationError(
            {"workshop_id": "Мест нет или мастер-класс уже начался."}
        )


@transaction.atomic
def create_booking(*, user, workshop_id):
    """Claim a seat and insert the booking as one indivisible operation.

    The first database operation is a write: concurrent requests cannot both
    claim the final seat. A failed insert rolls the counter back with the tx.
    """
    _reserve_seat(workshop_id)
    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user, workshop_id=workshop_id
            )
    except IntegrityError as exc:
        raise ValidationError({"workshop_id": "Вы уже записаны."}) from exc
    return Booking.objects.select_related("workshop").get(pk=booking.pk)


def _lock_owned_booking(*, user, booking_id):
    """Acquire SQLite's write lock before reading the booking to change."""
    owned = Booking.objects.filter(pk=booking_id, user=user)
    Workshop.objects.filter(pk__in=owned.values("workshop_id")).update(
        reserved=F("reserved")
    )
    booking = owned.select_related("workshop").first()
    if booking is None:
        raise NotFound()
    return booking


@transaction.atomic
def update_booking(*, user, booking_id, workshop_id=None):
    """Move an owned booking, rolling back both seat counters on failure."""
    booking = _lock_owned_booking(user=user, booking_id=booking_id)
    if workshop_id is None or workshop_id == booking.workshop_id:
        return booking
    previous_id = booking.workshop_id
    _reserve_seat(workshop_id)
    try:
        with transaction.atomic():
            booking.workshop_id = workshop_id
            booking.save(update_fields=["workshop_id"])
    except IntegrityError as exc:
        raise ValidationError({"workshop_id": "Вы уже записаны."}) from exc
    Workshop.objects.filter(pk=previous_id).update(reserved=F("reserved") - 1)
    return Booking.objects.select_related("workshop").get(pk=booking.pk)


@transaction.atomic
def cancel_booking(*, user, booking_id):
    """Serialize counter updates before checking/deleting an owned booking."""
    # A subquery keeps the first database operation a write, avoiding SQLite's
    # read-to-write lock upgrade when two cancellations arrive simultaneously.
    booking = _lock_owned_booking(user=user, booking_id=booking_id)
    workshop_id = booking.workshop_id
    booking.delete()
    Workshop.objects.filter(pk=workshop_id).update(reserved=F("reserved") - 1)


@transaction.atomic
def update_workshop(*, instance, validated_data):
    """Prevent lowering capacity below current occupancy during admin edits."""
    if not validated_data:
        instance.refresh_from_db()
        return instance
    queryset = Workshop.objects.filter(pk=instance.pk)
    if "capacity" in validated_data:
        queryset = queryset.filter(reserved__lte=validated_data["capacity"])
    updated = queryset.update(**validated_data)
    if not updated:
        if not Workshop.objects.filter(pk=instance.pk).exists():
            raise NotFound()
        raise ValidationError(
            {"capacity": "Вместимость меньше числа бронирований."}
        )
    instance.refresh_from_db()
    return instance
