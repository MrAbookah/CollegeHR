from django.urls import path

from finaid import views

urlpatterns = [
    path("awards/", views.AwardListView.as_view(), name="finaid_awards"),
    path("package/<int:person_id>/", views.PackageView.as_view(), name="finaid_package"),
    path("awards/<int:pk>/respond/", views.award_respond, name="award_respond"),
    path("disbursements/<int:pk>/disburse/", views.disburse, name="disburse"),
]
