from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("sw.js", core_views.ServiceWorkerView.as_view(), name="service_worker"),
    path("manifest.webmanifest", core_views.ManifestView.as_view(), name="manifest"),
    path("conturi/", include("apps.accounts.urls")),
    path("notite/", include("apps.notes.urls")),
    path("programari/", include("apps.scheduling.urls")),
    path("documente/", include("apps.documents.urls")),
    path("cauta/", include("apps.search.urls")),
    path("asistent/", include("apps.assistant.urls")),
    path("rezumat/", include("apps.daily_brief.urls")),
    path("notificari/", include("apps.notifications.urls")),
    path("integrari/", include("apps.integrations.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
