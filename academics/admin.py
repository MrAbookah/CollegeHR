from django.contrib import admin

from academics.models import (ClearanceItem, Course, Enrollment,
                              GraduationApplication, Program,
                              ProgramRequirement, Section, StudentProgram,
                              Subject, Term)

admin.site.register(Subject)
admin.site.register(Term)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "credits", "is_active")
    list_filter = ("subject",)
    search_fields = ("title", "number")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "instructor", "capacity", "status")
    list_filter = ("term", "status")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("person", "section", "status", "grade")
    list_filter = ("status", "section__term")
    search_fields = ("person__last_name",)


class RequirementInline(admin.TabularInline):
    model = ProgramRequirement
    extra = 0


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "degree", "total_credits_required", "is_active")
    inlines = [RequirementInline]


@admin.register(StudentProgram)
class StudentProgramAdmin(admin.ModelAdmin):
    list_display = ("person", "program", "status", "advisor")
    list_filter = ("status", "program")


class ClearanceInline(admin.TabularInline):
    model = ClearanceItem
    extra = 0


@admin.register(GraduationApplication)
class GraduationApplicationAdmin(admin.ModelAdmin):
    list_display = ("person", "student_program", "term", "status")
    list_filter = ("status", "term")
    inlines = [ClearanceInline]
