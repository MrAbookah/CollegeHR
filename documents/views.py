from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, TemplateView

from core import permissions
from workflow.mixins import StaffRequiredMixin

from . import services
from .forms import DocumentUploadForm
from .models import Document


class QueueView(StaffRequiredMixin, ListView):
    """The Perceptive-style review queue, scoped to my department's types."""

    template_name = "documents/queue.html"
    context_object_name = "documents"

    def get_queryset(self):
        scope = self.request.GET.get("scope", "mine")
        qs = Document.objects.filter(status=Document.PENDING_REVIEW).select_related(
            "person", "doc_type__owning_department", "uploaded_by"
        )
        if scope != "all":
            qs = qs.filter(
                doc_type__owning_department__code__in=permissions.user_dept_codes(self.request.user)
            )
        return qs.order_by("created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["scope"] = self.request.GET.get("scope", "mine")
        return ctx


class UploadView(StaffRequiredMixin, TemplateView):
    template_name = "documents/upload.html"

    def get(self, request):
        initial = {}
        person_id = request.GET.get("person")
        if person_id:
            from core.models import Person

            person = Person.objects.filter(pk=person_id).first()
            if person:
                initial["person_lookup"] = person.college_id
        return render(request, self.template_name, {"form": DocumentUploadForm(initial=initial)})

    def post(self, request):
        form = DocumentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        doc = services.upload_document(
            person=form.cleaned_data["person_lookup"],
            doc_type=form.cleaned_data["doc_type"],
            file=form.cleaned_data["file"],
            uploaded_by=request.user,
        )
        messages.success(
            request,
            f"Uploaded — review task sent to {doc.doc_type.owning_department.name}.",
        )
        return redirect("document_detail", pk=doc.pk)


class DocumentDetailView(StaffRequiredMixin, DetailView):
    model = Document
    template_name = "documents/detail.html"
    context_object_name = "doc"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["can_review"] = (
            self.object.status == Document.PENDING_REVIEW
            and permissions.is_member_of(
                self.request.user, self.object.doc_type.owning_department.code
            )
        )
        return ctx


@login_required
def document_file(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if not permissions.is_staff_member(request.user):
        raise Http404
    services.log_document_view(doc, request.user)  # FERPA: opening = a disclosure
    try:
        return FileResponse(doc.file.open("rb"), filename=doc.original_filename)
    except FileNotFoundError:
        raise Http404("File missing from storage")


@login_required
def document_review(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        try:
            services.review_document(
                doc, request.user,
                verify=request.POST.get("verdict") == "verify",
                note=request.POST.get("note", ""),
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(getattr(exc, "message", exc)))
        else:
            messages.success(request, f"Document {doc.status.lower().replace('_', ' ')}.")
    return redirect("document_detail", pk=pk)
