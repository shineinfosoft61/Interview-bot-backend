from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import ChatAiSerializer
from .models import Candidate, Question
import google.generativeai as genai
import os
import json

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


class AiQuestionView(APIView):
    def post(self, request, pk):
        try:
            hr_obj = Candidate.objects.get(pk=pk)
            hr_obj.questions.all().delete()
        except Candidate.DoesNotExist:
            return Response({"error": "Candidate not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            prompt = f"""
            You are an expert technical interviewer.
            Generate 10 short, clear, challenging interview questions based on:

            ### Requirement / Job Description
            {hr_obj.requirement.base_text if hr_obj.requirement and hr_obj.requirement.base_text else "none"}

            ### Candidate Information
            Name: {hr_obj.name}
            Email: {hr_obj.email}
            Experience: {hr_obj.experience} years
            Technology: {hr_obj.technology}

            ### Rules:
            - Focus questions on required technologies, tools, frameworks & experience level
            - Include mix of theoretical + practical scenario questions
            - Make questions specific, not generic
            - Avoid yes/no questions
            - Do NOT repeat similar questions
            - Keep each question under 20 words
            - please add every time first question is tell me about yourself

            ### Output JSON Format ONLY:
            {{
            "questions": [
                "Question 1 tell me about yourself",
                "Question 2",
                ...
                "Question 10"
            ]
            }}
            """
            model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            result = json.loads(response.text)
            questions = result.get("questions", [])

            question_objs = [Question(candidate=hr_obj, text=q, technology=(hr_obj.technology or "None")) for q in questions ]

            Question.objects.bulk_create(question_objs)
            return Response({"data": questions}, status=status.HTTP_201_CREATED)
        except Exception as e:
            print(f"Failed to generate questions: {e}")
            return Response({"error": "AI question generation failed"},status=status.HTTP_500_INTERNAL_SERVER_ERROR)