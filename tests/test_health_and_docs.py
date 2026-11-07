import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_ok(api_client):
    response = api_client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_openapi_schema_and_swagger_ui(api_client):
    schema = api_client.get(reverse("schema"), HTTP_ACCEPT="application/json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/payments/click/prepare/" in paths
    assert api_client.get(reverse("swagger-ui")).status_code == 200
