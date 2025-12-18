import re
import docx
import json
import random

from PyPDF2 import PdfReader
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Question, Candidate, QuestionBank, get_technology_choices
from .serializers import QuestionSerializer, TechnologyChoicesSerializer, QuestionBankSerializer
from django.db import models

class QuestionListAPIView(APIView):
    def get(self, request, pk=None):
        # Handle candidate-specific questions (legacy support)
        if pk:
            try:
                candidate = Candidate.objects.get(pk=pk)
            except Candidate.DoesNotExist:
                return Response({"error": "Candidate not found."}, status=status.HTTP_404_NOT_FOUND)
            
            # Get questions for this candidate, ordered by order field, then created_at
            candidate_questions = Question.objects.filter(candidate=candidate).order_by('order', 'created_at')
            if candidate_questions:
                serializer = QuestionSerializer(candidate_questions, many=True)
                return Response(serializer.data)
            else:
                # Get default questions (is_default=True) ordered by order field
                default_questions = Question.objects.filter(is_default=True).order_by('order', 'created_at')
                if not default_questions:
                    return Response({"message": "No questions available."}, status=404)
                # Return up to 10 default questions
                limited_questions = default_questions[:10]
                serializer = QuestionSerializer(limited_questions, many=True)
                return Response(serializer.data)
        
        # Handle general questions with filtering
        queryset = Question.objects.all().order_by('order', 'created_at')
        
        # Filter by is_default
        is_default = request.query_params.get('is_default')
        if is_default is not None:
            if is_default.lower() == 'true':
                queryset = queryset.filter(is_default=True)
            elif is_default.lower() == 'false':
                queryset = queryset.filter(is_default=False)
        
        # Filter by technologies (multiple values support)
        technologies = request.query_params.getlist('technologies')
        if technologies:
            # Filter questions that contain any of the selected technologies
            queryset = queryset.filter(technology__in=technologies)
        
        serializer = QuestionSerializer(queryset, many=True)
        return Response(serializer.data)

    def put(self, request, pk=None):
        """Update a question's text and technology"""
        if not pk:
            return Response({"error": "Question ID is required for update"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            question = Question.objects.get(pk=pk, is_deleted=False)
        except Question.DoesNotExist:
            return Response({"error": "Question not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # Get the fields to update
        question_text = request.data.get('text')
        technology = request.data.get('technology')
        # difficulty_level = request.data.get('difficulty_level')
        time_limit = request.data.get('time_limit')
        
        # Update fields if provided
        if question_text is not None:
            question.text = question_text
        if technology is not None:
            # Validate technology against choices
            valid_technologies = [choice[0] for choice in TECHNOLOGY_CHOICES]
            if technology not in valid_technologies:
                return Response({"error": f"Invalid technology. Must be one of: {valid_technologies}"}, status=status.HTTP_400_BAD_REQUEST)
            question.technology = technology
        # if difficulty_level is not None:
        #     # Validate difficulty_level against choices
        #     valid_difficulties = [choice[0] for choice in DIFFICULTY_CHOICES]
        #     if difficulty_level not in valid_difficulties:
        #         return Response({"error": f"Invalid difficulty level. Must be one of: {valid_difficulties}"}, status=status.HTTP_400_BAD_REQUEST)
        #     question.difficulty_level = difficulty_level
        if time_limit is not None:
            try:
                question.time_limit = int(time_limit)
            except (ValueError, TypeError):
                return Response({"error": "time_limit must be a valid integer"}, status=status.HTTP_400_BAD_REQUEST)
        
        question.save()
        serializer = QuestionSerializer(question)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        file = request.FILES.get('file')
        print("============", file)
        
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
                print("=============", request.data)
                candidate_id = request.data.get('candidate')
                candidate = None
                
                if candidate_id:
                    try:
                        candidate = Candidate.objects.get(pk=candidate_id)
                        # Get the next starting order for this candidate
                        last_question = Question.objects.filter(candidate_id=candidate_id).order_by('-order').first()
                        start_order = (last_question.order + 1) if last_question else 0
                    except Candidate.DoesNotExist:
                        return Response({"error": "Candidate not found."}, status=status.HTTP_404_NOT_FOUND)
                else:
                    start_order = 0
                
                for index, question_text in enumerate(questions):
                    question_data = {
                        'text': question_text,
                        'candidate': candidate_id,
                        'technology': candidate.technology if candidate else None,
                        'order': start_order + index,  # Auto-increment order for each question
                        'difficulty_level': 'medium',
                        'time_limit': 120,
                        'is_default': False
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
        
        # Handle single question creation
        candidate_id = request.data.get('candidate')
        if candidate_id:
            print('--------------------------')
            try:
                candidate = Candidate.objects.get(pk=candidate_id)
                # Use candidate's technology if not provided
                technology = request.data.get('technology') or candidate.technology
                
                # Auto-increment order if not provided
                if request.data.get('order') is None:
                    last_order = Question.objects.filter(candidate_id=candidate_id).order_by('-order').first()
                    next_order = (last_order.order + 1) if last_order else 0
                else:
                    next_order = request.data.get('order', 0)
                    
            except Candidate.DoesNotExist:
                return Response({"error": "Candidate not found."}, status=status.HTTP_404_NOT_FOUND)
        else:
            technology = request.data.get('technology', '')
            next_order = request.data.get('order', 0)

        question_data = {
            'text': request.data.get('text'),
            'candidate': candidate_id,
            'technology': technology,
            'difficulty_level': request.data.get('difficulty_level', 'medium'),
            'time_limit': request.data.get('time_limit', 120),
            'is_default': request.data.get('is_default', False),
            'order': next_order
        }
        
        serializer = QuestionSerializer(data=question_data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk=None):
        """Update a question and handle order reordering"""
        try:
            question = Question.objects.get(pk=pk)
        except Question.DoesNotExist:
            return Response({"error": "Question not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # Handle technology update
        technology = request.data.get('technology')
        if not technology and request.data.get('candidate'):
            try:
                candidate = Candidate.objects.get(pk=request.data.get('candidate'))
                technology = candidate.technology
            except Candidate.DoesNotExist:
                technology = question.technology  # Keep existing
        
        # Handle order changes
        new_order = request.data.get('order')
        old_order = question.order
        candidate_id = request.data.get('candidate', question.candidate_id)
        
        question_data = {
            'text': request.data.get('text', question.text),
            'candidate': candidate_id,
            'technology': technology or question.technology,
            'difficulty_level': request.data.get('difficulty_level', question.difficulty_level),
            'time_limit': request.data.get('time_limit', question.time_limit),
            'is_default': request.data.get('is_default', question.is_default),
            'order': new_order if new_order is not None else old_order
        }
        
        serializer = QuestionSerializer(question, data=question_data, partial=True)
        if serializer.is_valid():
            updated_question = serializer.save()
            
            # Handle order reordering if order changed and candidate is same
            if new_order is not None and new_order != old_order and candidate_id == question.candidate_id:
                if new_order > old_order:
                    # Moving question down: decrement orders of questions in between
                    Question.objects.filter(
                        candidate_id=candidate_id,
                        order__gt=old_order,
                        order__lte=new_order
                    ).exclude(pk=pk).update(order=models.F('order') - 1)
                else:
                    # Moving question up: increment orders of questions in between
                    Question.objects.filter(
                        candidate_id=candidate_id,
                        order__gte=new_order,
                        order__lt=old_order
                    ).exclude(pk=pk).update(order=models.F('order') + 1)
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk=None):
        """Delete a question and reorder remaining questions"""
        try:
            question = Question.objects.get(pk=pk)
            candidate_id = question.candidate_id
            deleted_order = question.order
            question.delete()
            
            # Reorder remaining questions for this candidate
            if candidate_id:
                remaining_questions = Question.objects.filter(candidate_id=candidate_id).filter(order__gt=deleted_order).order_by('order')
                for q in remaining_questions:
                    q.order -= 1
                    q.save()
            
            return Response({"message": "Question deleted successfully"}, status=status.HTTP_200_OK)
            
        except Question.DoesNotExist:
            return Response({"error": "Question not found."}, status=status.HTTP_404_NOT_FOUND)


class TechnologyChoicesView(APIView):
    """API endpoint to get technology choices"""
    def get(self, request):
        serializer = TechnologyChoicesSerializer({})
        return Response(serializer.data, status=status.HTTP_200_OK)


class QuestionBankView(APIView):
    def get(self, request):
        questions = QuestionBank.objects.all().order_by("-created_at")
        serializer = QuestionBankSerializer(questions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = QuestionBankSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        try:
            question = QuestionBank.objects.get(pk=pk)
        except QuestionBank.DoesNotExist:
            return Response({"error": "Question not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = QuestionBankSerializer(question, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        try:
            question = QuestionBank.objects.get(pk=pk)
        except QuestionBank.DoesNotExist:
            return Response({"error": "Question not found"}, status=status.HTTP_404_NOT_FOUND)

        question.delete()
        return Response({"message": "Question deleted successfully"}, status=status.HTTP_204_NO_CONTENT)