from django.urls import path

from hr import views

urlpatterns = [
    path("roster/", views.RosterView.as_view(), name="hr_roster"),
    path("employees/<int:person_id>/", views.EmployeeDetailView.as_view(), name="hr_employee"),
    path("employment/<int:pk>/edit/", views.EmploymentEditView.as_view(), name="employment_edit"),
    path("payroll/", views.PayrollListView.as_view(), name="hr_payroll"),
    path("payroll/<int:pk>/", views.PayrollDetailView.as_view(), name="hr_payroll_detail"),
]
