from django.urls import path
from .auth_views import RegisterView, LoginView
from .question_views import QuestionListAPIView, TechnologyChoicesView
from .utils import EnumsAPIView
from .answer_views import AnswerSaveView
from .candidate_views import CandidateView, PhotoView
from .requirement_views import RequirementView
from .llm_views import ChatAiView, AiQuestionView
from .jd_views import JDAssistantView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('register/<uuid:pk>/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('questions/', QuestionListAPIView.as_view(), name='question'),
    path('questions/<uuid:pk>/', QuestionListAPIView.as_view(), name='question'),
    path('questions/<int:pk>/', QuestionListAPIView.as_view(), name='question'),
    path('technology-choices/', TechnologyChoicesView.as_view(), name='technology-choices'),
    path('enums/', EnumsAPIView.as_view(), name='enums'),
    path('answer/', AnswerSaveView.as_view(), name="answer"),
    path('hr/', CandidateView.as_view(), name="hr"),
    path('hr/<uuid:pk>/', CandidateView.as_view(), name="hr"),
    path('photo/<uuid:pk>/', PhotoView.as_view(), name="photo"),
    path('requirement/', RequirementView.as_view(), name='requirement'),
    path('requirement/<uuid:pk>/', RequirementView.as_view(), name='requirement'),
    path('requirement/<uuid:pk>/delete/', RequirementView.as_view(), name='requirement-delete'),
    path('chat/', ChatAiView.as_view(), name="chat"),
    path('Ai-question/', AiQuestionView.as_view(), name="Ai-question"),
    path('Ai-question/<uuid:pk>/', AiQuestionView.as_view(), name="Ai-question"),
    path('jd-assistant/<str:action>/', JDAssistantView.as_view(), name="jd-assistant"),
]