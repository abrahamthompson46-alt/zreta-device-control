from django.urls import path

from . import api

urlpatterns = [
    path("audit-events", api.AuditEventListAPIView.as_view(), name="api-audit-events"),
]
