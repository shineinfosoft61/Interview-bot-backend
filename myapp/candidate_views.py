import os
import re
import docx
import json
import time

import google.generativeai as genai

from PyPDF2 import PdfReader
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.mail import send_mail

from .models import Question
from .utils import analyze_facial_expressions
from .serializers import HrSerializer, PublicCandidateSerializer, PhotoSerializer
from .models import Candidate, normalize_technology_string, TECHNOLOGY_CHOICES, QuestionAnswer

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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
            serializer = PublicCandidateSerializer(hr_objects)
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
                    Extract the following fields from this resume text. Be VERY careful and precise:
                    
                    - name: Extract ONLY the person's full name (usually at the top). Look for patterns like "John Doe" or "Ronak vora". Do NOT include addresses or other text.
                    - email: Extract email address only (contains @)
                    - phone: Extract phone number only. Look for patterns like "+91 8141081293", "+1234567890", "8141081293". Do NOT extract date ranges or other text. Must be a valid phone number format.
                    - technology: Main technologies from this EXACT list: {', '.join([choice[0] for choice in TECHNOLOGY_CHOICES])}
                    - experience: Total experience in years (e.g., "1 year", "2 years", "3 years 6 months")
                    - companies: Array of company work experience ONLY
                    
                    CRITICAL INSTRUCTIONS FOR "companies" FIELD:
                    - Look for sections labeled "EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT"
                    - Extract ONLY company names from these sections
                    - Look for patterns like "Company Name, City — Job Title" or "Company Name — Job Title"
                    - Extract dates that follow "month year - month year" patterns
                    - DO NOT extract sentences, descriptions, or project details as company names
                    - Each company should have: company_name (actual company), start_date, end_date
                    
                    VERY IMPORTANT INSTRUCTIONS FOR "technology" FIELD:
                    - Return 1-3 technology values from the provided list
                    - Use lowercase enum values (e.g., "python,aws", "react,nodejs")
                    - Look in SKILLS section and job descriptions for technologies
                    - Choose the closest matches if exact technologies aren't found
                    - Do NOT invent new technology names
                    - Join multiple technologies with commas only (no spaces)
                    - Examples: "python", "python,aws", "react,javascript", "nodejs,express"
                    
                    Date Requirements:
                    - Convert ALL dates to YYYY-MM format (e.g., "nov 2023" → "2023-11", "feb 2025" → "2025-02")
                    - If only year is available, use YYYY format (e.g., "2024")
                    - If date is unclear, use null
                    - Handle various formats: "July 2024", "12/03/2022", "2022-2024", etc.
                    - IMPORTANT: If candidate is currently working at company (end date shows "present", "current", "till date", "ongoing", etc.), set end_date = "running"
                    
                    Return only valid JSON (no explanations, no ```json blocks) with this format:
                    {{
                        "name": "John Doe",
                        "email": "john@example.com",
                        "phone": "+1234567890",
                        "technology": "python,django",
                        "experience": "1 year 3 months",
                        "companies": [
                            {{
                                "company_name": "Globalia soft LLP",
                                "start_date": "2023-11",
                                "end_date": "2025-02"
                            }}
                        ]
                    }}
                    
                    Resume text:
                    {text}
                """
            print(prompt)

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
                    print("===================")
                    print(result_text)
                    if result_text:
                        result_text = result_text.strip()
                    break  # exit loop on success

                except Exception as e:
                    last_error = str(e)
                    # If it's a quota error, don't retry
                    if "429" in last_error or "quota" in last_error.lower():
                        break
                    print(f"Attempt {attempt+1} failed: {e}")
                    time.sleep(1.0)  # backoff before retrying

            data = None
            if result_text:
                try:
                    clean_text = re.sub(r"```json|```", "", result_text).strip()
                    print(clean_text)
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
                
                # Extract companies using regex in fallback
                companies = []
                # Look for company names patterns
                company_patterns = [
                    r"(?:worked at|employed by|experience at|company|private|limited|ltd|inc|corp|technologies|solutions|systems|services)\s+([A-Za-z0-9\s&]+?)(?:\n|,|\.|\s+from|\s+since|\s+to|\s+till|\s+-|\s*\(|\s*[0-9]{4})",
                    r"([A-Za-z0-9\s&]+?(?:technologies|solutions|systems|services|limited|ltd|inc|corp))\s*(?:\n|,|\.|\s+from|\s+since|\s+to|\s+till|\s+-|\s*\(|\s*[0-9]{4})",
                    r"^\s*([A-Za-z0-9\s&]{2,50})\s*\n.*?(?:[0-9]{4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                ]
                
                for pattern in company_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        company_name = match.strip() if isinstance(match, str) else match[0].strip() if match else ""
                        if len(company_name) > 2 and len(company_name) < 100:
                            # Avoid duplicates
                            if not any(comp.get("company_name", "").lower() == company_name.lower() for comp in companies):
                                companies.append({
                                    "company_name": company_name,
                                    "start_date": None,
                                    "end_date": None
                                })
                
                # Limit to first 5 companies to avoid too much data
                companies = companies[:5]
                
                data = {
                    "name": first_line[:100],
                    "email": email_match.group(0) if email_match else "",
                    "phone": phone_match.group(0) if phone_match else "",
                    "technology": tech,
                    "companies": companies,
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
            email = data.get("email")
            if email and Candidate.objects.filter(email=email).exists():
                return Response(
                    {
                        "error": "Email already exists.",
                        "details": "Email already exists.",
                    },
                    status=400,
                )

            # Store raw extracted document text in base_text
            llm_response = data if not fallback_used else {"fallback": True, "data": data}
            
            # Debug logging
            print(f"Extracted companies: {data.get('companies', [])}")
            print(f"Number of companies: {len(data.get('companies', []))}")
            
            # Clean and validate extracted data
            name = data.get("name", "").strip()
            email = data.get("email", "").strip()
            phone = data.get("phone", "").strip()
            
            # Clean phone number - extract only digits and + sign
            phone_match = re.search(r'[\+]?[\d\s\-]+', phone)
            if phone_match:
                phone = re.sub(r'[\s\-]', '', phone_match.group())
            else:
                phone = ""
            
            # Limit phone length to 30 chars
            phone = phone[:30] if phone else phone
            
            # Normalize technology string to match enum values
            technology_raw = data.get("technology", "")
            normalized_techs = normalize_technology_string(technology_raw)
            technology_normalized = ",".join(normalized_techs)
            
            print(f"Cleaned data - name: {name}, email: {email}, phone: {phone}, tech: {technology_normalized}")
            
            hr_obj = Candidate.objects.create(
                upload_doc=file,
                name=name,
                email=email,
                phone=phone,
                experience=data.get("experience", ""),
                technology=technology_normalized,
                company=data.get("companies", []),
                base_text=text,  # Store raw document text instead of LLM response
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
                    model = genai.GenerativeModel("models/gemini-2.5-flash-lite")

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
                    return Response({"error": "Failed to generate communication evaluation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                result_json = json.loads(result_text)
                if "communication_point" in result_json:
                    result_json = result_json["communication_point"]
                    hr_obj.communication = result_json
                    hr_obj.save(update_fields=["communication"])
                
                facial = analyze_facial_expressions(hr_obj)

            if interview_quick and str(hr_obj.requirement) != str(requirement):
                try:
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

                    question_objs = [Question(candidate=hr_obj, text=q) for q in questions ]

                    Question.objects.bulk_create(question_objs)
                except Exception as e:
                    print(f"Failed to generate questions: {e}")
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