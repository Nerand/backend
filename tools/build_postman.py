"""Generate a repeatable Postman collection with isolated run variables."""

import json
from pathlib import Path

items = []


def request(
    name, method, path, code, *, body=None, token=None, checks=(), pre=()
):
    headers = []
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
    if token:
        headers.append(
            {"key": "Authorization", "value": "Token {{" + token + "}}"}
        )
    req = {"method": method, "header": headers, "url": "{{base_url}}" + path}
    if body is not None:
        req["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, ensure_ascii=False),
        }
    tests = [
        f'pm.test("HTTP {code}", () => pm.response.to.have.status({code}));'
    ]
    tests.extend(checks)
    events = [
        {
            "listen": "test",
            "script": {"type": "text/javascript", "exec": tests},
        }
    ]
    if pre:
        events.insert(
            0,
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": list(pre),
                },
            },
        )
    items.append({"name": name, "request": req, "event": events})


save_token = [
    'pm.collectionVariables.set("user_token", pm.response.json().token);'
]
request(
    "01 Регистрация участника",
    "POST",
    "/auth/register/",
    201,
    body={
        "username": "{{run_user}}",
        "password": "{{user_password}}",
        "role": "admin",
    },
    pre=[
        'const run = Date.now() + "_" + Math.floor(Math.random() * 100000);',
        'pm.collectionVariables.set("run_user", "member_" + run);',
        'pm.collectionVariables.set("other_user", "other_" + run);',
        (
            'pm.collectionVariables.set("future", new Date(Date.now() + 8'
            "64000000).toISOString());"
        ),
        (
            'pm.collectionVariables.set("past", new Date(Date.now() - 864'
            "00000).toISOString());"
        ),
    ],
    checks=[
        (
            'pm.test("Пароль скрыт", () => pm.expect(pm.response.json()).'
            'not.to.have.property("password"));'
        )
    ],
)
request(
    "02 Вход участника",
    "POST",
    "/auth/login/",
    200,
    body={"username": "{{run_user}}", "password": "{{user_password}}"},
    checks=save_token
    + [
        (
            'pm.test("Роль user", () => pm.expect(pm.response.json().user'
            '.role).to.eql("user"));'
        )
    ],
)
request("03 Профиль", "GET", "/auth/me/", 200, token="user_token")
request(
    "04 Вход администратора",
    "POST",
    "/auth/login/",
    200,
    body={"username": "{{admin_username}}", "password": "{{admin_password}}"},
    checks=[
        'pm.collectionVariables.set("admin_token", pm.response.json().token);'
    ],
)
workshop = {
    "title": "Python: практика",
    "description": "Демонстрационный мастер-класс",
    "location": "Онлайн",
    "starts_at": "{{future}}",
    "capacity": 1,
}
request(
    "05 Создать мастер-класс",
    "POST",
    "/workshops/",
    201,
    body=workshop,
    token="admin_token",
    checks=[
        'pm.collectionVariables.set("workshop_id", pm.response.json().id);'
    ],
)
request(
    "06 Публичный список",
    "GET",
    "/workshops/",
    200,
    checks=[
        (
            'pm.test("Пагинация", () => pm.expect(pm.response.json().resu'
            'lts).to.be.an("array"));'
        )
    ],
)
request("07 Публичные детали", "GET", "/workshops/{{workshop_id}}/", 200)
request(
    "08 PUT мастер-класса",
    "PUT",
    "/workshops/{{workshop_id}}/",
    200,
    body=workshop,
    token="admin_token",
)
request(
    "09 PATCH мастер-класса",
    "PATCH",
    "/workshops/{{workshop_id}}/",
    200,
    body={"title": "Обновлённый Python"},
    token="admin_token",
)
request(
    "10 Пользователь не администратор",
    "POST",
    "/workshops/",
    403,
    body=workshop,
    token="user_token",
)
for method in ["PUT", "PATCH", "DELETE"]:
    request(
        f"10{method} Изменение занятия запрещено пользователю",
        method,
        "/workshops/{{workshop_id}}/",
        403,
        body=workshop if method != "DELETE" else None,
        token="user_token",
    )
