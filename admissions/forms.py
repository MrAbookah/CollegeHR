from django import forms

from .models import Application, CommunicationLog


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ["term", "program", "source", "high_school", "gpa_reported"]


class CommunicationForm(forms.ModelForm):
    class Meta:
        model = CommunicationLog
        fields = ["channel", "direction", "subject", "notes", "occurred_at"]
        widgets = {
            "occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["occurred_at"].required = False
