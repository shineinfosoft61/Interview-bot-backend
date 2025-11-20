# tasks.py (Celery)
# celery -A interviewbot worker -l info
from .models import QuestionAnswer, Question
import re
from celery import shared_task
from openai import OpenAI
from django.conf import settings
import google.generativeai as genai
genai.configure(api_key="AIzaSyCkS_laQWhLDMbfLTR94YK50c85AikXk5I")

client = OpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=settings.OPENROUTER_API_KEY,
            )

@shared_task
def rate_answer(answer_id):
    print('--------------answer_id--*************',answer_id)
    answer = QuestionAnswer.objects.get(id=answer_id)
    prompt = f"Question: {answer.question.text}\nAnswer: {answer.answer_text}\nRate the answer out of 10 and explain only 2 line why."

    model = genai.GenerativeModel("models/gemini-2.5-flash")
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1,
            response_mime_type="text/plain",  # or "application/json" if you want JSON parsing
        ),
    )
    ai_response = response.text.strip()
    print('AI Response:', ai_response)
    match = re.search(r"(\d{1,2})\s*/?\s*10", ai_response)
    rating = int(match.group(1)) if match else None
    print('-----------rating------',rating)

    answer.rating = rating
    answer.ai_response = ai_response
    answer.save()
