from django.urls import path

from student_accounts import views

urlpatterns = [
    path("accounts/", views.AccountListView.as_view(), name="bursar_accounts"),
    path("accounts/<int:person_id>/", views.AccountDetailView.as_view(), name="bursar_account"),
]
