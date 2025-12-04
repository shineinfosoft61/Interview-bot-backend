from django.contrib import admin
from .models import Question, Candidate, QuestionAnswer, User, Requirement

# Register your models here.
# Register models in the Django admin site
admin.site.register(Question)
admin.site.register(Candidate)
admin.site.register(QuestionAnswer)
admin.site.register(User)
admin.site.register(Requirement)