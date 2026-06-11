from django.urls import path

from workflow import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("tasks/", views.TaskListView.as_view(), name="task_list"),
    path("tasks/new/", views.ReferralCreateView.as_view(), name="task_new"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="task_detail"),
    path("tasks/<int:pk>/claim/", views.task_claim, name="task_claim"),
    path("tasks/<int:pk>/complete/", views.task_complete, name="task_complete"),
    path("tasks/<int:pk>/comment/", views.task_comment, name="task_comment"),
    path("changes/<int:pk>/", views.ChangeDetailView.as_view(), name="change_detail"),
    path("changes/<int:pk>/review/", views.change_review, name="change_review"),
    path("notifications/", views.NotificationListView.as_view(), name="notification_list"),
    path("notifications/bell/", views.notification_bell, name="notification_bell"),
    path("notifications/<int:pk>/go/", views.notification_go, name="notification_go"),
    path("notifications/read-all/", views.notification_read_all, name="notification_read_all"),
    path("holds/", views.HoldListView.as_view(), name="hold_list"),
    path("holds/new/", views.HoldCreateView.as_view(), name="hold_new"),
    path("holds/<int:pk>/release/", views.hold_release, name="hold_release"),
]
