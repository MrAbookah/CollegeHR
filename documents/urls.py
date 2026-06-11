from django.urls import path

from documents import views

urlpatterns = [
    path("queue/", views.QueueView.as_view(), name="document_queue"),
    path("upload/", views.UploadView.as_view(), name="document_upload"),
    path("<int:pk>/", views.DocumentDetailView.as_view(), name="document_detail"),
    path("<int:pk>/file/", views.document_file, name="document_file"),
    path("<int:pk>/review/", views.document_review, name="document_review"),
]
