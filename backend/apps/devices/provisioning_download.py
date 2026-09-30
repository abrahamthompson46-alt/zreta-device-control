from django.http import FileResponse, Http404
from django.views import View

from apps.devices.provisioning import dpc_apk_path


class DpcApkDownloadView(View):
    """Public APK for setup-wizard provisioning. Contains no enrollment secret."""

    def get(self, request):
        path = dpc_apk_path()
        if path is None:
            raise Http404("Device Owner APK is not configured.")
        handle = path.open("rb")
        response = FileResponse(handle, content_type="application/vnd.android.package-archive")
        response["Content-Disposition"] = 'attachment; filename="zreta-dpc.apk"'
        return response
