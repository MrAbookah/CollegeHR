from core.permissions import user_dept_codes


def nav(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"my_dept_codes": set(), "unread_count": 0, "bell_items": []}
    from workflow.models import Notification

    mine = Notification.objects.filter(recipient=user)
    return {
        "my_dept_codes": user_dept_codes(user),
        "unread_count": mine.filter(read_at__isnull=True).count(),
        # The bell dropdown is populated on first render, not just by the
        # poll — otherwise the badge and the list disagree for 45 seconds.
        "bell_items": mine[:8],
    }
