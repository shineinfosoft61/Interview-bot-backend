from django.urls import path
from .views import AnswerSaveView, QuestionListAPIView, CandidateCreateView, hrView


urlpatterns = [
    path('questions/', QuestionListAPIView.as_view(), name='question'),
    path('Candidate/', CandidateCreateView.as_view(), name='Candidate'),
    path('Candidate/<uuid:pk>/', CandidateCreateView.as_view(), name='Candidate'),
    path('answer/', AnswerSaveView.as_view(), name="answer"),
    path('hr/', hrView.as_view(), name="hr"),
    path('hr/<pk>/', hrView.as_view(), name="hr"),

]