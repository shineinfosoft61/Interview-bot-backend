import os
import re
import json
import google.generativeai as genai

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import Requirement, normalize_technology_string, TECHNOLOGY_CHOICES
from .serializers import RequirementSerializer

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

class JDAssistantView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, action):
        """
        Handle different JD assistant actions:
        - analyze: Extract and validate JD fields from user message
        - generate: Generate complete JD based on fields
        - save: Save generated JD to database
        """
        if action == 'analyze':
            return self.analyze_input(request)
        elif action == 'generate':
            return self.generate_jd(request)
        elif action == 'save':
            return self.save_jd(request)
        else:
            return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)
    
    def analyze_input(self, request):
        """Analyze user message and extract JD fields"""
        message = request.data.get('message', '')
        if not message:
            return Response({"error": "Message is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        prompt = f"""
        Analyze this job description request and extract structured information.
        
        Required fields to extract:
        - name (Job title/position name)  -- this is OPTIONAL, you may infer it from technology/experience
        - experience (Required experience in years or range)
        - technology (Primary technology stack)
        - No_of_openings (Number of positions, integer)
        - notice_period (Notice period in days, integer)
        - priority (Boolean: true if urgent/high priority)
        
        User message: "{message}"
        
        Return only valid JSON with this format:
        {{
            "status": "ready" or "need_more_info",
            "fields": {{
                "name": "extracted JD name or null",
                "experience": "extracted value or null", 
                "technology": "extracted value or null",
                "No_of_openings": extracted_integer_or_null,
                "notice_period": extracted_integer_or_null,
                "priority": true_or_false_or_null
            }},
            "missing_fields": ["list", "of", "missing", "field", "names"]
        }}
        
        Rules:
        - REQUIRED fields are only: experience and technology
        - The JD name (field "name") is OPTIONAL. If possible, infer a good JD name, otherwise leave it null.
        - Set status to "ready" only if experience AND technology are provided
        - Set status to "need_more_info" if either experience or technology is missing
        - For No_of_openings, notice_period: extract numbers or set null
        - For priority: detect words like "urgent", "immediate", "high priority" as true
        - Include ONLY the actually missing required fields (experience, technology) in missing_fields array
        """
        
        try:
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            
            result_text = getattr(response, "text", None)
            if result_text:
                result_text = result_text.strip()
                clean_text = re.sub(r"```json|```", "", result_text).strip()
                data = json.loads(clean_text)
                return Response(data, status=status.HTTP_200_OK)
            else:
                return Response({"error": "Failed to analyze input"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            return Response({"error": f"Analysis failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def generate_jd(self, request):
        """Generate complete job description based on provided fields"""
        # Accept either `fields` (preferred) or `analysis_data` (from frontend)
        raw_fields = request.data.get('fields')
        analysis_data = request.data.get('analysis_data')

        # If analysis_data is present, support both:
        # 1) { status, fields: {...}, missing_fields }
        # 2) { name, experience, technology, No_of_openings, ... } (flat shape from frontend)
        if not raw_fields and isinstance(analysis_data, dict):
            inner_fields = analysis_data.get('fields')
            if isinstance(inner_fields, dict):
                raw_fields = inner_fields
            else:
                # Fallback: treat the full analysis_data as the fields dict
                raw_fields = analysis_data

        fields = raw_fields or {}

        # Only experience and technology are required; name is optional and can be auto-suggested
        name = fields.get('name')
        experience = fields.get('experience')
        technology = fields.get('technology')

        if not experience or not technology:
            return Response(
                {
                    "error": "Missing required fields",
                    "details": "Fields 'experience' and 'technology' are required to generate JD.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Auto-suggest JD name if not provided
        if not name and technology:
            name = f"{technology} Developer"
            fields["name"] = name

        prompt = f"""
        Generate a comprehensive job description based on these details:

        Job Title: {name}
        Experience Required: {experience}
        Technology: {technology}
        Number of Openings: {fields.get('No_of_openings', 'Not specified')}
        Notice Period: {fields.get('notice_period', 'Not specified')} days
        Priority: {'High Priority' if fields.get('priority') else 'Normal'}

        Generate a complete job description with:
        1. Job Summary
        2. Responsibilities  
        3. Requirements (technical and soft skills)
        4. Nice-to-have skills
        5. What we offer

        Format as clean text without markdown formatting.
        """

        try:
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    response_mime_type="text/plain",
                ),
            )

            jd_text = getattr(response, "text", None)
            if jd_text:
                return Response(
                    {
                        "fields": fields,
                        "jd_text": jd_text.strip(),
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"error": "Failed to generate job description"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            return Response(
                {"error": f"Generation failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    
    def save_jd(self, request):
        """Save generated job description to Requirement model"""
        fields = request.data.get('fields', {})
        jd_text = request.data.get('jd_text', '')

        experience = fields.get('experience')
        technology = fields.get('technology')

        # If required fields are missing, try to extract them from jd_text using Gemini
        if (not experience or not technology) and jd_text:
            # Truncate very long JDs before sending to LLM to reduce latency
            # Usually the top part of the JD is enough to infer experience/technology
            jd_snippet = jd_text[:2000]

            extract_prompt = f"""
            From the following job description text, extract structured fields.

            VERY IMPORTANT INSTRUCTIONS FOR THE "technology" FIELD:
            - Return ONLY technologies from this EXACT list: {', '.join([choice[0] for choice in TECHNOLOGY_CHOICES])}
            - Use lowercase enum values (e.g., "python,aws", "react,nodejs", NOT "Python", "AWS", "React")
            - Return 1-3 technologies as comma-separated string
            - For "Python AWS Developer", return "python,aws"
            - For "Full Stack React Developer", return "react,javascript"
            - Choose the closest match from the list if an exact match isn't found
            - Do NOT invent new technology names
            - Join multiple technologies with commas only (no spaces)
            - Examples: "python", "python,aws", "react,javascript", "nodejs,express"

            JD Text (may be truncated):
            {jd_snippet}

            Return ONLY valid JSON in this format:
            {{
                "name": "Job title or null",
                "experience": "Experience requirement or null",
                "technology": "1-3 short main technologies as a comma-separated string or null",
                "No_of_openings": integer_or_null,
                "notice_period": integer_or_null,
                "priority": true_or_false_or_null
            }}
            """

            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash-lite")
                response = model.generate_content(
                    extract_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=200,
                        response_mime_type="application/json",
                    ),
                )

                try:
                    result_text = response.text  # may raise if no valid Part
                except Exception as inner_e:
                    print("JD save response.text access failed:", inner_e)
                    result_text = None

                if result_text:
                    result_text = result_text.strip()
                    clean_text = re.sub(r"```json|```", "", result_text).strip()
                    extracted = json.loads(clean_text)

                    # Merge extracted values into fields if missing
                    for key in ["name", "experience", "technology", "No_of_openings", "notice_period", "priority"]:
                        if not fields.get(key) and extracted.get(key) is not None:
                            fields[key] = extracted.get(key)

                    experience = fields.get('experience')
                    technology = fields.get('technology')
            except Exception as e:
                # If extraction fails, we just proceed with whatever we have
                print("JD save extraction failed:", e)

        # Simple heuristic fallback if LLM did not provide values
        if (not experience or not technology) and jd_text:
            lowered = jd_text.lower()
            # Try to infer technology from TECHNOLOGY_CHOICES
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            if not technology:
                technology = next((t for t in valid_techs if t in lowered), technology)

            # Try to infer experience strings like "4+ years" or "3-5 years"
            if not experience:
                match = re.search(r"(\d+\+?\s*-?\s*\d*\s*years?)", jd_text, re.IGNORECASE)
                if match:
                    experience = match.group(1).strip()

        # After best-effort extraction, still require experience and technology
        if not experience or not technology:
            return Response(
                {
                    "error": "Missing required fields",
                    "details": "Could not infer 'experience' and 'technology' from JD text.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Auto-suggest JD name if not provided
        if not fields.get('name') and technology:
            fields["name"] = f"{technology} Developer"

        try:
            # Normalize technology string to match enum values
            if isinstance(technology, str):
                normalized_techs = normalize_technology_string(technology)
                technology = ",".join(normalized_techs)

            requirement = Requirement.objects.create(
                name=fields.get('name', ''),
                experience=experience or '',
                technology=technology or '',
                No_of_openings=fields.get('No_of_openings'),
                notice_period=fields.get('notice_period'),
                priority=fields.get('priority', False),
                base_text=jd_text  # Store final JD text (including user edits)
            )
            
            serializer = RequirementSerializer(requirement)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({"error": f"Save failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
