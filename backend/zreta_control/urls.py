from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.accounts.api_urls")),
    path("api/v1/", include("apps.devices.api_urls")),
    path("api/v1/", include("apps.policies.api_urls")),
    path("api/v1/", include("apps.audit.api_urls")),
]
