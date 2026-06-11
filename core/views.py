from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import DetailView, TemplateView, UpdateView

from core import audit, dedup, permissions
from core.forms import (AddressForm, EmergencyContactForm, PersonBioForm,
                        PersonCreateForm)
from core.models import Affiliation, Person
from workflow.mixins import GovernedFormMixin, StaffRequiredMixin


class PersonSearchView(StaffRequiredMixin, TemplateView):
    template_name = "people/search.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        ctx["q"] = q
        ctx["results"] = dedup.search_people(q) if q else None
        # Searching is what licenses creating — the token proves it happened.
        ctx["search_token"] = dedup.issue_search_token()
        return ctx


class PersonCreateView(StaffRequiredMixin, TemplateView):
    template_name = "people/create.html"

    def get(self, request):
        token = request.GET.get("token", "")
        if not dedup.validate_search_token(token):
            messages.warning(request, "Search for the person first — they may already exist.")
            return redirect("person_search")
        form = PersonCreateForm(initial={
            "first_name": request.GET.get("first", ""),
            "last_name": request.GET.get("last", ""),
        })
        return render(request, self.template_name, {"form": form, "search_token": token})

    def post(self, request):
        token = request.POST.get("search_token", "")
        if not dedup.validate_search_token(token):
            messages.warning(request, "Your search session expired — search again.")
            return redirect("person_search")
        form = PersonCreateForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "search_token": token})

        cd = form.cleaned_data
        candidates = dedup.find_candidates(
            cd["first_name"], cd["last_name"],
            date_of_birth=cd.get("date_of_birth"),
            email=cd.get("primary_email"),
            ssn_last4=cd.get("ssn_last4"),
        )
        candidates = [c for c in candidates if c.score >= dedup.INTERSTITIAL_THRESHOLD]
        force = request.POST.get("force") == "1"
        justification = request.POST.get("justification", "").strip()

        if candidates and not force:
            return render(request, "people/duplicates.html", {
                "form": form, "search_token": token, "candidates": candidates,
            })
        if candidates and force and not justification:
            messages.error(request, "A justification is required to create despite possible duplicates.")
            return render(request, "people/duplicates.html", {
                "form": form, "search_token": token, "candidates": candidates,
            })

        person = form.save(commit=False)
        person.created_by = request.user
        person.save()
        if cd.get("initial_affiliation"):
            from django.utils import timezone

            Affiliation.objects.create(
                person=person, type=cd["initial_affiliation"],
                start_date=timezone.localdate(),
            )
        if candidates and force:
            audit.log(
                "OVERRIDE", person,
                summary=f"Created despite {len(candidates)} possible duplicate(s): {justification}",
            )
        messages.success(request, f"Created {person.display_name} ({person.college_id}).")
        return redirect("person_detail", pk=person.pk)


class PersonDetailView(StaffRequiredMixin, DetailView):
    model = Person
    template_name = "people/detail.html"
    context_object_name = "person"

    def get(self, request, *args, **kwargs):
        person = self.get_object()
        if person.merged_into_id:
            messages.info(request, f"{person.college_id} was merged — showing the surviving record.")
            return redirect("person_detail", pk=person.merged_into_id)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        person = self.object
        user = self.request.user
        tabs = [("overview", "Overview", None)]
        if person.affiliations.filter(type__in=[Affiliation.STUDENT, Affiliation.APPLICANT]).exists() \
                or person.enrollments.exists():
            tabs.append(("academics", "Academics", "ACADEMIC"))
        if person.applications.exists():
            tabs.append(("admissions", "Admissions", "ADMISSIONS"))
        tabs += [
            ("account", "Student Account", "STUDENT_ACCOUNT"),
            ("finaid", "Financial Aid", "FINANCIAL_AID"),
        ]
        if person.employment_records.exists() or person.staff_memberships.exists():
            tabs.append(("employment", "Employment", "EMPLOYMENT"))
        if person.gifts.exists() or person.pledges.exists() or hasattr(person, "alumni_info"):
            tabs.append(("advancement", "Advancement", "ADVANCEMENT"))
        tabs += [("documents", "Documents", "DOCUMENT"), ("activity", "Activity", None)]
        ctx["tabs"] = [
            {"key": key, "label": label, "allowed": domain is None or permissions.can_view_domain(user, domain)}
            for key, label, domain in tabs
        ]
        ctx["active_holds"] = person.active_holds()
        ctx["active_affiliations"] = person.active_affiliations()
        return ctx


# Domain tabs are HTMX-lazy: each load is one precise FERPA "VIEW" audit row.
TAB_DOMAINS = {
    "overview": None, "activity": None,
    "academics": "ACADEMIC", "admissions": "ADMISSIONS", "account": "STUDENT_ACCOUNT",
    "finaid": "FINANCIAL_AID", "employment": "EMPLOYMENT", "advancement": "ADVANCEMENT",
    "documents": "DOCUMENT",
}


