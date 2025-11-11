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
from .models import Question, HrModels, Requirement, QuestionAnswer
from .serializers import AnswerSerializer, CandidateSerializer, QuestionSerializer, HrSerializer, PhotoSerializer, RequirementSerializer
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
from io import BytesIO
import tempfile
import os
import docx
import google.generativeai as genai

client = OpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=settings.OPENROUTER_API_KEY,
            )
genai.configure(api_key="AIzaSyCkS_laQWhLDMbfLTR94YK50c85AikXk5I")

class QuestionListAPIView(APIView): 
    def get(self, request):
        questions = list(Question.objects.all())
        if not questions:
            return Response({"message": "No questions available."}, status=404)
        question = random.choice(questions)  # random select
        serializer = QuestionSerializer(question)
        return Response(serializer.data)

    def post(self, request):
        file = request.FILES.get('file')
        
        if file:
            try:
                filename = file.name.lower()
                questions = []

                if filename.endswith('.txt'):
                    file_content = file.read().decode('utf-8', errors='ignore')
                    questions = [q.strip() for q in file_content.split('\n') if q.strip()]

                elif filename.endswith('.pdf'):
                    pdf_reader = PdfReader(file)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    questions = re.split(r'\n\s*\d+[\).]|\n*Q\d+[\).]?', text)
                    questions = [q.strip() for q in questions if len(q.strip()) > 5]
                    print('-------------', questions)
                else:
                    return Response({"error": "Unsupported file type. Please upload .txt or .pdf"}, status=status.HTTP_400_BAD_REQUEST)

                saved_questions = []
                for question_text in questions:
                    question_data = {
                        'text': question_text,
                        'hr': request.data.get('hr')
                    }

                    serializer = QuestionSerializer(data=question_data)
                    if serializer.is_valid():
                        serializer.save()
                        saved_questions.append(serializer.data)

                if not saved_questions:
                    return Response({"error": "No valid questions found in the file."}, status=status.HTTP_400_BAD_REQUEST)

                return Response(saved_questions, status=status.HTTP_201_CREATED)

            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
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
                    - experience (total experience)
                    - company (all company name like infotech,infosys,soft etc)
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
                fallback_used = True
                lowered = text.lower()
                email_match = re.search(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", text)
                phone_match = re.search(r"(\+?\d[\d\s\-\(\)]{7,}\d)", text)
                first_line = next((ln.strip() for ln in text.splitlines() if ln and len(ln.strip()) > 1), "")
                tech_map = ["python", ".net", "java", "react"]
                tech = next((t for t in tech_map if t in lowered), "")
                data = {
                    "name": first_line[:100],
                    "email": email_match.group(0) if email_match else "",
                    "phone": phone_match.group(0) if phone_match else "",
                    "technology": tech,
                    "company": [],
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
            if HrModels.objects.filter(email=data.get("email")).exists():
                return Response(
                    {
                        "error": "Email already exists.",
                        "details": "Email already exists.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            hr_obj = HrModels.objects.create(
                upload_doc=file,
                name=data.get("name", ""),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                technology=data.get("technology", ""),
                experience=str(data.get("experience", "")),
                company=data.get("company", []),
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
            interview_status = serializer.validated_data.get("interview_status")

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
            if interview_status == "Completed":
                answers = list(QuestionAnswer.objects.filter(hr=hr_obj).values_list("answer_text", flat=True))
            if not answers:
                return None

            prompt = (
                "Evaluate the candidate's communication skills based on the provided answers.\n"
                "Return ONLY a valid JSON object named communication_point containing:\n"
                "- Grammar: integer score (0-10)\n"
                "- ProfessionalLanguage: integer score (0-10)\n"
                "- OverallGrammarExplanation: short paragraph explaining the grammar score.\n"
                "- OverallProfessionalLanguageExplanation: short paragraph explaining the professional language score.\n"
                "- OverallLanguageUsed: describe which language(s) the candidate used (e.g., English, Hindi, mixed).\n\n"
                "Example format:\n"
                "{\n"
                '  "communication_point": {\n'
                '    "Grammar": 8,\n'
                '    "ProfessionalLanguage": 7,\n'
                '    "OverallGrammarExplanation": "Grammar was mostly correct, with few minor sentence structure issues.",\n'
                '    "OverallProfessionalLanguageExplanation": "The candidate used formal language but with occasional informal phrases.",\n'
                '    "OverallLanguageUsed": "English"\n'
                "  }\n"
                "}\n\n"
                f"Answers: {json.dumps(answers)}"
            )

            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")

                # Generate JSON response
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                result_text = response.text.strip()
            except Exception as e:
                print("error", e)
                result_text = None

            if not result_text:
                return None

            result_json = json.loads(result_text)
            if "communication_point" in result_json:
                result_json = result_json["communication_point"]
                hr_obj.communication = result_json
                hr_obj.save(update_fields=["communication"])

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


class RequirementView(APIView):
    def get(self, request):
        requirement_objects = Requirement.objects.all().order_by('-created_at')
        serializer = RequirementSerializer(requirement_objects, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            file_data = file.read()
            filename = file.name
            file_extension = filename.split('.')[-1].lower()

            text = ""

            # Handle DOCX files
            if file_extension == 'docx':
                docx_file = BytesIO(file_data)
                doc = docx.Document(docx_file)
                for para in doc.paragraphs:
                    if para.text.strip():
                        text += para.text + "\n"

            # Handle DOC files (requires textract)
            elif file_extension == 'doc':
                with tempfile.NamedTemporaryFile(delete=False, suffix='.doc') as temp_file:
                    temp_file.write(file_data)
                    temp_file_path = temp_file.name

                try:
                    text = textract.process(temp_file_path).decode('utf-8')
                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
            if not text.strip():
                return Response({"error": "Could not extract any text from the uploaded file"}, 
                             status=status.HTTP_400_BAD_REQUEST)

            # Prepare the prompt for OpenAI
            prompt = """
            Extract the following fields from the given job requirement text:
            - name: Job title/requirement name
            - experience: Required experience (e.g., "2-5 years")
            - technology: Main technology/stack required (e.g., "Python", "React")
            - No_of_openings: Number of open positions (extract as integer)
            - notice_period: Notice period in days (extract as integer)
            - priority: Boolean indicating if this is a high priority requirement (true/false)

            Return only a valid JSON object with these fields. If a field cannot be determined, use null.
            Example output:
            {
                "name": "Senior Python Developer",
                "experience": "2-5 years",
                "technology": "Python",
                "No_of_openings": 3,
                "notice_period": 30,
                "priority": true
            }

            Here is the requirement text to analyze:
            """ + text

            # Call OpenAI API
            completion = client.chat.completions.create(
                model="alibaba/tongyi-deepresearch-30b-a3b:free",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts structured data from job requirements."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            # Parse the response
            result_text = completion.choices[0].message.content
            clean_text = re.sub(r'```json|```', '', result_text).strip()
            data = json.loads(clean_text)

            if not any([data.get("name"), data.get("experience"), data.get("technology"), data.get("No_of_openings"), data.get("notice_period"), data.get("priority")]):
                # If even fallback got nothing useful, respond gracefully with 503 if provider failed, else 422
                status_code = status.HTTP_503_SERVICE_UNAVAILABLE if last_error else status.HTTP_422_UNPROCESSABLE_ENTITY
                return Response(
                    {
                        "error": "Could not extract fields from Document.",
                        "details": str(last_error) if last_error else "",
                    },
                    status=status_code,
                )
            
            # Create the requirement with extracted data
            requirement = Requirement.objects.create(
                file=file,
                name=data.get('name'),
                experience=data.get('experience'),
                technology=data.get('technology'),
                No_of_openings=data.get('No_of_openings'),
                notice_period=data.get('notice_period'),
                priority=bool(data.get('priority', False))
            )
            
            serializer = RequirementSerializer(requirement)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except json.JSONDecodeError as e:
            return Response(
                {"error": f"Failed to parse AI response: {str(e)}", "raw_response": result_text},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to process requirement: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request, pk):
        try:
            requirement = Requirement.objects.get(pk=pk)
        except Requirement.DoesNotExist:
            return Response({"error": "Requirement not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = RequirementSerializer(requirement, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



import os
import instaloader
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from urllib.parse import urlparse
from django.conf import settings

class InstagramDownloadView(APIView):
    def post(self, request):
        url = request.data.get("url")
        if not url:
            return Response({"error": "URL is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Create download directory
        download_dir = os.path.join(settings.MEDIA_ROOT, "instagram_downloads")
        os.makedirs(download_dir, exist_ok=True)

        loader = instaloader.Instaloader(dirname_pattern=download_dir, save_metadata=False, download_comments=False)

        try:
            # Extract shortcode from the URL
            parsed = urlparse(url)
            shortcode = parsed.path.strip("/").split("/")[-1]

            # Download post
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target=download_dir)

            return Response({
                "message": "Downloaded successfully",
                "shortcode": shortcode,
                "file_path": download_dir
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
