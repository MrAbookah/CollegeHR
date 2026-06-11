from django import forms

from core.models import Affiliation, EmergencyContact, Person, PersonAddress


class PersonCreateForm(forms.ModelForm):
    initial_affiliation = forms.ChoiceField(
        choices=[("", "— none yet —")] + Affiliation.TYPES,
        required=False,
        help_text="Optional: how this person relates to the college today.",
    )

    class Meta:
        model = Person
        fields = [
            "first_name", "last_name", "middle_name", "preferred_name", "suffix",
            "date_of_birth", "ssn_last4", "pronouns", "primary_email", "primary_phone",
        ]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


class PersonBioForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "first_name", "last_name", "middle_name", "preferred_name", "suffix",
            "date_of_birth", "pronouns", "primary_email", "primary_phone",
            "directory_optout",
        ]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


class AddressForm(forms.ModelForm):
    class Meta:
        model = PersonAddress
        fields = ["type", "line1", "line2", "city", "state", "postal_code", "is_primary"]


class EmergencyContactForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        fields = ["name", "relationship", "phone", "email", "priority"]
