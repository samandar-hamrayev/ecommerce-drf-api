# E-Commerce DRF API

A RESTful e-commerce backend API built with **Django REST Framework**, covering the full shopping flow — from product browsing to order management.

## Features

- Product catalog with categories
- Shopping cart management
- Order creation and tracking
- Product reviews and ratings
- User authentication and profiles
- Django admin panel

## Tech Stack

- Python 3.9+ · Django 4+ · Django REST Framework
- PostgreSQL
- JWT Authentication

## Setup

### 1. Clone

```bash
git clone https://github.com/samandar-hamrayev/ecommorce-drf-api.git
cd ecommorce-drf-api
```

### 2. Install dependencies

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=postgres://user:password@localhost:5432/ecommerce_db
```

### 4. Run migrations

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## API Endpoints

| Resource | Base Endpoint |
|----------|---------------|
| Products | `/api/products/` |
| Carts | `/api/carts/` |
| Orders | `/api/orders/` |
| Reviews | `/api/reviews/` |
| Users | `/api/users/` |

## Project Structure

```
ecommorce-drf-api/
├── config/      # Django settings and URL config
├── products/    # Product catalog
├── carts/       # Shopping cart
├── orders/      # Order management
├── reviews/     # Product reviews
├── users/       # User profiles and authentication
└── manage.py
```

## License

MIT — [Samandar Hamrayev](https://github.com/samandar-hamrayev)
