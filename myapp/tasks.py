# tasks.py (Celery)
# celery -A interviewbot worker -l info
from .models import QuestionAnswer, Question
import re
from celery import shared_task
from openai import OpenAI

client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key="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",
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
