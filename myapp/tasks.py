# tasks.py (Celery)
# celery -A interviewbot worker -l info
from .models import QuestionAnswer, Question
import re
from celery import shared_task
from openai import OpenAI
from django.conf import settings

client = OpenAI(
                base_url=settings.OPENROUTER_BASE_URL,
                api_key=settings.OPENROUTER_API_KEY,
            )

@shared_task
def rate_answer(answer_id):
    print('--------------answer_id--*************',answer_id)
    answer = QuestionAnswer.objects.get(id=answer_id)
    prompt = f"Question: {answer.question.text}\nAnswer: {answer.answer_text}\nRate the answer out of 10 and explain why."

    completion = client.chat.completions.create(
        model="x-ai/grok-4-fast:free",
        messages=[{"role": "user", "content": prompt}]
    )
    ai_response = completion.choices[0].message.content
    match = re.search(r"(\d{1,2})\s*/?\s*10", ai_response)
    rating = int(match.group(1)) if match else None
    print('-----------rating------',rating)

    answer.rating = rating
    answer.ai_response = ai_response
    answer.save()
