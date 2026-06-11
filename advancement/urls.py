from django.urls import path

from advancement import views

urlpatterns = [
    path("gifts/", views.GiftListView.as_view(), name="advancement_gifts"),
    path("donors/<int:person_id>/", views.DonorView.as_view(), name="donor_detail"),
    path("donors/<int:person_id>/pledge/", views.pledge_create, name="pledge_create"),
    path("pledges/", views.PledgeListView.as_view(), name="advancement_pledges"),
]
