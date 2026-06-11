from django import forms

from workflow.forms import PersonLookupMixin

from .models import DocumentType


class DocumentUploadForm(PersonLookupMixin, forms.Form):
    doc_type = forms.ModelChoiceField(queryset=DocumentType.objects.all(), label="Document type")
    file = forms.FileField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person_lookup"].required = True
