from django.urls import path
from .views import AnswerSaveView, QuestionListAPIView, CandidateView, PhotoView, RequirementView, RegisterView, LoginView, ChatAiView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('register/<uuid:pk>/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('questions/', QuestionListAPIView.as_view(), name='question'),
    path('questions/<uuid:pk>/', QuestionListAPIView.as_view(), name='question'),
    path('answer/', AnswerSaveView.as_view(), name="answer"),
    path('hr/', CandidateView.as_view(), name="hr"),
    path('hr/<uuid:pk>/', CandidateView.as_view(), name="hr"),
    path('photo/<uuid:pk>/', PhotoView.as_view(), name="photo"),
    path('requirement/', RequirementView.as_view(), name="requirement"),
    path('requirement/<uuid:pk>/', RequirementView.as_view(), name="requirement"),
    path('chat/', ChatAiView.as_view(), name="chat"),
]