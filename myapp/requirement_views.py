from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import Requirement, normalize_technology_string, TECHNOLOGY_CHOICES
from .serializers import RequirementSerializer

class RequirementView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        requirement_objects = Requirement.objects.filter(is_deleted=False).order_by('-created_at')
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
            tech_choices = ', '.join([choice[0] for choice in TECHNOLOGY_CHOICES])
            prompt = f"""
            Extract the following fields from the given job requirement text:
            - name: Job title/requirement name
            - experience: Required experience (e.g., "2-5 years")
            - technology: Main technologies required (ONLY from this list: {tech_choices})
            - No_of_openings: Number of open positions (extract as integer)
            - notice_period: Notice period in days (extract as integer)
            - priority: Boolean indicating if this is a high priority requirement (true/false)

            VERY IMPORTANT INSTRUCTIONS FOR "technology" FIELD:
            - Return ONLY technology values from the provided list
            - Use lowercase enum values (e.g., "python,aws", "react,nodejs")
            - Return 1-3 technologies as comma-separated string
            - For "Python AWS Developer", return "python,aws"
            - For "Full Stack React Developer", return "react,javascript"
            - Choose the closest matches if exact technologies aren't found
            - Do NOT invent new technology names
            - Join multiple technologies with commas only (no spaces)
            - Examples: "python", "python,aws", "react,javascript", "nodejs,express"

            Return only a valid JSON object with these fields. If a field cannot be determined, use null.
            Example output:
            {{
                "name": "Senior Python Developer",
                "experience": "2-5 years",
                "technology": "python,aws",
                "No_of_openings": 3,    
                "notice_period": 30,
                "priority": true
            }}

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
            
            # Normalize technology string to match enum values
            technology_raw = data.get('technology', '')
            normalized_techs = normalize_technology_string(technology_raw)
            technology_normalized = ",".join(normalized_techs)
            
            # Create the requirement with extracted data
            requirement = Requirement.objects.create(
                file=file,
                base_text=text,
                name=data.get('name'),
                experience=data.get('experience'),
                technology=technology_normalized,
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

    def delete(self, request, pk=None):
        """Soft delete a requirement by setting is_deleted=True"""
        try:
            requirement = Requirement.objects.get(pk=pk)
        except (ValueError, ValidationError):
            return Response({"error": "Invalid id format. Must be a UUID."}, status=status.HTTP_400_BAD_REQUEST)
        except Requirement.DoesNotExist:
            return Response({"error": "Requirement not found."}, status=status.HTTP_404_NOT_FOUND)

        requirement.is_deleted = True
        requirement.save(update_fields=['is_deleted'])
        return Response(status=status.HTTP_204_NO_CONTENT)
