from django.urls import path
from .views import AnswerSaveView, QuestionListAPIView, CandidateCreateView


urlpatterns = [
    path('questions/', QuestionListAPIView.as_view(), name='question'),
    path('Candidate/', CandidateCreateView.as_view(), name='Candidate'),
    path('answer/', AnswerSaveView.as_view(), name="answer"),

]