request(
    "11 Бронь без токена",
    "POST",
    "/bookings/",
    401,
    body={"workshop_id": "{{workshop_id}}"},
)
request(
    "12 Запись участника",
    "POST",
    "/bookings/",
    201,
    body={"workshop_id": "{{workshop_id}}"},
    token="user_token",
    checks=[
        'pm.collectionVariables.set("booking_id", pm.response.json().id);',
        (
            'pm.test("Вложенный мастер-класс", () => pm.expect(pm.respons'
            "e.json().workshop.id).to.eql(Number(pm.collectionVariables.g"
            'et("workshop_id"))));'
        ),
    ],
)
request(
    "13 Повторная запись",
    "POST",
    "/bookings/",
    400,
    body={"workshop_id": "{{workshop_id}}"},
    token="user_token",
)
request("14 Мои бронирования", "GET", "/bookings/", 200, token="user_token")
request(
    "15 Детали моей брони",
    "GET",
    "/bookings/{{booking_id}}/",
    200,
    token="user_token",
)
request(
    "15a Создать занятие для переноса",
    "POST",
    "/workshops/",
    201,
    body={**workshop, "title": "Занятие для переноса"},
    token="admin_token",
    checks=[
        'pm.collectionVariables.set("move_workshop_id", '
        "pm.response.json().id);"
    ],
)
request(
    "15b PUT перенос брони",
    "PUT",
    "/bookings/{{booking_id}}/",
    200,
    body={"workshop_id": "{{move_workshop_id}}"},
    token="user_token",
    checks=[
        'pm.test("Сохранён ID брони", () => '
        "pm.expect(pm.response.json().id).to.eql("
        'Number(pm.collectionVariables.get("booking_id"))));',
        'pm.test("Бронь перенесена", () => '
        "pm.expect(pm.response.json().workshop.id).to.eql("
        'Number(pm.collectionVariables.get("move_workshop_id"))));',
    ],
)
request(
    "15c Старое место свободно",
    "GET",
    "/workshops/{{workshop_id}}/",
    200,
    checks=[
        'pm.test("Место освобождено переносом", () => '
        "pm.expect(pm.response.json().available_seats).to.eql(1));"
    ],
)
request(
    "15d PATCH возврат брони",
    "PATCH",
    "/bookings/{{booking_id}}/",
    200,
    body={"workshop_id": "{{workshop_id}}"},
    token="user_token",
    checks=[
        'pm.test("Возврат на исходное занятие", () => '
        "pm.expect(pm.response.json().workshop.id).to.eql("
        'Number(pm.collectionVariables.get("workshop_id"))));'
    ],
)
request(
    "15e Удалить занятие для переноса",
    "DELETE",
    "/workshops/{{move_workshop_id}}/",
    204,
    token="admin_token",
)
request(
    "16 Второй пользователь",
    "POST",
    "/auth/register/",
    201,
    body={"username": "{{other_user}}", "password": "{{user_password}}"},
)
request(
    "17 Вход второго пользователя",
    "POST",
    "/auth/login/",
    200,
    body={"username": "{{other_user}}", "password": "{{user_password}}"},
    checks=[
        'pm.collectionVariables.set("other_token", pm.response.json().token);'
    ],
)
request(
    "18 Чужие брони скрыты",
    "GET",
    "/bookings/",
    200,
    token="other_token",
    checks=[
        (
            'pm.test("Нет чужих броней", () => pm.expect(pm.response.json'
            "().count).to.eql(0));"
        )
    ],
)
request(
    "19 Чужая бронь недоступна",
    "GET",
    "/bookings/{{booking_id}}/",
    404,
    token="other_token",
)
request(
    "20 Нельзя отменить чужую бронь",
    "DELETE",
    "/bookings/{{booking_id}}/",
    404,
    token="other_token",
)
for method in ["PUT", "PATCH"]:
    request(
        f"20{method} Нельзя перенести чужую бронь",
        method,
        "/bookings/{{booking_id}}/",
        404,
        body={"workshop_id": "{{workshop_id}}"},
        token="other_token",
    )
request(
    "21 Нет свободных мест",
    "POST",
    "/bookings/",
    400,
    body={"workshop_id": "{{workshop_id}}"},
    token="other_token",
)
request(
    "22 Прошедшая дата",
    "POST",
    "/workshops/",
    400,
    body={**workshop, "starts_at": "{{past}}"},
    token="admin_token",
)
request(
    "23 Отмена своей брони",
    "DELETE",
    "/bookings/{{booking_id}}/",
    204,
    token="user_token",
)
request(
    "24 Место освободилось",
    "GET",
    "/workshops/{{workshop_id}}/",
    200,
    checks=[
        (
            'pm.test("Свободно одно место", () => pm.expect(pm.response.j'
            "son().available_seats).to.eql(1));"
        )
    ],
)
request(
    "25 Второй участник занимает место",
    "POST",
    "/bookings/",
    201,
    body={"workshop_id": "{{workshop_id}}"},
    token="other_token",
    checks=[
        'pm.collectionVariables.set("second_booking_id", '
        "pm.response.json().id);"
    ],
)
request(
    "26 Отмена второй брони",
    "DELETE",
    "/bookings/{{second_booking_id}}/",
    204,
    token="other_token",
)
request(
    "27 Удаление мастер-класса",
    "DELETE",
    "/workshops/{{workshop_id}}/",
    204,
    token="admin_token",
)
request("28 Удалённый мастер-класс", "GET", "/workshops/{{workshop_id}}/", 404)
request("29 Выход участника", "POST", "/auth/logout/", 204, token="user_token")
request("30 Токен отозван", "GET", "/auth/me/", 401, token="user_token")
request(
    "31 Выход второго участника",
    "POST",
    "/auth/logout/",
    204,
    token="other_token",
)
request(
    "32 Выход администратора",
    "POST",
    "/auth/logout/",
    204,
    token="admin_token",
)
collection = {
    "info": {
        "name": "Workshop Booking System",
        "schema": (
            "https://schema.getpostman.com/json/"
            "collection/v2.1.0/collection.json"
        ),
    },
    "variable": [
        {"key": k, "value": v}
        for k, v in {
            "base_url": "http://127.0.0.1:8000/api/v1",
            "user_password": "Demo-Participant-394!",
            "admin_username": "admin",
            "admin_password": "",
            "user_token": "",
            "admin_token": "",
        }.items()
    ],
    "item": items,
}
Path("postman/workshop-booking.postman_collection.json").write_text(
    json.dumps(collection, ensure_ascii=False, indent=2) + "\n"
)
