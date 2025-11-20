import random
import re
import json
import time

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Question, HrModels, Requirement, QuestionAnswer, User
from .serializers import AnswerSerializer, CandidateSerializer, QuestionSerializer, HrSerializer, PhotoSerializer, RequirementSerializer, RegisterSerializer, LoginSerializer
from .utils import analyze_facial_expressions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .tasks import rate_answer
from openai import OpenAI
from PyPDF2 import PdfReader
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from io import BytesIO
import tempfile
import os
import docx
import google.generativeai as genai
from django.contrib.auth import authenticate, login as auth_login
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated


client = OpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=settings.OPENROUTER_API_KEY,
            )
genai.configure(api_key="AIzaSyCkS_laQWhLDMbfLTR94YK50c85AikXk5I")


class RegisterView(APIView):
    serializer_class = RegisterSerializer

    def get(self, request):
        users = User.objects.all()
        serializer = RegisterSerializer(users, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        data = request.data
        try:
            User.objects.get(username=data['username'])
            return Response({"status": "error", "message": f"User with this username address already exists."}, status=400)
        except:
            serializer = self.serializer_class(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response({"status": "success", "message": "User created successfully!","data":serializer.data}, status=200)
            
            return Response(serializer.errors, status=400)
        
    def put(self, request, pk=None):
        data = request.data
        try:
            user_obj = User.objects.get(id=pk)
        except User.DoesNotExist:
            return Response({"status": "error", "message": f"User Does not exist with ID: {pk}"}, status=400)
        
        serializer = RegisterSerializer(user_obj, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "message": "Profile updated successfully!"}, status=200)
        return Response(serializer.errors, status=400)

    
class LoginView(APIView):
    serializer_class = LoginSerializer
    
    def post(self, request):
        data = request.data
        serializer = self.serializer_class(data=data)
        if serializer.is_valid():
            email = serializer.validated_data.get('email')
            password = serializer.validated_data.get('password')
            
            try:
                user_obj = User.objects.get(email=email)
                if not user_obj.is_active:
                    return Response({"status": "error", "message": "Your account has been disabled!"}, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return Response({"status": "error", "message": "The email provided is invalid."}, status=status.HTTP_400_BAD_REQUEST)
            
            user = authenticate(email=email, password=password)
            if user is not None:
                auth_login(request, user)
                refresh = RefreshToken.for_user(user)
                
                response = {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': user.id,
                        'name': user.name,
                        'email': user.email,
                        'role': user.role,
                        'is_staff': user.is_staff,
                        }
                }
                return Response(response, status=status.HTTP_200_OK)
            return Response({"status": "error", "message": "The password provided is invalid."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class QuestionListAPIView(APIView):
    def get(self, request, pk=None):
        if pk:
            try:
                hr = HrModels.objects.get(pk=pk)
            except HrModels.DoesNotExist:
                return Response({"error": "HR not found."}, status=status.HTTP_404_NOT_FOUND)
            question = Question.objects.filter(hr=hr)
            if question:
                serializer = QuestionSerializer(question, many=True)
                return Response(serializer.data)
            else:
                questions = list(Question.objects.all().exclude(hr=hr))
                if not questions:
                    return Response({"message": "No questions available."}, status=404)
                random_questions = random.sample(questions, min(len(questions), 10))

                serializer = QuestionSerializer(random_questions, many=True)
                return Response(serializer.data)
        return Response({"error": "HR not found."}, status=status.HTTP_404_NOT_FOUND)

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
    permission_classes = [IsAuthenticated]
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
                    # Create the model instance
                    model = genai.GenerativeModel("models/gemini-2.5-flash")
                    # Generate content
                    response = model.generate_content(
                        prompt,
                        generation_config=genai.types.GenerationConfig(
                            temperature=0.1,
                            response_mime_type="application/json",  # or "text/plain" if you want plain text
                        ),
                    )
                    # Extract text safely
                    result_text = getattr(response, "text", None)
                    if result_text:
                        result_text = result_text.strip()
                    break  # exit loop on success

                except Exception as e:
                    last_error = e
                    print(f"Attempt {attempt+1} failed: {e}")
                    time.sleep(1.0)  # backoff before retrying

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
                    status=400,
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
                
                facial = analyze_facial_expressions(hr_obj)

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
    permission_classes = [IsAuthenticated]
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
            
            # Parse the response
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
            return Response(
                {"error": "Requirement not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = RequirementSerializer(requirement, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
