from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView

from core.models import Department
from core.permissions import user_dept_codes
from workflow import services
from workflow.forms import CommentForm, HoldCreateForm, ReferralTaskForm, ReviewForm
from workflow.mixins import StaffRequiredMixin
from workflow.models import ChangeRequest, Hold, Notification, Task


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        my_depts = Department.objects.filter(code__in=user_dept_codes(user))
        open_statuses = [Task.OPEN, Task.IN_PROGRESS]

        ctx["my_tasks"] = Task.objects.filter(
            assigned_to=user, status__in=open_statuses
        ).select_related("person", "originating_department")[:10]

        ctx["dept_queues"] = []
        for dept in my_depts:
            queue = Task.objects.filter(
                assigned_department=dept, assigned_to__isnull=True, status=Task.OPEN
            ).select_related("person", "originating_department").order_by("created_at")
            ctx["dept_queues"].append({
                "department": dept,
                "tasks": queue[:8],
                "count": queue.count(),
            })

        ctx["my_holds"] = Hold.objects.filter(
            hold_type__owning_department__in=my_depts, status=Hold.ACTIVE
        ).select_related("person", "hold_type")[:8]
        ctx["my_holds_count"] = Hold.objects.filter(
            hold_type__owning_department__in=my_depts, status=Hold.ACTIVE
        ).count()

        ctx["my_pending_crs"] = ChangeRequest.objects.filter(
            submitted_by=user, status=ChangeRequest.PENDING
        ).select_related("person")[:8]

        ctx["recent_notifications"] = Notification.objects.filter(
            recipient=user
        )[:8]
        return ctx


