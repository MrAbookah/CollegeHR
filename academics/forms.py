from django import forms

from .grades import ALL_GRADES
from .models import (Enrollment, GraduationApplication, Section,
                     StudentProgram, Term)


class GradeForm(forms.ModelForm):
    grade = forms.ChoiceField(choices=[(g, g) for g in ALL_GRADES])

    class Meta:
        model = Enrollment
        fields = ["grade"]


class SectionAddForm(forms.Form):
    section = forms.ModelChoiceField(queryset=Section.objects.none(), label="Add section")

    def __init__(self, *args, term=None, **kwargs):
        super().__init__(*args, **kwargs)
        if term is not None:
            self.fields["section"].queryset = (
                Section.objects.filter(term=term, status=Section.OPEN)
                .select_related("course__subject")
            )


class GraduationApplyForm(forms.Form):
    student_program = forms.ModelChoiceField(queryset=StudentProgram.objects.none())
    term = forms.ModelChoiceField(queryset=Term.objects.all())

    def __init__(self, *args, person=None, **kwargs):
        super().__init__(*args, **kwargs)
        if person is not None:
            self.fields["student_program"].queryset = person.student_programs.filter(
                status=StudentProgram.ACTIVE
            )
