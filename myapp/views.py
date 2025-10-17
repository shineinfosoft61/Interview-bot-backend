import random
import re
import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Question, HrModels
from .serializers import AnswerSerializer, CandidateSerializer, QuestionSerializer, HrSerializer
import base64
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .tasks import rate_answer
from openai import OpenAI
from PyPDF2 import PdfReader
from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail


client = OpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=settings.OPENROUTER_API_KEY,
            )

class QuestionListAPIView(APIView): 
    def get(self, request):
        questions = list(Question.objects.all())
        if not questions:
            return Response({"message": "No questions available."}, status=404)
        question = random.choice(questions)  # random select
        serializer = QuestionSerializer(question)
        return Response(serializer.data)

    def post(self, request):
        serializer = QuestionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class CandidateCreateView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def get(self, request, pk):

        try:
            hr = HrModels.objects.get(pk=pk)
        except HrModels.DoesNotExist:
            return Response({"error": "Invalid link or candidate not found."}, status=status.HTTP_404_NOT_FOUND)

        if hr.interview_closed:
            return Response({"error": "This interview link is no longer accessible."}, status=status.HTTP_403_FORBIDDEN)

        return Response({"interview_closed": hr.interview_closed}, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = CandidateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AnswerSaveView(APIView):
    def post(self, request):
        serializer = AnswerSerializer(data = request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AnswerSaveView(APIView):
    def post(self, request):
        serializer = AnswerSerializer(data=request.data)
        if serializer.is_valid():
            answer = serializer.save()

            # Queue background task
            rate_answer.delay(answer.id)  

            return Response(
                {"saved_data": serializer.data, "message": "Answer saved, rating in progress..."},
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class hrView(APIView):
    def get(self,request):
        hr_objects = HrModels.objects.all().order_by('-created_at')
        serializer = HrSerializer(hr_objects, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


    def post(self, request):
        files = request.FILES.getlist('upload_doc')
        if not files:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        created_records = []

        for file in files:
            text = ""
            try:
                reader = PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            except Exception as e:
                return Response({"error": f"Failed to read resume: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

            prompt = f"""
                    Extract the following fields from this resume text: 
                    - name
                    - email
                    - phone
                    - technology (take only one main technology)
                    Return only valid JSON (no explanations, no ```json blocks).
                    Resume text:
                    {text}
                """

            try:
                completion = client.chat.completions.create(
                    model="alibaba/tongyi-deepresearch-30b-a3b:free",
                    messages=[{"role": "user", "content": prompt}]
                )
                result_text = completion.choices[0].message.content
                print('--------------result_text------------', result_text)
            except Exception as e:
                return Response({"error": f"LLM extraction failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                clean_text = re.sub(r"```json|```", "", result_text).strip()
                data = json.loads(clean_text)
            except Exception as e:
                return Response({"error": f"Failed to parse extracted data: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            hr_obj = HrModels.objects.create(
                upload_doc=file,
                name=data.get("name", ""),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                technology=data.get("technology", ""),
            )
            frontend_base = "http://localhost:5173"
            hr_obj.shine_link = f"{frontend_base}/{hr_obj.id}/"
            hr_obj.save(update_fields=['shine_link'])
            created_records.append(hr_obj)
            

        serializer = HrSerializer(created_records, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


    def put(self, request, pk):
        try:
            hr_obj = HrModels.objects.get(pk=pk)
        except HrModels.DoesNotExist:
            return Response({"error": "HrModels not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = HrSerializer(hr_obj, data=request.data, partial=True)
        if serializer.is_valid():
            interview_time = serializer.validated_data.get("time")

            # If time is added, mark as scheduled and send email
            if interview_time:
                hr_obj.interview_status = "Scheduled"
                hr_obj.save(update_fields=["interview_status"])

                # Save serializer data (to ensure gmeet_link etc. are saved)
                serializer.save()

                # Send email with interview link
                subject = f"Interview Scheduled - {hr_obj.technology} Role"
                message = (
                    f"Hello {hr_obj.name},\n\n"
                    f"Your interview for the {hr_obj.technology} position has been scheduled.\n\n"
                    f"🗓 Date & Time: {interview_time.strftime('%A, %d %B %Y at %I:%M %p')}\n"
                    f"🔗 Google Meet Link: {hr_obj.gmeet_link or 'Not provided'}\n"
                    f"🔗 Share Link: {hr_obj.shine_link or 'Not provided'}\n"
                    f"Please make sure to join the interview on time.\n\n"
                    f"Best regards,\n"
                    f"HR Team"
                )

                if hr_obj.email:
                    try:
                        send_mail(
                            subject=subject,
                            message=message,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[hr_obj.email],
                            fail_silently=False,
                        )
                    except Exception as e:
                        print(f"Email sending failed: {e}")

                return Response(serializer.data, status=status.HTTP_200_OK)

            # If no time provided, just save changes
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)