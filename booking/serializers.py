"""Explicit JSON schemas; passwords and roles cannot be set by registrants."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from . import services
from .models import Booking, User, Workshop


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]
        read_only_fields = fields


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        user = User(username=attrs["username"], email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"password": exc.messages}
            ) from exc
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class WorkshopSerializer(serializers.ModelSerializer):
    available_seats = serializers.SerializerMethodField()

    class Meta:
        model = Workshop
        fields = [
            "id",
            "title",
            "description",
            "location",
            "starts_at",
            "capacity",
            "reserved",
            "available_seats",
            "created_at",
        ]
        read_only_fields = ["reserved", "available_seats", "created_at"]

    def get_available_seats(self, obj):
        return obj.capacity - obj.reserved

    def validate_starts_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Укажите будущую дату.")
        return value

    def update(self, instance, validated_data):
        return services.update_workshop(
            instance=instance, validated_data=validated_data
        )


class BookingSerializer(serializers.ModelSerializer):
    workshop = WorkshopSerializer(read_only=True)
    workshop_id = serializers.IntegerField(write_only=True, min_value=1)

    class Meta:
        model = Booking
        fields = ["id", "workshop", "workshop_id", "created_at"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        return services.create_booking(
            user=self.context["request"].user, **validated_data
        )

    def update(self, instance, validated_data):
        return services.update_booking(
            user=self.context["request"].user,
            booking_id=instance.pk,
            **validated_data,
        )
