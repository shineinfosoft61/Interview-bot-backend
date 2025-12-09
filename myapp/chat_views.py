from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import ChatAiSerializer
import google.generativeai as genai
import os

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class ChatAiView(APIView):
    def post(self, request):
        print('---------------------')
        serializer = ChatAiSerializer(data=request.data)
        if serializer.is_valid():
            user_message = serializer.validated_data['question']

            # Generate response using the model
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            chat = model.start_chat()
            response = chat.send_message(user_message)

            data = {
                "question": user_message,
                "response": response.text,
            }

            return Response({"data": data}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