class TaskListView(StaffRequiredMixin, ListView):
    template_name = "tasks/list.html"
    context_object_name = "tasks"
    paginate_by = 30

    def get_queryset(self):
        user = self.request.user
        scope = self.request.GET.get("scope", "dept")
        status = self.request.GET.get("status", "open")
        qs = Task.objects.select_related(
            "person", "assigned_department", "originating_department", "assigned_to"
        )
        if scope == "mine":
            qs = qs.filter(assigned_to=user)
        else:
            qs = qs.filter(assigned_department__code__in=user_dept_codes(user))
        if status == "open":
            qs = qs.filter(status__in=[Task.OPEN, Task.IN_PROGRESS])
        elif status == "done":
            qs = qs.filter(status=Task.DONE)
        task_type = self.request.GET.get("type")
        if task_type:
            qs = qs.filter(task_type=task_type)
        return qs.order_by("created_at" if status == "open" else "-completed_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["scope"] = self.request.GET.get("scope", "dept")
        ctx["status"] = self.request.GET.get("status", "open")
        ctx["type_filter"] = self.request.GET.get("type", "")
        ctx["task_types"] = Task.TYPES
        return ctx


class TaskDetailView(StaffRequiredMixin, DetailView):
    model = Task
    template_name = "tasks/detail.html"
    context_object_name = "task"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        task = self.object
        user = self.request.user
        ctx["comment_form"] = CommentForm()
        ctx["can_act"] = user.is_superuser or task.assigned_department.code in user_dept_codes(user)
        related = task.related
        if isinstance(related, ChangeRequest):
            ctx["change_request"] = related
            ctx["review_form"] = ReviewForm()
            ctx["can_review"] = (
                related.status == ChangeRequest.PENDING
                and ctx["can_act"]
                and (user != related.submitted_by or user.is_superuser)
            )
        else:
            ctx["related_object"] = related
        return ctx


def _back_to(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    return HttpResponseRedirect(nxt or default)


class ReferralCreateView(StaffRequiredMixin, TemplateView):
    template_name = "tasks/new.html"

    def get(self, request):
        initial = {}
        person_id = request.GET.get("person")
        if person_id:
            from core.models import Person

            person = Person.objects.filter(pk=person_id).first()
            if person:
                initial["person_lookup"] = person.college_id
        return render(request, self.template_name, {"form": ReferralTaskForm(initial=initial)})

    def post(self, request):
        form = ReferralTaskForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        my_dept = Department.objects.filter(code__in=user_dept_codes(request.user)).first()
        task = services.create_task(
            title=form.cleaned_data["title"],
            task_type=Task.REFERRAL,
            assigned_department=form.cleaned_data["assigned_department"],
            person=form.cleaned_data.get("person_lookup"),
            originating_department=my_dept,
            description=form.cleaned_data["description"],
            priority=form.cleaned_data["priority"],
            due_date=form.cleaned_data["due_date"],
            created_by=request.user,
        )
        messages.success(request, f"Referral sent to {task.assigned_department.name}.")
        return redirect("task_detail", pk=task.pk)


@login_required
def task_claim(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == "POST":
        services.claim_task(task, request.user)
        messages.success(request, "Task claimed.")
    return _back_to(request, reverse("task_detail", args=[pk]))


@login_required
def task_complete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == "POST":
        if task.task_type == Task.VERIFY_CHANGE:
            messages.error(request, "Verification tasks close through Approve/Reject.")
        else:
            services.complete_task(task, request.user)
            messages.success(request, "Task completed.")
    return _back_to(request, reverse("task_detail", args=[pk]))


@login_required
def task_comment(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.task = task
            comment.author = request.user
            comment.save()
            # The other side of the conversation hears about it.
            counterpart = (
                task.created_by if request.user != task.created_by else task.assigned_to
            )
            if counterpart and counterpart != request.user:
                services.notify_user(
                    counterpart,
                    f"New comment on: {task.title}",
                    url=reverse("task_detail", args=[task.pk]),
                    body=comment.body[:140],
                )
    return _back_to(request, reverse("task_detail", args=[pk]))


class ChangeDetailView(StaffRequiredMixin, DetailView):
    model = ChangeRequest
    template_name = "changes/detail.html"
    context_object_name = "cr"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cr = self.object
        user = self.request.user
        from core.permissions import can_edit_domain

        ctx["review_form"] = ReviewForm()
        ctx["can_review"] = (
            cr.status == ChangeRequest.PENDING
            and can_edit_domain(user, cr.data_domain)
            and (user != cr.submitted_by or user.is_superuser)
        )
        return ctx


@login_required
def change_review(request, pk):
    cr = get_object_or_404(ChangeRequest, pk=pk)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            try:
                cr = services.review_change(
                    cr, request.user,
                    approve=form.cleaned_data["decision"] == "approve",
                    note=form.cleaned_data["note"],
                )
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, str(getattr(exc, "message", exc)))
            else:
                verdicts = {
                    ChangeRequest.APPROVED: "approved",
                    ChangeRequest.REJECTED: "rejected" + (" and reverted" if cr.reverted else ""),
                    ChangeRequest.CONFLICT: "flagged as a conflict — the data changed since submission",
                }
                messages.success(request, f"Change {verdicts[cr.status]}.")
    return _back_to(request, reverse("change_detail", args=[pk]))


class NotificationListView(StaffRequiredMixin, ListView):
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 40

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)


def notification_bell(request):
    if not request.user.is_authenticated:
        return render(request, "partials/bell.html", {"unread": 0, "items": []})
    qs = Notification.objects.filter(recipient=request.user)
    return render(request, "partials/bell.html", {
        "unread": qs.filter(read_at__isnull=True).count(),
        "items": qs[:8],
    })


@login_required
def notification_go(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    services.mark_read(n)
    return redirect(n.url or "dashboard")


@login_required
def notification_read_all(request):
    if request.method == "POST":
        Notification.objects.filter(
            recipient=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())
    return redirect("notification_list")


class HoldListView(StaffRequiredMixin, ListView):
    template_name = "holds/list.html"
    context_object_name = "holds"
    paginate_by = 40

    def get_queryset(self):
        qs = Hold.objects.select_related("person", "hold_type", "hold_type__owning_department")
        if self.request.GET.get("scope") == "all":
            return qs.filter(status=Hold.ACTIVE)
        return qs.filter(
            status=Hold.ACTIVE,
            hold_type__owning_department__code__in=user_dept_codes(self.request.user),
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["scope"] = self.request.GET.get("scope", "mine")
        return ctx


class HoldCreateView(StaffRequiredMixin, TemplateView):
    template_name = "holds/new.html"

    def get(self, request):
        initial = {}
        person_id = request.GET.get("person")
        if person_id:
            from core.models import Person

            person = Person.objects.filter(pk=person_id).first()
            if person:
                initial["person_lookup"] = person.college_id
        return render(request, self.template_name, {"form": HoldCreateForm(initial=initial, user=request.user)})

    def post(self, request):
        form = HoldCreateForm(request.POST, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        try:
            hold = services.place_hold(
                form.cleaned_data["person_lookup"],
                form.cleaned_data["hold_type"],
                reason=form.cleaned_data["reason"],
                amount=form.cleaned_data["amount"],
                actor=request.user,
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name, {"form": form})
        messages.success(request, f"{hold.hold_type.name} hold placed on {hold.person.display_name}.")
        return redirect("hold_list")


@login_required
def hold_release(request, pk):
    hold = get_object_or_404(Hold, pk=pk)
    if request.method == "POST":
        try:
            services.release_hold(hold, actor=request.user, note=request.POST.get("note", ""))
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Released {hold.hold_type.name} on {hold.person.display_name}.")
    return _back_to(request, reverse("hold_list"))
