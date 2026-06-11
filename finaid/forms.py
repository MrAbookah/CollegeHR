from django import forms

from .models import AidAward


class AwardForm(forms.ModelForm):
    class Meta:
        model = AidAward
        fields = ["aid_year", "program", "amount_offered"]
