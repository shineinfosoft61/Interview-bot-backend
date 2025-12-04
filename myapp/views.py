import random
import re
import json
import time
import tempfile
import os
import docx

from .models import Question, Requirement, QuestionAnswer, User, Candidate
from .serializers import (AnswerSerializer, 
                          QuestionSerializer, 
                          HrSerializer, 
                          PhotoSerializer, 
                          RequirementSerializer, 
                          RegisterSerializer, 
                          LoginSerializer,
                          ChatAiSerializer
                        )          
from .utils import analyze_facial_expressions
from .tasks import rate_answer

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from openai import OpenAI
from PyPDF2 import PdfReader
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from io import BytesIO
import google.generativeai as genai
from django.contrib.auth import authenticate, login as auth_login
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated, AllowAny


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
                        'username': user.username,
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
                candidate = Candidate.objects.get(pk=pk)
            except Candidate.DoesNotExist:
                return Response({"error": "Candidate not found."}, status=status.HTTP_404_NOT_FOUND)
            question = Question.objects.filter(candidate=candidate)
            if question:
                serializer = QuestionSerializer(question, many=True)
                return Response(serializer.data)
            else:
                questions = list(Question.objects.all().exclude(candidate=candidate))
                if not questions:
                    return Response({"message": "No questions available."}, status=404)
                random_questions = random.sample(questions, min(len(questions), 10))

                serializer = QuestionSerializer(random_questions, many=True)
                return Response(serializer.data)
        return Response({"error": "Candidate not found."}, status=status.HTTP_404_NOT_FOUND)

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


class CandidateView(APIView):
    def get_permissions(self):
        # Allow anyone to access GET; require auth for other methods
        if self.request.method == 'GET':
            return [AllowAny()]
        elif self.request.method == 'PUT':
            return [AllowAny()]
        return [IsAuthenticated()]
    
    def get(self,request, pk=None):
        if pk:
            try:
                hr_objects = Candidate.objects.get(pk=pk)
            except (ValueError, ValidationError):
                return Response({"error": "Invalid id format. Must be a UUID."}, status=status.HTTP_400_BAD_REQUEST)
            except Candidate.DoesNotExist:
                return Response({"error": "HR record not found."}, status=status.HTTP_404_NOT_FOUND)
            serializer = HrSerializer(hr_objects)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            hr_objects = Candidate.objects.all().order_by('-created_at')
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
                filename = file.name.lower()
                if filename.endswith('.pdf'):
                    reader = PdfReader(file)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                elif filename.endswith('.docx'):
                    document = docx.Document(file)
                    for para in document.paragraphs:
                        if para.text.strip():
                            text += para.text + "\n"
                else:
                    return Response({"error": "Unsupported file type. Please upload .pdf or .docx"}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                return Response({"error": f"Failed to read resume: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

            if not text.strip():
                return Response({"error": "Could not extract any readable text from the uploaded document."}, status=status.HTTP_400_BAD_REQUEST)

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
            if Candidate.objects.filter(email=data.get("email")).exists():
                return Response(
                    {
                        "error": "Email already exists.",
                        "details": "Email already exists.",
                    },
                    status=400,
                )

            hr_obj = Candidate.objects.create(
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
            hr_obj = Candidate.objects.get(pk=pk)
        except Candidate.DoesNotExist:
            return Response({"error": "Candidate not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = HrSerializer(hr_obj, data=request.data, partial=True)
        if serializer.is_valid():
            interview_time = serializer.validated_data.get("time")
            interview_status = serializer.validated_data.get("interview_status")
            interview_quick = serializer.validated_data.get("is_quick")
            requirement = serializer.validated_data.get("requirement")
            is_selected = serializer.validated_data.get("is_selected")

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
                print("hr_obj:", hr_obj)
                print("hr_obj.id:", hr_obj.id)
                answers = list(
                    QuestionAnswer.objects.filter(candidate_id=hr_obj.id)
                    .values_list("answer_text", flat=True)
                )
                print("Answer------=-", answers)
                if not answers:
                    return Response({"message": "No answers found"}, status=200)

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

                print("Result Text", result_text)
                if not result_text:
                    return None

                result_json = json.loads(result_text)
                if "communication_point" in result_json:
                    result_json = result_json["communication_point"]
                    hr_obj.communication = result_json
                    hr_obj.save(update_fields=["communication"])
                
                facial = analyze_facial_expressions(hr_obj)

            if interview_quick and str(hr_obj.requirement) != str(requirement):
                prompt = f"""
                You are an expert technical interviewer.

                Generate 10 short, clear, challenging interview questions based on:

                ### Requirement / Job Description
                {requirement.base_text}

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
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )

                result = json.loads(response.text)
                questions = result.get("questions", [])

                question_objs = [Question(candidate=hr_obj, text=q) for q in questions ]

                Question.objects.bulk_create(question_objs)
            if is_selected == True or is_selected == False:
                hr_obj.save(update_fields=["is_selected"])
                serializer.save()

                subject = f"Interview Result"
                if is_selected == True:
                    message = (
                        f"Hello {hr_obj.name},\n\n"
                        f"Congratulations! You're selected in the interview.\n"
                        f"Hr is connected you soon.\n"
                        f"Best regards,\n"
                        f"HR Team."
                    )
                elif is_selected == False:
                    message = (
                        f"Hello {hr_obj.name},\n\n" 
                        f"Unfortunately, you are not selected in the interview.\n" 
                        f"Good luck for next interview.\n" 
                        f"Best regards,\n" 
                        f"HR Team."
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
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PhotoView(APIView):
    def get(self, request, pk):
        try:
            hr_obj = Candidate.objects.get(pk=pk)
        except Candidate.DoesNotExist:
            return Response({"error": "Candidate not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PhotoSerializer(hr_obj.photos.all(), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, pk):
        try:
            hr_obj = Candidate.objects.get(pk=pk)
        except Candidate.DoesNotExist:
            return Response({"error": "Candidate not found"}, status=status.HTTP_404_NOT_FOUND)
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
            # Handle PDF files
            elif file_extension == 'pdf':
                try:
                    pdf_reader = PdfReader(BytesIO(file_data))
                    for page in pdf_reader.pages:
                        extracted = page.extract_text()
                        if extracted:
                            text += extracted + "\n"
                except Exception as e:
                    return Response({"error": f"Failed to read PDF: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({"error": "Unsupported file type. Please upload .docx, .doc, or .pdf"}, status=status.HTTP_400_BAD_REQUEST)
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
                base_text=text,
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