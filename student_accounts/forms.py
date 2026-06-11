from django import forms

from .models import LedgerEntry


class LedgerEntryForm(forms.ModelForm):
    class Meta:
        model = LedgerEntry
        fields = ["entry_type", "charge_code", "amount", "description", "effective_date", "term"]
        widgets = {"effective_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["effective_date"].required = False
        self.fields["amount"].help_text = "Charges positive; payments/credits negative."

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")
        entry_type = cleaned.get("entry_type")
        if amount is not None and entry_type:
            if entry_type in (LedgerEntry.PAYMENT, LedgerEntry.AID_CREDIT, LedgerEntry.WAIVER) and amount > 0:
                cleaned["amount"] = -amount  # staff think "post a $500 payment"
            elif entry_type == LedgerEntry.CHARGE and amount < 0:
                self.add_error("amount", "Charges must be positive.")
        if not cleaned.get("effective_date"):
            from django.utils import timezone

            cleaned["effective_date"] = timezone.localdate()
            self.instance.effective_date = cleaned["effective_date"]
        return cleaned
