from django.contrib import admin
from django.urls import include, path

from apps.devices.provisioning_download import DpcApkDownloadView

urlpatterns = [
    path("dpc.apk", DpcApkDownloadView.as_view(), name="dpc-apk"),
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.accounts.api_urls")),
    path("api/v1/", include("apps.devices.api_urls")),
    path("api/v1/", include("apps.policies.api_urls")),
    path("api/v1/", include("apps.audit.api_urls")),
]
