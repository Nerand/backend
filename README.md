# Workshop Booking System

Система бронирования мастер-классов: Django 5.2, Django REST Framework,
SQLite, токенная аутентификация. Клиент для проверки API — Postman.
Одна бронь занимает одно место. Пользователь просматривает, переносит и отменяет
только свои брони; администратор управляет мастер-классами.

## Материалы для сдачи

- [Видеопрезентация — MP4, 5:04](presentation/video/workshop-booking-voiceover-fixed.mp4).
- [Презентация — PDF](presentation/workshop-booking-reviewed.pdf).
- [Коллекция Postman](postman/workshop-booking.postman_collection.json).

В видео использованы слайды и исходный голос автора.

## Быстрый запуск через Docker

Нужны Docker Engine / Docker Desktop и Docker Compose v2.

```sh
cp .env.example .env
# Задайте SECRET_KEY и ADMIN_PASSWORD в .env.
docker compose up --build -d
docker compose exec web python manage.py create_admin
```

API: http://localhost:8000/api/v1/workshops/ . Миграции применяются при старте,
база сохраняется в именованном томе `workshop_data`. Команда `create_admin`
читает `ADMIN_USERNAME` и `ADMIN_PASSWORD` из окружения контейнера; существующую
учётную запись не меняет. Повторно после каждого запуска вызывать её не нужно.

```sh
docker compose logs -f web
docker compose exec web python manage.py check
docker compose exec web python manage.py test
docker compose down
```

`down` сохраняет данные. Для внешнего развёртывания задайте свой `ALLOWED_HOSTS`,
секрет и HTTPS на reverse proxy; учебная конфигурация публикует HTTP на порту 8000.
Токен DRF не истекает автоматически; выход отзывает текущий токен.

## Локальный запуск

Python 3.11 или новее; `.env` локально автоматически не загружается.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
export ADMIN_USERNAME=admin
# Введите пароль без записи в историю shell:
read -s ADMIN_PASSWORD
export ADMIN_PASSWORD
python manage.py create_admin
python manage.py runserver
```

По умолчанию база — `db.sqlite3`, можно изменить через `DB_PATH`.
При `DEBUG=0` разрешены `localhost`, `127.0.0.1`, `testserver`;
значение переопределяется переменной `ALLOWED_HOSTS` (хосты через запятую).

## API

Префикс всех маршрутов — `/api/v1/`. Тело запросов и ответов — JSON.
Для закрытых маршрутов: `Authorization: Token <token>`.

| Метод | Маршрут | Доступ и назначение |
|---|---|---|
| POST | `auth/register/` | Публичная регистрация, всегда роль `user` |
| POST | `auth/login/` | Имя и пароль → токен и профиль |
| POST | `auth/logout/` | Авторизованный: отзыв токена, 204 |
| GET | `auth/me/` | Авторизованный: профиль |
| GET | `workshops/` | Публичный список |
| GET | `workshops/{id}/` | Публичные детали |
| POST | `workshops/` | Только `admin`: создание |
| PUT, PATCH | `workshops/{id}/` | Только `admin`: изменение |
| DELETE | `workshops/{id}/` | Только `admin`: удаление, 204 |
| POST | `bookings/` | Авторизованный: запись |
| GET | `bookings/` | Только собственные брони |
| GET | `bookings/{id}/` | Только собственная бронь |
| PUT, PATCH | `bookings/{id}/` | Перенос своей брони на другой мастер-класс |
| DELETE | `bookings/{id}/` | Отмена собственной брони, 204 |

Для переноса отправьте PUT/PATCH `bookings/{id}/` с новым `workshop_id`.
Идентификатор брони сохраняется. Старое место освобождается и новое занимается
в одной транзакции. Если новое занятие началось, заполнено, отсутствует или
на него уже есть ваша бронь, перенос возвращает 400, исходная бронь сохраняется.
PUT требует `workshop_id`, PATCH допускает пустое тело как отсутствие изменений.
Ни пользователь, ни администратор не могут менять чужие брони. Удаление
мастер-класса каскадно удаляет относящиеся к нему брони.

Регистрация: `{"username":"alice","password":"Unusual-Password-239!"}`.
Вход: те же поля. Email при регистрации необязателен. Назначить роль `admin`
через регистрацию нельзя; пароли хешируются средствами Django и не выдаются API.

Создание мастер-класса (дата должна быть в будущем):

```json
{
  "title": "Основы Python",
  "description": "Практический мастер-класс",
  "location": "Онлайн",
  "starts_at": "2027-12-10T15:00:00+03:00",
  "capacity": 10
}
```

Бронирование: `{"workshop_id": 1}`. Поля `user` и `reserved` не принимаются
от клиента. Пользователь определяется по токену. Ответ включает `workshop`
с датой, местом, вместимостью и `available_seats`.

Списки пагинированы: `count`, `next`, `previous`, `results`, по 20 записей,
следующая страница `?page=2`. Ошибки: 400 — неверные данные, повторная запись,
прошедшая дата или отсутствие мест; 401 — нет действительного токена;
403 — недостаточно прав; 404 — объект отсутствует или чужая бронь.
Отсутствующий `workshop_id` при записи возвращает 400 как ошибка поля.

## Postman

Импортируйте `postman/workshop-booking.postman_collection.json`.
В переменных коллекции задайте `admin_username`, `admin_password` и при
необходимости `base_url`. Запускайте всю коллекцию по порядку через Runner.
Не экспортируйте заполненные токены и пароли в публичный репозиторий.

42 запроса покрывают все бизнес-маршруты и поддерживаемые CRUD-методы,
положительные и отрицательные сценарии.
Pre-request script генерирует уникальные имена и будущую дату; токены,
идентификаторы мастер-класса и брони сохраняются автоматически. Скрипты
проверяют HTTP-коды, отсутствие пароля, роль, вложенные данные, изоляцию
броней, перенос и освобождение места. Запуск создаёт двух пользователей
и два мастер-класса; созданные брони и мастер-классы удаляются в конце,
пользователи остаются.
Ошибки в Postman видны в статусе ответа и вкладке Test Results, выполнение
запроса — в интерфейсе клиента; отдельного веб-интерфейса нет.

При установленном Node.js можно запустить ту же коллекцию через Newman:

```sh
npx newman run postman/workshop-booking.postman_collection.json \
  --env-var "admin_password=$ADMIN_PASSWORD"
