from django.contrib import admin
from .models import Question, Candidate, HrModels, QuestionAnswer

# Register your models here.
# Register models in the Django admin site
admin.site.register(Question)
admin.site.register(Candidate)
admin.site.register(HrModels)
admin.site.register(QuestionAnswer)
