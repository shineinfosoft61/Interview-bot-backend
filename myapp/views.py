import random
import re
import json
import time
# from fer import FER
# import cv2
# import numpy as np
# import requests
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Question, HrModels
from .serializers import AnswerSerializer, CandidateSerializer, QuestionSerializer, HrSerializer, PhotoSerializer
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
from django.core.exceptions import ValidationError


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

    def get(self,request, pk=None):
        if pk:
            try:
                hr_objects = HrModels.objects.get(pk=pk)
            except (ValueError, ValidationError):
                return Response({"error": "Invalid id format. Must be a UUID."}, status=status.HTTP_400_BAD_REQUEST)
            except HrModels.DoesNotExist:
                return Response({"error": "HR record not found."}, status=status.HTTP_404_NOT_FOUND)
            serializer = HrSerializer(hr_objects)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
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

            if not text.strip():
                return Response({"error": "Could not extract any readable text from the uploaded PDF."}, status=status.HTTP_400_BAD_REQUEST)

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

            # Try LLM with simple retries
            result_text = None
            last_error = None
            for attempt in range(3):
                try:
                    completion = client.chat.completions.create(
                        model="alibaba/tongyi-deepresearch-30b-a3b:free",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    result_text = completion.choices[0].message.content
                    break
                except Exception as e:
                    last_error = e
                    # brief backoff before retrying on transient provider issues
                    time.sleep(1.0)

            data = None
            if result_text:
                try:
                    clean_text = re.sub(r"```json|```", "", result_text).strip()
                    data = json.loads(clean_text)
                except Exception as e:
                    # fall back to heuristic parsing if LLM output is malformed
                    last_error = e

            fallback_used = False
            if not data:
                # Heuristic fallback extraction
                fallback_used = True
                lowered = text.lower()
                # email
                email_match = re.search(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
                # phone (very permissive)
                phone_match = re.search(r"(\+?\d[\d\s\-\(\)]{7,}\d)", text)
                # name: first non-empty line that is not an email/phone header-like
                first_line = next((ln.strip() for ln in text.splitlines() if ln and len(ln.strip()) > 1), "")
                # technology from a small keyword set
                tech_map = ["python", ".net", "java", "react"]
                tech = next((t for t in tech_map if t in lowered), "")
                data = {
                    "name": first_line[:100],
                    "email": email_match.group(0) if email_match else "",
                    "phone": phone_match.group(0) if phone_match else "",
                    "technology": tech,
                }
                if not any([data.get("name"), data.get("email"), data.get("phone"), data.get("technology")]):
                    # If even fallback got nothing useful, respond gracefully with 503 if provider failed, else 422
                    status_code = status.HTTP_503_SERVICE_UNAVAILABLE if last_error else status.HTTP_422_UNPROCESSABLE_ENTITY
                    return Response(
                        {
                            "error": "Could not extract fields from resume.",
                            "details": str(last_error) if last_error else "",
                        },
                        status=status_code,
                    )

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
        return Response({"records": serializer.data}, status=status.HTTP_201_CREATED)


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


class PhotoView(APIView):
    def get(self, request, pk):
        try:
            hr_obj = HrModels.objects.get(pk=pk)
        except HrModels.DoesNotExist:
            return Response({"error": "HrModels not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PhotoSerializer(hr_obj.photos.all(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, pk):
        try:
            hr_obj = HrModels.objects.get(pk=pk)
        except HrModels.DoesNotExist:
            return Response({"error": "HrModels not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PhotoSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            hr_obj.photos.add(serializer.instance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)