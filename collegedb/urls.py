from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("workflow.urls")),
    path("people/", include("core.urls")),
    path("academics/", include("academics.urls")),
    path("admissions/", include("admissions.urls")),
    path("bursar/", include("student_accounts.urls")),
    path("finaid/", include("finaid.urls")),
    path("hr/", include("hr.urls")),
    path("finance/", include("finance.urls")),
    path("advancement/", include("advancement.urls")),
    path("documents/", include("documents.urls")),
    path("reports/", core_views.reports, name="reports"),
    path("sops/", core_views.sops, name="sops"),
]
