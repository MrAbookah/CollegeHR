from django import forms

from core.permissions import can_see_field

from .models import EmploymentRecord


class EmploymentRecordForm(forms.ModelForm):
    class Meta:
        model = EmploymentRecord
        fields = ["position", "status", "hire_date", "end_date", "salary", "pay_basis", "supervisor"]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Field-level sensitivity: if you can't see salary you can't edit
        # (or propose) it either — the field simply isn't on your form.
        if user is not None and not can_see_field(user, "hr.employmentrecord", "salary"):
            del self.fields["salary"]
