from core.permissions import user_dept_codes


def nav(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"my_dept_codes": set(), "unread_count": 0}
    from workflow.models import Notification

    return {
        "my_dept_codes": user_dept_codes(user),
        "unread_count": Notification.objects.filter(recipient=user, read_at__isnull=True).count(),
    }
