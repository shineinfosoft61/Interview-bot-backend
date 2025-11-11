from django.urls import path
from .views import AnswerSaveView, QuestionListAPIView, CandidateCreateView, hrView, PhotoView, RequirementView, InstagramDownloadView


urlpatterns = [
    path('questions/', QuestionListAPIView.as_view(), name='question'),
    path('Candidate/', CandidateCreateView.as_view(), name='Candidate'),
    path('Candidate/<uuid:pk>/', CandidateCreateView.as_view(), name='Candidate'),
    path('answer/', AnswerSaveView.as_view(), name="answer"),
    path('hr/', hrView.as_view(), name="hr"),
    path('hr/<uuid:pk>/', hrView.as_view(), name="hr"),
    path('photo/<uuid:pk>/', PhotoView.as_view(), name="photo"),
    path('requirement/', RequirementView.as_view(), name="requirement"),
    path('requirement/<uuid:pk>/', RequirementView.as_view(), name="requirement"),
    path('instagram-download/', InstagramDownloadView.as_view(), name="instagram-download"),
]