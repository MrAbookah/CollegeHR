from django.urls import path

from admissions import views

urlpatterns = [
    path("pipeline/", views.PipelineView.as_view(), name="pipeline"),
    path("applications/new/<int:person_id>/", views.application_create, name="application_create"),
    path("applications/<int:pk>/", views.ApplicationDetailView.as_view(), name="application_detail"),
    path("applications/<int:pk>/stage/", views.stage_change, name="stage_change"),
    path("applications/<int:pk>/checklist/<int:item_id>/waive/", views.checklist_waive, name="checklist_waive"),
    path("applications/<int:pk>/comm/", views.communication_add, name="communication_add"),
]
