# Ivan Bashkin Library API

## Назначение
Сервис предоставляет REST API для учета читателей, книжного фонда и выдач в библиотеке. Он поддерживает авторизацию, оформление и возврат экземпляров, фильтрацию истории и сводные показатели.

## Требования
- Python 3.11 или новее
- PostgreSQL 16
- Docker и Docker Compose

## Установка и запуск
```bash
git clone <repository-url> ivan_bashkin
cd ivan_bashkin
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Linux/macOS/WSL:
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose up -d
alembic upgrade head
python seed.py --type=small
uvicorn app.main:app --reload
```
Для большого набора данных используйте `python seed.py --type=large`. Тестовая учетная запись после заполнения: `admin` / `admin123`.

## Переменные окружения
| Переменная | Значение / источник | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql://app:changeme@localhost:5432/ivan_bashkin` | Подключение к PostgreSQL |
| `SECRET_KEY` | В `.env.example`: `replace-this-with-a-long-random-secret`; без переменной: `development-only-secret-key-change-me` | Подпись JWT; задайте собственное случайное значение |

## Проверка работоспособности и тесты
Из корневой директории проекта после установки зависимостей запустите `pytest`. Файл `pytest.ini` автоматически настраивает поиск модуля `app`, поэтому `PYTHONPATH` указывать не нужно. Интерактивная документация API доступна по адресу `/docs`.

## Программный интерфейс
Все пути, кроме входа, требуют заголовок `Authorization: Bearer <token>`.

| Метод/путь | Параметры | Ответ | Ошибки |
|---|---|---|---|
| `POST /api/v1/auth/login` | Form (`application/x-www-form-urlencoded`): `username`, `password` | `200`: JWT `access_token` | `401`, `422` |
| `GET /api/v1/loans` | `page` (>=1), `size` (1..100), `status` (`active`/`returned`/`overdue`), `reader_id` | `200`: `items`, `page`, `size`, `total` | `401`, `422` |
| `GET /api/v1/loans/{id}` | ID выдачи | `200`: выдача, читатель, экземпляр и книга | `401`, `404`, `422` |
| `POST /api/v1/loans` | JSON: `reader_id`, `copy_id`, опционально `due_date` | `201`: созданная выдача | `401`, `404`, `409`, `422` |
| `POST /api/v1/loans/{id}/return` | ID выдачи | `200`: дата возврата, дни просрочки, штраф | `401`, `404`, `409`, `422` |
| `GET /api/v1/summary` | Нет | `200`: экземпляры на руках, просрочки, топ-10 книг | `401` |

После запуска сервиса измерьте производительность командой `python benchmark.py --requests 30 --warmup 5`. Скрипт отдельно выводит медиану и p95 для авторизации (`POST /api/v1/auth/login`) и получения списка выдач (`GET /api/v1/loans`). Для входа используется тестовая учетная запись `admin` / `admin123`, создаваемая командой `seed.py`.