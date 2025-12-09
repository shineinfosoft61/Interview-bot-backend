from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import AnswerSerializer
from .tasks import rate_answer

class AnswerSaveView(APIView):
    def post(self, request):
        serializer = AnswerSerializer(data=request.data)
        if serializer.is_valid():
            answer = serializer.save()
            rate_answer.delay(answer.id)
            return Response(
                {"saved_data": serializer.data, "message": "Answer saved, rating in progress..."},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
