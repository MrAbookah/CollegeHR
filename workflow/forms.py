from django import forms

from core.models import Person
from workflow.models import Hold, HoldType, Task, TaskComment


class PersonLookupMixin(forms.Form):
    """Resolve a typed college ID (C00000042) or exact email to a Person."""

    person_lookup = forms.CharField(
        label="Person (College ID or email)", required=False,
        widget=forms.TextInput(attrs={"placeholder": "C00000042 or email"}),
    )

    def clean_person_lookup(self):
        raw = self.cleaned_data.get("person_lookup", "").strip()
        if not raw:
            return None
        qs = Person.objects.filter(merged_into__isnull=True)
        person = (
            qs.filter(college_id__iexact=raw).first()
            or qs.filter(primary_email__iexact=raw).first()
        )
        if person is None:
            raise forms.ValidationError("No person found with that College ID or email.")
        return person


class ReferralTaskForm(PersonLookupMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "assigned_department", "priority", "due_date"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}


class HoldCreateForm(PersonLookupMixin, forms.ModelForm):
    class Meta:
        model = Hold
        fields = ["hold_type", "reason", "amount"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person_lookup"].required = True
        if user is not None and not user.is_superuser:
            from core.permissions import user_dept_codes

            self.fields["hold_type"].queryset = HoldType.objects.filter(
                owning_department__code__in=user_dept_codes(user)
            )


class ReviewForm(forms.Form):
    DECISIONS = [("approve", "Approve"), ("reject", "Reject")]
    decision = forms.ChoiceField(choices=DECISIONS)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class CommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 2, "placeholder": "Add a comment for the other office…"})}
