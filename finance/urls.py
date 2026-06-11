from django.urls import path

from finance import views

urlpatterns = [
    path("budgets/", views.BudgetView.as_view(), name="finance_budgets"),
    path("journal/", views.JournalListView.as_view(), name="finance_journal"),
    path("journal/new/", views.journal_create, name="journal_create"),
    path("journal/<int:pk>/", views.JournalDetailView.as_view(), name="journal_detail"),
    path("journal/<int:pk>/lines/", views.journal_add_line, name="journal_add_line"),
    path("journal/<int:pk>/post/", views.journal_post, name="journal_post"),
]
