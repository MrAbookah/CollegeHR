from django.urls import path

from core import views

urlpatterns = [
    path("search/", views.PersonSearchView.as_view(), name="person_search"),
    path("new/", views.PersonCreateView.as_view(), name="person_create"),
    path("<int:pk>/", views.PersonDetailView.as_view(), name="person_detail"),
    path("<int:pk>/tab/<slug:tab>/", views.person_tab, name="person_tab"),
    path("<int:pk>/bio/edit/", views.PersonBioEditView.as_view(), name="person_bio_edit"),
    path("<int:person_id>/address/new/", views.AddressCreateView.as_view(), name="address_new"),
    path("<int:person_id>/contact/new/", views.EmergencyContactCreateView.as_view(), name="contact_new"),
]
