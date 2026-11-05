"""API integration tests for permissions, invariants and query counts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APITestCase

from .models import Booking, User, Workshop
from .services import cancel_booking, create_booking, update_booking


class BookingAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "alice", password="ExampleSecret-123"
        )
        self.other = User.objects.create_user(
            "bob", password="ExampleSecret-456"
        )
        self.admin = User.objects.create_user("admin", role="admin")
        self.workshop = Workshop.objects.create(**self.payload())
        self.base = "/api/v1/"

    def payload(self, **overrides):
        data = {
            "title": "Python",
            "description": "Практика",
            "location": "Онлайн",
            "starts_at": timezone.now() + timedelta(days=10),
            "capacity": 2,
        }
        data.update(overrides)
        return data

    def auth(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def book(self, workshop=None):
        return self.client.post(
            self.base + "bookings/",
            {
                "workshop_id": (workshop or self.workshop).pk,
            },
        )

    def test_public_catalogue_and_detail(self):
        self.assertEqual(
            self.client.get(self.base + "workshops/").status_code, 200
        )
        response = self.client.get(f"{self.base}workshops/{self.workshop.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["available_seats"], 2)

    def test_anonymous_cannot_book(self):
        self.assertEqual(self.book().status_code, 401)

    def test_register_login_logout_and_no_password_leak(self):
        response = self.client.post(
            self.base + "auth/register/",
            {
                "username": "charlie",
                "password": "Unusual-Password-239!",
                "role": "admin",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.data)
        self.assertEqual(User.objects.get(username="charlie").role, "user")
        login = self.client.post(
            self.base + "auth/login/",
            {
                "username": "charlie",
                "password": "Unusual-Password-239!",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertNotIn("password", login.data["user"])
        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + login.data["token"]
        )
        self.assertEqual(
            self.client.get(self.base + "auth/me/").status_code, 200
        )
        self.assertEqual(
            self.client.post(self.base + "auth/logout/").status_code, 204
        )
        self.assertEqual(
            self.client.get(self.base + "auth/me/").status_code, 401
        )

    def test_weak_password_and_bad_login(self):
        self.assertEqual(
            self.client.post(
                self.base + "auth/register/",
                {
                    "username": "weak",
                    "password": "123",
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                self.base + "auth/login/",
                {
                    "username": "alice",
                    "password": "wrong",
                },
            ).status_code,
            400,
        )

    def test_user_cannot_change_workshops(self):
        self.auth()
        detail = f"{self.base}workshops/{self.workshop.pk}/"
        self.assertEqual(
            self.client.post(
                self.base + "workshops/", self.payload()
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(detail, self.payload()).status_code, 403
        )
        self.assertEqual(
            self.client.patch(detail, {"title": "No"}).status_code, 403
        )
        self.assertEqual(self.client.delete(detail).status_code, 403)

    def test_admin_workshop_crud(self):
        self.auth(self.admin)
        response = self.client.post(self.base + "workshops/", self.payload())
        self.assertEqual(response.status_code, 201)
        detail = f"{self.base}workshops/{response.data['id']}/"
        self.assertEqual(
            self.client.put(detail, self.payload(title="New")).status_code, 200
        )
        self.assertEqual(
            self.client.patch(detail, {"title": "Patch"}).status_code, 200
        )
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_duplicate_rolls_back_counter(self):
        self.auth()
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book().status_code, 400)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.reserved, 1)
        self.assertEqual(Booking.objects.count(), 1)

    def test_full_workshop_and_cancellation(self):
        self.workshop.capacity = 1
        self.workshop.save()
        self.auth()
        booking = self.book()
        self.auth(self.other)
        self.assertEqual(self.book().status_code, 400)
        self.auth()
        detail = f"{self.base}bookings/{booking.data['id']}/"
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.reserved, 0)
        self.auth(self.other)
        self.assertEqual(self.book().status_code, 201)

    def test_only_own_bookings_and_nested_workshop(self):
        self.auth()
        booking = self.book()
        self.assertEqual(booking.data["workshop"]["title"], "Python")
        self.auth(self.other)
        listing = self.client.get(self.base + "bookings/")
        self.assertEqual(listing.data["count"], 0)
        detail = f"{self.base}bookings/{booking.data['id']}/"
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.assertEqual(Booking.objects.count(), 1)

    def test_past_and_unknown_workshop(self):
        Workshop.objects.filter(pk=self.workshop.pk).update(
            starts_at=timezone.now() - timedelta(days=1)
        )
        self.auth()
        self.assertEqual(self.book().status_code, 400)
        self.assertEqual(
            self.client.post(
                self.base + "bookings/",
                {
                    "workshop_id": 99999,
                },
            ).status_code,
            400,
        )

    def test_invalid_workshop_and_capacity_reduction(self):
        self.auth(self.admin)
        self.assertEqual(
            self.client.post(
                self.base + "workshops/",
                self.payload(starts_at=timezone.now() - timedelta(days=1)),
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                self.base + "workshops/", self.payload(capacity=0)
            ).status_code,
            400,
        )
        self.auth()
        self.book()
        self.auth(self.other)
        self.book()
        self.auth(self.admin)
        detail = f"{self.base}workshops/{self.workshop.pk}/"
        self.assertEqual(
            self.client.patch(detail, {"capacity": 1}).status_code, 400
        )
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.capacity, 2)

    def test_booking_put_and_patch_move_seats(self):
        self.auth()
        booking = self.book()
        destination = Workshop.objects.create(
            **self.payload(title="Destination")
        )
        detail = f"{self.base}bookings/{booking.data['id']}/"
        moved = self.client.put(detail, {"workshop_id": destination.pk})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.data["id"], booking.data["id"])
        self.assertEqual(moved.data["workshop"]["id"], destination.pk)
        self.workshop.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(
            (self.workshop.reserved, destination.reserved), (0, 1)
        )
        moved_back = self.client.patch(
            detail, {"workshop_id": self.workshop.pk}
        )
        self.assertEqual(moved_back.status_code, 200)
        self.workshop.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(
            (self.workshop.reserved, destination.reserved), (1, 0)
        )

    def test_booking_move_failure_preserves_original(self):
        self.auth()
        booking = self.book()
        detail = f"{self.base}bookings/{booking.data['id']}/"
        full = Workshop.objects.create(**self.payload(capacity=1))
        create_booking(user=self.other, workshop_id=full.pk)
        past = Workshop.objects.create(
            **self.payload(starts_at=timezone.now() - timedelta(seconds=1))
        )
        for destination in [full.pk, past.pk, 99999]:
            with self.subTest(destination=destination):
                self.assertEqual(
                    self.client.patch(
                        detail,
                        {
                            "workshop_id": destination,
                        },
                    ).status_code,
                    400,
                )
        original = Booking.objects.get(pk=booking.data["id"])
        self.workshop.refresh_from_db()
        full.refresh_from_db()
        self.assertEqual(original.workshop_id, self.workshop.pk)
        self.assertEqual((self.workshop.reserved, full.reserved), (1, 1))

    def test_duplicate_move_rolls_back_counters(self):
        self.auth()
        first = self.book()
        destination = Workshop.objects.create(**self.payload())
        second = self.book(destination)
        self.assertEqual(second.status_code, 201)
        detail = f"{self.base}bookings/{first.data['id']}/"
        self.assertEqual(
            self.client.patch(
                detail,
                {
                    "workshop_id": destination.pk,
                },
            ).status_code,
            400,
        )
        self.workshop.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(
            (self.workshop.reserved, destination.reserved), (1, 1)
        )
        self.assertEqual(Booking.objects.count(), 2)

    def test_booking_updates_are_owner_only_even_for_admin(self):
        self.auth()
        booking = self.book()
        detail = f"{self.base}bookings/{booking.data['id']}/"
        for stranger in [self.other, self.admin]:
            self.auth(stranger)
            for method in [self.client.put, self.client.patch]:
                with self.subTest(user=stranger.username, method=method):
                    self.assertEqual(
                        method(
                            detail,
                            {
                                "workshop_id": self.workshop.pk,
                            },
                        ).status_code,
                        404,
                    )

    def test_booking_update_validation_and_noop(self):
        self.auth()
        booking = self.book()
        detail = f"{self.base}bookings/{booking.data['id']}/"
        self.assertEqual(self.client.patch(detail, {}).status_code, 200)
        self.assertEqual(self.client.put(detail, {}).status_code, 400)
        for value in [0, -1, "abc", 1.5]:
            with self.subTest(value=value):
                self.assertEqual(
                    self.client.patch(
                        detail,
                        {
                            "workshop_id": value,
                        },
                    ).status_code,
                    400,
                )
        self.assertEqual(
            self.client.put(
                detail,
                {
                    "workshop_id": self.workshop.pk,
                },
            ).status_code,
            200,
        )
        self.workshop.refresh_from_db()
        self.assertEqual(self.workshop.reserved, 1)

    def test_database_enforces_unique_and_capacity_constraints(self):
        create_booking(user=self.user, workshop_id=self.workshop.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(user=self.user, workshop=self.workshop)
        for changes in [{"capacity": 0}, {"reserved": 3}, {"reserved": -1}]:
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Workshop.objects.filter(pk=self.workshop.pk).update(
                        **changes
                    )

    def test_password_is_hashed_and_duplicate_registration_rejected(self):
        self.assertNotEqual(self.user.password, "ExampleSecret-123")
        self.assertTrue(self.user.check_password("ExampleSecret-123"))
        self.assertEqual(
            self.client.post(
                self.base + "auth/register/",
                {
                    "username": "alice",
                    "password": "Unusual-Password-239!",
                },
            ).status_code,
            400,
        )

    def test_inactive_and_invalid_tokens_are_rejected(self):
        login = self.client.post(
            self.base + "auth/login/",
            {
                "username": "alice",
                "password": "ExampleSecret-123",
            },
        )
        self.client.credentials(
            HTTP_AUTHORIZATION="Token " + login.data["token"]
        )
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(
            self.client.get(self.base + "auth/me/").status_code, 401
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token invalid")
        self.assertEqual(
            self.client.get(self.base + "bookings/").status_code, 401
        )

    def test_ownership_and_occupancy_cannot_be_spoofed(self):
        self.auth()
        response = self.client.post(
            self.base + "bookings/",
            {
                "workshop_id": self.workshop.pk,
                "user": self.other.pk,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Booking.objects.get(pk=response.data["id"]).user, self.user
        )
        self.auth(self.admin)
        response = self.client.post(
            self.base + "workshops/",
            {
                **self.payload(),
                "reserved": 99,
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["reserved"], 0)

    def test_public_catalogue_pagination_and_json(self):
        for i in range(21):
            Workshop.objects.create(**self.payload(title=f"Page {i}"))
        response = self.client.get(self.base + "workshops/")
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.data["count"], 22)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])
        second = self.client.get(self.base + "workshops/?page=2")
        self.assertEqual(len(second.data["results"]), 2)

    def test_workshop_deletion_cascades_bookings(self):
        self.auth()
        booking = self.book()
        self.auth(self.admin)
        detail = f"{self.base}workshops/{self.workshop.pk}/"
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertFalse(
            Booking.objects.filter(pk=booking.data["id"]).exists()
        )

    def test_anonymous_cannot_mutate_workshops_or_access_bookings(self):
        workshop_detail = f"{self.base}workshops/{self.workshop.pk}/"
        self.assertEqual(
            self.client.post(
                self.base + "workshops/",
                {
                    **self.payload(),
                },
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.put(workshop_detail, self.payload()).status_code, 401
        )
        self.assertEqual(
            self.client.patch(workshop_detail, {}).status_code, 401
        )
        self.assertEqual(self.client.delete(workshop_detail).status_code, 401)
        self.assertEqual(
            self.client.get(self.base + "bookings/").status_code, 401
        )

    def test_list_has_no_n_plus_one(self):
        self.auth()
        for i in range(5):
            workshop = Workshop.objects.create(
                **self.payload(title=f"Workshop {i}")
            )
            self.book(workshop)
        # Pagination count + one JOIN, independent of number of bookings.
        with self.assertNumQueries(2):
            response = self.client.get(self.base + "bookings/")
        self.assertEqual(response.data["count"], 5)


class ConcurrentBookingTests(TransactionTestCase):
    def run_concurrently(self, actions):
        """Use independent connections and start all writes simultaneously."""
        barrier = Barrier(len(actions))

        def attempt(action):
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                action()
                return "success"
            except (ValidationError, NotFound):
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(attempt, actions))

    def workshop(self, capacity):
        return Workshop.objects.create(
            title="Concurrent",
            description="Test",
            location="Online",
            starts_at=timezone.now() + timedelta(days=1),
            capacity=capacity,
        )

    def test_parallel_duplicate_booking_rolls_back_counter(self):
        workshop = self.workshop(2)
        user = User.objects.create_user("same_user")

        def action():
            return create_booking(user=user, workshop_id=workshop.pk)

        results = self.run_concurrently([action, action])
        self.assertCountEqual(results, ["success", "rejected"])
        workshop.refresh_from_db()
        self.assertEqual(workshop.reserved, 1)
        self.assertEqual(workshop.bookings.count(), 1)

    def test_parallel_cancellation_frees_exactly_one_seat(self):
        workshop = self.workshop(1)
        user = User.objects.create_user("cancel_user")
        booking = create_booking(user=user, workshop_id=workshop.pk)

        def action():
            return cancel_booking(user=user, booking_id=booking.pk)

        results = self.run_concurrently([action, action])
        self.assertCountEqual(results, ["success", "rejected"])
        workshop.refresh_from_db()
        self.assertEqual(workshop.reserved, 0)
        self.assertEqual(workshop.bookings.count(), 0)

    def test_parallel_moves_compete_for_one_seat(self):
        source = self.workshop(2)
        destination = self.workshop(1)
        alice = User.objects.create_user("move_alice")
        bob = User.objects.create_user("move_bob")
        first = create_booking(user=alice, workshop_id=source.pk)
        second = create_booking(user=bob, workshop_id=source.pk)
        results = self.run_concurrently(
            [
                lambda: update_booking(
                    user=alice,
                    booking_id=first.pk,
                    workshop_id=destination.pk,
                ),
                lambda: update_booking(
                    user=bob,
                    booking_id=second.pk,
                    workshop_id=destination.pk,
                ),
            ]
        )
        self.assertCountEqual(results, ["success", "rejected"])
        for workshop in [source, destination]:
            workshop.refresh_from_db()
            self.assertEqual(workshop.reserved, 1)
            self.assertEqual(workshop.bookings.count(), 1)

    def test_concurrent_move_and_cancellation_leave_no_ghost_seat(self):
        source = self.workshop(1)
        destination = self.workshop(1)
        user = User.objects.create_user("move_cancel")
        booking = create_booking(user=user, workshop_id=source.pk)
        self.run_concurrently(
            [
                lambda: update_booking(
                    user=user,
                    booking_id=booking.pk,
                    workshop_id=destination.pk,
                ),
                lambda: cancel_booking(user=user, booking_id=booking.pk),
            ]
        )
        self.assertFalse(Booking.objects.filter(pk=booking.pk).exists())
        for workshop in [source, destination]:
            workshop.refresh_from_db()
            self.assertEqual(workshop.reserved, 0)

    def test_two_requests_compete_for_one_seat(self):
        workshop = Workshop.objects.create(
            title="Last seat",
            description="Concurrency",
            location="Online",
            starts_at=timezone.now() + timedelta(days=1),
            capacity=1,
        )
        users = [User.objects.create_user(f"parallel{i}") for i in range(2)]
        barrier = Barrier(2)

        def attempt(user):
            close_old_connections()
            barrier.wait(timeout=5)
            try:
                create_booking(user=user, workshop_id=workshop.pk)
                return "created"
            except ValidationError:
                return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, users))
        self.assertCountEqual(results, ["created", "rejected"])
        workshop.refresh_from_db()
        self.assertEqual(workshop.reserved, 1)
        self.assertEqual(workshop.bookings.count(), 1)
