# E-commerce DRF API

**A production-style e-commerce backend on Django REST Framework, with Click and Payme payment integrations for Uzbekistan.**

[![CI](https://github.com/samandar-hamrayev/ecommerce-drf-api/actions/workflows/ci.yml/badge.svg)](https://github.com/samandar-hamrayev/ecommerce-drf-api/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/django-5.2-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.16+-A30000)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

The API covers the whole shopping flow: catalog, cart, checkout, order lifecycle, verified-buyer reviews
and online payment. Checkout is **transactional and safe under concurrency**: product rows are locked,
prices are snapshotted, and nothing is written if any step fails. The `payments` app implements the
**Click SHOP-API** (Prepare/Complete) and the **Payme Merchant API** (JSON-RPC) merchant callbacks, with
signature/auth checks, the providers' error codes and idempotent handling of retries.

<!--
Screenshot placeholder - add an image of the Swagger UI here, e.g.:
<p align="center"><img src="docs/swagger.png" alt="Swagger UI" width="800"></p>
-->

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Design decisions](#design-decisions)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Payments](#payments)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

## Features

- **Auth**: e-mail registration with a one-time confirmation code, JWT access/refresh tokens (SimpleJWT),
  refresh rotation and logout through a blacklist, password change and reset. The reset endpoint gives the
  same answer for every e-mail, so it can't be used to find out who has an account.
- **Catalog**: categories, brands and products, plus dynamic attributes (`text` / `number` / `choice`)
  that are validated against their definitions. Products have images, and each product can have only one
  primary image. Reads are public; only staff can write.
- **Search, filtering and ordering**: filter by category, brand, price range, stock, discount and minimum
  rating; keyword search over names and descriptions; ordering by price, date, rating and other fields; page-number
  pagination with a `page_size` the client can set.
- **No N+1 queries**: `select_related`, `prefetch_related` / `Prefetch` and DB-level `Avg`/`Count`
  annotations. Tests check this: the product list and order list run a fixed number of queries.
- **Cart**: created the first time it's used. Adding the same product twice merges the quantities, and
  the stock check is a soft one (nothing is reserved until checkout).
- **Orders**: checkout runs in one transaction with `SELECT ... FOR UPDATE` and saves a price snapshot.
  An explicit state machine (`pending → paid → shipped → delivered`, plus `cancelled`) restocks items
  when an order is cancelled.
- **Reviews**: only buyers whose order was delivered can review, one review per user and product, and
  only the author can edit or delete it.
- **Payments**: Click Prepare/Complete and the Payme Merchant API, plus an endpoint that builds the
  hosted-checkout URL for an order.
- **Operations**: OpenAPI 3 schema (drf-spectacular) with Swagger UI and ReDoc, a `/health/` endpoint
  that also checks the database, Django admin with inlines, throttling, and settings from environment
  variables.
- **Quality**: 130 pytest tests (96% coverage), ruff, pre-commit and gitleaks, a GitHub Actions CI that
  runs on PostgreSQL, and a slim Docker image that runs as a non-root user.

## Architecture

### Data model

```mermaid
erDiagram
    USER ||--o| CART : owns
    USER ||--o{ ORDER : places
    USER ||--o{ REVIEW : writes
    USER ||--o| EMAIL_VERIFICATION : has
    CART ||--o{ CART_ITEM : contains
    PRODUCT ||--o{ CART_ITEM : "added as"
    CATEGORY ||--o{ PRODUCT : groups
    BRAND |o--o{ PRODUCT : makes
    PRODUCT ||--o{ PRODUCT_IMAGE : has
    PRODUCT ||--o{ PRODUCT_FIELD_VALUE : has
    PRODUCT_FIELD ||--o{ PRODUCT_FIELD_VALUE : defines
    PRODUCT ||--o{ REVIEW : receives
    ORDER ||--|{ ORDER_ITEM : contains
    PRODUCT |o--o{ ORDER_ITEM : "snapshot of"
    ORDER ||--o{ PAYMENT : "paid by"

    PRODUCT {
        decimal price
        smallint discount "0-90 %"
        int stock
        bool is_active
    }
    ORDER {
        string status "pending|paid|shipped|delivered|cancelled"
        decimal total_amount
        datetime paid_at
    }
    ORDER_ITEM {
        string product_name "snapshot"
        decimal unit_price "snapshot"
        int quantity
    }
    PAYMENT {
        string provider "click|payme"
        string external_id "unique per provider"
        decimal amount
        smallint state "1, 2, -1, -2"
        smallint reason
        bigint provider_time "ms"
    }
    REVIEW {
        smallint rating "1-5"
        text comment
    }
```

### Checkout and Click payment flow

```mermaid
sequenceDiagram
    autonumber
    actor C as Customer
    participant API as DRF API
    participant DB as PostgreSQL
    participant Click as Click

    C->>API: POST /api/orders/ {shipping_address}
    API->>DB: BEGIN, lock cart items + products FOR UPDATE
    API->>DB: check stock, decrement, snapshot prices, create Order(pending), clear cart
    API->>DB: COMMIT
    API-->>C: 201 Order
    C->>API: POST /api/payments/checkout/ {order, provider: "click"}
    API-->>C: https://my.click.uz/services/pay?...&transaction_param=<order id>
    C->>Click: pays on the hosted page
    Click->>API: POST /api/payments/click/prepare/ (action=0, sign_string)
    API->>API: verify md5 sign, service_id, order, amount
    API->>DB: Payment(state=CREATED), unique (provider, click_trans_id)
    API-->>Click: {error: 0, merchant_prepare_id}
    Click->>API: POST /api/payments/click/complete/ (action=1, merchant_prepare_id, sign_string)
    API->>DB: lock Order + Payment, Payment PERFORMED, Order PAID (one transaction)
    API-->>Click: {error: 0, merchant_confirm_id}
    Note over Click,API: Retries are idempotent: a repeated Prepare returns the same id,<br/>a repeated Complete returns -4 "Already paid" without side effects.
```

The views are thin. Business rules live in `orders/services.py` (checkout and state machine) and in the
payment providers (`payments/providers/*`). Providers only change order state through
`payments/services.py`.

## Design decisions

| Decision | Why |
|---|---|
| **`SELECT ... FOR UPDATE` on products during checkout**, locked in primary-key order | Two customers buying the last item at the same moment can't both succeed. Locking in a fixed order prevents deadlocks. A PostgreSQL test with two threads checks this. |
| **Stock is reserved at checkout, not when items go into the cart** | A cart is a wish list. Reserving stock there lets abandoned carts block real buyers. The cart only does a soft check for UX. |
| **Price and name snapshot on `OrderItem`** (`unit_price`, `product_name`) | What the customer was charged must never change when the catalog is edited later. `OrderItem.product` is `SET_NULL`, so order history survives a product being deleted. |
| **Whole checkout in one `transaction.atomic()`** | The order, its items, the stock decrements and clearing the cart either all happen or none do. Tests inject a failure in the middle of checkout to prove this. |
| **Explicit order state machine** (`Order.TRANSITIONS`, `orders.services.change_status`) | Illegal jumps (for example `delivered → cancelled`) are rejected in one place, and side effects (restock, timestamps) can't be forgotten. |
| **Idempotent payment callbacks**: `UniqueConstraint(provider, external_id)` plus state checks | Providers retry when a request times out. A retry must return the same answer and never charge or ship twice. The DB constraint guarantees this even under concurrent retries. |
| **One `Payment` table for both providers**, using Payme's numeric states (1, 2, -1, -2) | Payme's states cover everything Click needs, so there is one audit trail and one admin view. Adding a provider means adding a class, not a new schema. |
| **Signature check with `hmac.compare_digest`** over the raw request strings | Click signs the exact strings it sent (for example `"1000.00"` and `"1000"` give different hashes), and a constant-time comparison avoids timing side channels. |
| **Callbacks without user auth, CSRF or throttling** | These calls come from the providers' servers, not from browsers. They are authenticated by md5 signature (Click) or HTTP Basic (Payme) instead. |
| **Money as `Decimal`, Payme amounts in tiyin as `int`** | No floating-point rounding errors. Conversion happens in one helper (`PaymentProvider.to_tiyin`). |
| **Business logic in `services.py` and providers, thin views** | The rules can be reused from the API, admin and payment callbacks, and are easy to unit-test. |
| **`NullsLastOrderingFilter`** | PostgreSQL puts `NULL` first in `DESC` order, so `?ordering=-average_rating` would otherwise show unrated products first. |
| **Secrets and config from the environment** (django-environ) | The same image runs in dev, CI and production. Credentials are never committed (`.env` is git-ignored and gitleaks runs in CI and pre-commit). |

## Tech stack

| Area | Tools |
|---|---|
| Language / framework | Python 3.12, Django 5.2 LTS, Django REST Framework |
| Auth | djangorestframework-simplejwt (rotation + blacklist) |
| API docs | drf-spectacular (OpenAPI 3, Swagger UI, ReDoc) |
| Querying | django-filter, drf-nested-routers |
| Database | PostgreSQL 16 (SQLite fallback for quick local runs) |
| Serving | gunicorn, WhiteNoise for static files |
| Quality | pytest, pytest-django, pytest-cov, ruff, pre-commit, gitleaks |
| Delivery | Docker (multi-stage, non-root, healthcheck), docker compose, GitHub Actions, Dependabot |

## Quick start

### With Docker (recommended)

```bash
git clone https://github.com/samandar-hamrayev/ecommerce-drf-api.git
cd ecommerce-drf-api
cp .env.example .env            # set SECRET_KEY; add Click/Payme credentials if you have them
docker compose up -d --build    # web + PostgreSQL; migrations run on start
docker compose exec web python manage.py createsuperuser
```

- Swagger UI: <http://localhost:18300/api/docs/>
- ReDoc: <http://localhost:18300/api/redoc/>
- Admin: <http://localhost:18300/admin/>
- Health: <http://localhost:18300/health/>

Set `WEB_PORT` to change the host port, and run `docker compose down -v` to stop and remove the volumes.

### Locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set SECRET_KEY; remove DATABASE_URL to use SQLite
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

With the default console e-mail backend, registration codes are printed in the server log.
Run `make help` to see the shortcuts (`make test`, `make lint`, `make up`, and so on).

## Configuration

All settings come from environment variables (or `.env`). `.env.example` lists every one of them.

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Django secret key |
| `DEBUG` | `False` | Debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | Origins for admin/session forms behind a proxy |
| `DATABASE_URL` | `sqlite:///db.sqlite3` | e.g. `postgres://user:pass@host:5432/db` |
| `CONN_MAX_AGE` | `60` | Persistent DB connection lifetime (seconds) |
| `TIME_ZONE` | `Asia/Tashkent` | Server time zone |
| `SECURE_SSL_REDIRECT` | `False` | Redirect HTTP to HTTPS |
| `PAGE_SIZE` | `20` | Default page size (clients can pass `page_size`, max 100) |
| `THROTTLE_ANON` / `THROTTLE_USER` | `100/min` / `1000/min` | DRF throttling rates |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | `30` / `7` | Token lifetimes |
| `EMAIL_BACKEND` | console backend | Use `django.core.mail.backends.smtp.EmailBackend` for real mail |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | | SMTP settings |
| `MEDIA_ROOT` | `./media` | Uploaded files location |
| `LOG_LEVEL` | `INFO` | Root log level |
| `CLICK_SERVICE_ID`, `CLICK_MERCHANT_ID`, `CLICK_SECRET_KEY` | *(empty)* | Issued by Click when you connect |
| `PAYME_MERCHANT_ID`, `PAYME_KEY` | *(empty)* | Issued by Payme (cashbox id and key) |
| `PAYME_ACCOUNT_FIELD` | `order_id` | Name of the `account` field configured in the Payme cabinet |
| `PAYME_CHECKOUT_URL` | `https://checkout.paycom.uz` | Use `https://checkout.test.paycom.uz` for the sandbox |
| `PAYMENT_RETURN_URL` | *(empty)* | Default redirect after payment |
| `POSTGRES_PASSWORD`, `WEB_PORT` | `ecommerce`, `18300` | docker compose only |

## API overview

All endpoints are under `/api/`. The full interactive reference is at `/api/docs/`.

| Area | Method and path | Access |
|---|---|---|
| Auth | `POST auth/register/`, `POST auth/confirm-email/` | public |
| | `POST auth/login/`, `POST auth/token/refresh/`, `POST auth/logout/` | public / user |
| | `GET PATCH auth/me/`, `POST auth/password/change/` | user |
| | `POST auth/password/reset/`, `POST auth/password/reset/confirm/` | public |
| Users | `GET users/`, `GET PATCH DELETE users/{id}/` | staff |
| Catalog | `GET categories/`, `GET brands/`, `GET products/`, `GET products/{id}/` | public |
| | `POST PATCH PUT DELETE` on the above | staff |
| | `products/{id}/images/`, `products/{id}/field-values/`, `product-fields/` | read public, write staff |
| Cart | `GET DELETE cart/`, `GET POST cart/items/`, `PATCH DELETE cart/items/{id}/` | user (own cart only) |
| Orders | `GET POST orders/` (POST = checkout), `GET orders/{id}/` | user (own) / staff (all) |
| | `POST orders/{id}/cancel/` | owner while pending, or staff |
| | `POST orders/{id}/status/` | staff |
| Reviews | `GET reviews/`, `POST reviews/`, `PATCH DELETE reviews/{id}/` | read public, write verified buyer / author |
| Payments | `POST payments/checkout/` | user (own pending order) |
| | `POST payments/click/prepare/`, `POST payments/click/complete/` | Click (md5 signature) |
| | `POST payments/payme/` | Payme (HTTP Basic) |
| Ops | `GET /health/`, `GET /api/schema/`, `/api/docs/`, `/api/redoc/`, `/admin/` | public / staff |

Example product query:
`GET /api/products/?category=1&price_min=100000&in_stock=true&search=phone&ordering=-average_rating&page_size=10`

## Payments

Both integrations are in `payments/providers/`. They share the `PaymentProvider` interface
(`is_configured()`, `build_checkout_url()`) and the `Payment` model. To start a payment, the client calls
`POST /api/payments/checkout/ {"order": <id>, "provider": "click" | "payme"}` and redirects the customer
to the returned `checkout_url`.

### Click SHOP-API

Click sends `application/x-www-form-urlencoded` POSTs, and the response is always HTTP 200 JSON.
`merchant_trans_id` is the order id.

```
Prepare  sign_string = md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id
                           + amount + action + sign_time)
Complete sign_string = md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id
                           + merchant_prepare_id + amount + action + sign_time)
```

| Code | Meaning | When this API returns it |
|---|---|---|
| `0` | Success | |
| `-1` | SIGN CHECK FAILED | md5 mismatch |
| `-2` | Incorrect parameter amount | amount differs from the order total or the prepared amount, or isn't a valid positive number |
| `-3` | Action not found | `action` is not 0/1, or doesn't match the endpoint |
| `-4` | Already paid | the order or transaction is already paid, or Complete is repeated |
| `-5` | User does not exist | the order doesn't exist |
| `-6` | Transaction does not exist | `merchant_prepare_id` is unknown or belongs to another `click_trans_id` or order |
| `-7` | Failed to update user | unexpected error while saving (everything is rolled back) |
| `-8` | Error in request from click | a required field is missing, or `service_id` is wrong |
| `-9` | Transaction cancelled | Complete arrived with `error < 0` (the transaction is cancelled and saved), or the order or transaction was already cancelled |

### Payme Merchant API

JSON-RPC 2.0 on a single URL. Requests are authenticated with `Authorization: Basic base64("Paycom:" + PAYME_KEY)`.
Amounts are in tiyin, and times are milliseconds. The implemented methods are `CheckPerformTransaction`,
`CreateTransaction`, `PerformTransaction`, `CancelTransaction`, `CheckTransaction` and `GetStatement`.

- A created transaction expires after **12 hours** (43 200 000 ms). After that, `Perform` and `Create`
  cancel it with reason `4` and answer `-31008`.
- An order can have only one live (state 1) Payme transaction at a time.
- `CancelTransaction` on a performed transaction (state 2 → -2) cancels the order and restocks the items.
  If the order has already shipped or been delivered, it returns `-31007`.
- Repeating `Create`, `Perform` or `Cancel` returns the stored result (idempotent).

| Code | Meaning |
|---|---|
| `-32504` | Insufficient privilege (bad or missing Basic auth) |
| `-32700` / `-32600` / `-32601` / `-32400` | Parse error / invalid request or param types / unknown method / system error |
| `-31001` | Wrong amount |
| `-31003` | Transaction not found |
| `-31007` | Order already shipped or delivered, can't cancel |
| `-31008` | Operation can't be performed (wrong state, expired, or order no longer payable) |
| `-31050` | Order not found (`data` = account field name) |
| `-31051` | Order not available for payment (already paid or cancelled, or waiting on another transaction) |

### Implementation notes and assumptions

These choices come from the public documentation and Click's reference integration, and should be checked
against your merchant agreement:

- **Click**: a repeated Complete answers `-4` (as in Click's reference implementation) instead of
  replaying success. A cancelled order answers `-9`. Amounts are compared exactly to 2 decimal places.
  Click's source IP addresses are not allow-listed in the app; do that at the proxy or firewall.
- **Payme**: `-31051` is a merchant-defined code in the account-error range (-31050..-31099) that
  Payme reserves for merchants. The `ChangePassword` method is not implemented (the key is managed through
  the environment), so it returns `-32601`. `receivers` (split payments) are not used. `GetStatement`
  filters by Payme's own `time`.
- When staff cancel a paid order through `orders/{id}/status/`, the items are restocked, but the API
  **does not** trigger a refund at the provider.

## Testing

```bash
pytest                      # 130 tests
pytest --cov                # coverage report (96%)
make check                  # lint + Django checks + migration check + tests
```

| Suite | What it covers |
|---|---|
| `test_auth.py` | registration and confirmation codes, JWT login/refresh/logout (blacklist), blocking self-promotion to staff, staff-only user admin, password change and reset without leaking accounts |
| `test_products.py` | public read / staff write, validation, filters, search, ordering, pagination, rating annotations, **N+1 guard** (`django_assert_max_num_queries`), images, dynamic attributes, PROTECT on categories |
| `test_cart.py` | merging items, quantity and stock validation, no stock reservation, isolation between users |
| `test_orders.py` | totals and discount snapshot, **rollback on a failure mid-checkout**, insufficient stock, ordering only from your own cart, privacy, state machine, restocking, **concurrent checkout of the last item** (PostgreSQL only) |
| `test_reviews.py` | verified-buyer rule, one review per product, rating range, author-only edits |
| `test_payments_click.py` | md5 formula, tampering, every Click error code, idempotent retries, cancellation persisted on `error<0`, double-payment protection |
| `test_payments_payme.py` | Basic auth, JSON-RPC errors, every method, 12 h timeout with reason 4, refunds, idempotency, `GetStatement` window |

CI runs the suite against PostgreSQL 16, so the `select_for_update` concurrency test runs there.
With SQLite that one test is skipped.

## Project structure

```
ecommerce-drf-api/
├── config/            # settings (django-environ), URLs, WSGI/ASGI
├── core/              # health check, pagination, shared permissions, nulls-last ordering
├── users/             # custom e-mail user, registration/confirmation, JWT auth views
├── products/          # categories, brands, products, images, dynamic attributes
├── carts/             # per-user cart and items
├── orders/            # Order/OrderItem, services.py (checkout + state machine)
├── reviews/           # verified-buyer reviews
├── payments/
│   ├── providers/     # base.py (interface), click.py, payme.py
│   ├── services.py    # provider → order state bridge
│   └── models.py      # Payment (shared by providers)
├── tests/             # pytest suite
├── docker/            # container entrypoint (migrations on start)
├── Dockerfile         # multi-stage, non-root, gunicorn, HEALTHCHECK
├── docker-compose.yml # web + postgres with healthchecks
├── .github/           # CI workflow, Dependabot
├── pyproject.toml     # ruff, pytest, coverage config
└── Makefile
```

## Roadmap

- [ ] Celery + Redis to send e-mail asynchronously and to cancel unpaid orders that have expired
- [ ] Automatic refunds at the provider when staff cancel a paid order
- [ ] Atmos and Multicard providers behind the same `PaymentProvider` interface
- [ ] Payme `ChangePassword` with the key stored in the database
- [ ] Coupons and promo codes
- [ ] S3-compatible media storage
- [ ] Structured JSON logging and Sentry

## License

[MIT](LICENSE) © 2026 Samandar Hamrayev
