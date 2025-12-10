# tasks.py (Celery)
# celery -A interviewbot worker -l info
import re
from celery import shared_task
import google.generativeai as genai

from .models import QuestionAnswer

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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