@login_required
def person_tab(request, pk, tab):
    if tab not in TAB_DOMAINS:
        raise Http404
    person = get_object_or_404(Person, pk=pk)
    domain = TAB_DOMAINS[tab]
    if not permissions.is_staff_member(request.user):
        return render(request, "people/tabs/no_access.html", {"person": person}, status=403)
    if domain and not permissions.can_view_domain(request.user, domain):
        return render(request, "people/tabs/no_access.html", {"person": person})

    ctx = {"person": person, "user": request.user}
    if domain:
        audit.log("VIEW", person=person,
                  summary=f"Viewed {tab} tab for {person.display_name}")

    if tab == "overview":
        ctx.update(
            addresses=person.addresses.filter(is_active=True),
            contacts=person.emergency_contacts.all(),
            affiliations=person.affiliations.all(),
            memberships=person.staff_memberships.select_related("department"),
        )
    elif tab == "academics":
        from academics.models import Term
        from academics.services import gpa

        ctx.update(
            terms=Term.objects.all()[:6],
            student_programs=person.student_programs.select_related("program", "advisor"),
            enrollments=person.enrollments.select_related(
                "section__course__subject", "section__term"
            ).order_by("-section__term__start_date"),
            gpa=gpa(person),
            grad_apps=person.graduation_applications.select_related("term", "student_program__program"),
            can_register=permissions.can_edit_domain(request.user, "ACADEMIC"),
        )
    elif tab == "admissions":
        ctx.update(applications=person.applications.select_related("term", "program"))
    elif tab == "account":
        from student_accounts.services import balance

        ctx.update(
            balance=balance(person),
            entries=person.ledger_entries.select_related("charge_code", "term")[:20],
        )
    elif tab == "finaid":
        ctx.update(
            awards=person.aid_awards.select_related("program", "aid_year").prefetch_related("disbursements"),
        )
    elif tab == "employment":
        salary_visible = permissions.can_see_field(request.user, "hr.employmentrecord", "salary")
        if salary_visible:
            audit.log("VIEW", person=person,
                      summary=f"Viewed employment records incl. salary for {person.display_name}")
        ctx.update(
            records=person.employment_records.select_related(
                "position__department", "position__gl_account", "supervisor"
            ),
            paychecks=person.paychecks.select_related("payroll_run")[:6],
            salary_visible=salary_visible,
        )
    elif tab == "advancement":
        ctx.update(
            gifts=person.gifts.select_related("designation")[:15],
            pledges=person.pledges.select_related("designation"),
            alumni_info=getattr(person, "alumni_info", None),
            total_giving=person.gifts.aggregate(t=Sum("amount"))["t"] or 0,
        )
    elif tab == "documents":
        ctx.update(documents=person.documents.select_related("doc_type", "uploaded_by"))
    elif tab == "activity":
        ctx.update(
            audit_entries=person.audit_entries.select_related("actor")[:50],
            tasks=person.tasks.select_related("assigned_department")[:20],
            communications=person.communications.select_related("logged_by")[:20],
        )
    return render(request, f"people/tabs/{tab}.html", ctx)


class PersonBioEditView(GovernedFormMixin, StaffRequiredMixin, UpdateView):
    """The front-desk scenario: anyone may fix biographic data, but unless
    they're the Registrar the save produces a verification task."""

    model = Person
    form_class = PersonBioForm
    template_name = "people/bio_edit.html"
    data_domain = "BIOGRAPHIC"

    def get_success_url(self):
        return reverse("person_detail", args=[self.object.pk if self.object else self.kwargs["pk"]])


class AddressCreateView(GovernedFormMixin, StaffRequiredMixin, TemplateView):
    template_name = "people/address_form.html"
    data_domain = "BIOGRAPHIC"

    def get(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        return render(request, self.template_name, {"form": AddressForm(), "person": person})

    def post(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        form = AddressForm(request.POST)
        form.instance.person = person
        self.person = person
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "person": person})
        return self.form_valid(form)

    def get_success_url(self):
        return reverse("person_detail", args=[self.person.pk])


class EmergencyContactCreateView(AddressCreateView):
    template_name = "people/contact_form.html"

    def get(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        return render(request, self.template_name, {"form": EmergencyContactForm(), "person": person})

    def post(self, request, person_id):
        person = get_object_or_404(Person, pk=person_id)
        form = EmergencyContactForm(request.POST)
        form.instance.person = person
        self.person = person
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "person": person})
        return self.form_valid(form)


@login_required
def reports(request):
    """Four canned, shared-definition reports — the antidote to every
    department keeping its own conflicting spreadsheet."""
    if not permissions.is_staff_member(request.user):
        return render(request, "registration/no_access.html", status=403)
    from academics.models import Enrollment, Term
    from advancement.models import Gift
    from student_accounts.models import LedgerEntry

    headcount = (
        Affiliation.objects.filter(status=Affiliation.ACTIVE)
        .values("type").annotate(n=Count("person", distinct=True)).order_by("-n")
    )
    enrollment_by_term = (
        Enrollment.objects.filter(status__in=[Enrollment.REGISTERED, Enrollment.COMPLETED])
        .values("section__term__name", "section__term__code")
        .annotate(n=Count("person", distinct=True)).order_by("-section__term__code")
    )
    balances = (
        LedgerEntry.objects.values("person").annotate(bal=Sum("amount")).filter(bal__gt=0)
    )
    buckets = {"0-500": 0, "500-1000": 0, "1000+": 0}
    ar_total = Decimal("0")
    for row in balances:
        b = row["bal"]
        ar_total += b
        if b <= 500:
            buckets["0-500"] += 1
        elif b <= 1000:
            buckets["500-1000"] += 1
        else:
            buckets["1000+"] += 1
    giving = (
        Gift.objects.values("designation__name")
        .annotate(total=Sum("amount"), n=Count("id")).order_by("-total")
    )
    return render(request, "reports.html", {
        "headcount": headcount,
        "enrollment_by_term": enrollment_by_term,
        "ar_buckets": buckets,
        "ar_total": ar_total,
        "giving": giving,
        "terms": Term.objects.all()[:6],
    })
