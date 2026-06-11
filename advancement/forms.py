from django import forms

from .models import Gift, Pledge


class GiftForm(forms.ModelForm):
    class Meta:
        model = Gift
        fields = ["designation", "amount", "gift_date", "method", "pledge"]
        widgets = {"gift_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pledge"].required = False
        self.fields["gift_date"].required = False


class PledgeForm(forms.ModelForm):
    class Meta:
        model = Pledge
        fields = ["designation", "total_amount", "start_date", "frequency"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"})}