```

## Архитектура и целостность данных

- `config/` — настройки, маршруты, WSGI.
- `booking/models.py` и `migrations/` — User с ролью, Workshop, Booking и схема БД.
- `booking/views.py` — HTTP-контроллеры; `permissions.py` — роли и права.
- `booking/serializers.py` — JSON, валидация, вложенные данные мастер-класса.
- `booking/services.py` — транзакционные операции записи, переноса и отмены.
- `booking/tests.py` — интеграционные тесты API, параллельной записи и запросов ORM.
- `tools/build_postman.py` — воспроизводимая генерация коллекции.

Связи: User 1:N Booking и Workshop 1:N Booking. Ограничение UNIQUE на
`(user, workshop)` исключает повторную бронь. CHECK требует `capacity >= 1`
и `reserved <= capacity`. Запись использует условный UPDATE со счётчиком
мест и F-выражением внутри транзакции, затем создаёт бронь. При ошибке
вставки вся транзакция откатывается. Отмена освобождает место в той же
транзакции. Перенос атомарен: при ошибке откатываются оба счётчика.
Изменение вместимости также проверяет число занятых мест
непосредственно при UPDATE. Счётчик изменяется только сервисами: прямые
правки Booking через ORM/SQL в обход сервисов не поддерживаются.

Записаться после начала мастер-класса нельзя. При создании/изменении даты
сериализатор допускает только будущую дату. Собственные брони фильтруются
на уровне queryset; `select_related("workshop")` загружает мастер-классы
одним JOIN. Тест списка проверяет два SQL-запроса: COUNT для пагинации
и SELECT с JOIN для всей страницы.
Это запросы данных страницы. При реальной TokenAuthentication добавляется
один запрос авторизации: для проверенной непустой страницы всего три.
Дополнительный SQL-запрос на каждую бронь не возникает.

SQLite подходит для учебного проекта; одновременно записывающие транзакции
выполняются последовательно с ожиданием блокировки до 20 секунд. При большой
нагрузке нужно оценить переход на PostgreSQL и обработку исчерпания ожидания.
Масштабирование на несколько машин с отдельными SQLite-файлами не предусмотрено.

## Проверки

```sh
pip install -r requirements-dev.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test -v 2
ruff check .
ruff format --check .
```

Тестовая база — отдельный `test.sqlite3` рядом с основной базой
(в Docker — `/data/test.sqlite3`), удаляется после завершения.
Файловая база нужна для проверки реального механизма блокировок SQLite;
in-memory SQLite использует другой механизм блокировки таблиц.
Проверка стиля Ruff охватывает в том числе миграции; длина строки — 79 символов.

Документация используемых механизмов:
[Django constraints](https://docs.djangoproject.com/en/5.2/ref/models/constraints/),
[DRF TokenAuthentication](https://www.django-rest-framework.org/api-guide/authentication/#tokenauthentication).
