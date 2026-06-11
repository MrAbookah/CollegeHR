from django import forms

from .models import JournalEntry, JournalLine


class JournalEntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ["entry_date", "description"]
        widgets = {"entry_date": forms.DateInput(attrs={"type": "date"})}


class JournalLineForm(forms.ModelForm):
    class Meta:
        model = JournalLine
        fields = ["gl_account", "department", "debit", "credit"]
