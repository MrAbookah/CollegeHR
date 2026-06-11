from django.urls import path

from academics import views

urlpatterns = [
    path("catalog/", views.CatalogView.as_view(), name="catalog"),
    path("courses/<int:pk>/", views.CourseDetailView.as_view(), name="course_detail"),
    path("sections/", views.SectionListView.as_view(), name="section_list"),
    path("sections/<int:pk>/", views.SectionDetailView.as_view(), name="section_detail"),
    path("sections/<int:pk>/grade/<int:enrollment_id>/", views.enter_grade, name="enter_grade"),
    path("grade-change/<int:pk>/", views.GradeChangeView.as_view(), name="grade_change"),
    path("register/<int:person_id>/", views.RegistrationView.as_view(), name="registration"),
    path("transcript/<int:person_id>/", views.transcript, name="transcript"),
    path("graduation/", views.GraduationBoardView.as_view(), name="graduation_board"),
    path("graduation/<int:pk>/", views.GraduationDetailView.as_view(), name="graduation_detail"),
    path("graduation/<int:pk>/items/<int:item_id>/", views.clearance_action, name="clearance_action"),
    path("graduation/<int:pk>/award/", views.award_degree, name="award_degree"),
    path("graduation/apply/<int:person_id>/", views.graduation_apply, name="graduation_apply"),
]
