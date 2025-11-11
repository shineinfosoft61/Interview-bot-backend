import json
from openai import OpenAI
from django.conf import settings
from .models import HrModels, QuestionAnswer
import time
# Optional imports for facial expression analysis
try:
    from fer import FER  # type: ignore
    import cv2  # type: ignore
except Exception:
    FER = None
    cv2 = None





# def get_grammer_report(hr_pk):
#     """
#     Generate a grammar/communication report for the given HrModels primary key.
#     Saves the JSON result to HrModels.communication and returns the saved dict.
#     """
#     try:
#         hr_obj = HrModels.objects.get(pk=hr_pk)
#     except HrModels.DoesNotExist:
#         return None

#     answers = list(QuestionAnswer.objects.filter(hr=hr_pk).values_list("answer_text", flat=True))
#     print("*******************answers", answers)
#     if not answers:
#         return None

#     prompt = (
#         "Evaluate the candidate's communication skills based on the provided answers.\n"
#         "Return ONLY a valid JSON object named communication_point containing:\n"
#         "- Grammar: integer score (0-10)\n"
#         "- ProfessionalLanguage: integer score (0-10)\n"
#         "- OverallGrammarExplanation: short paragraph explaining the grammar score.\n"
#         "- OverallProfessionalLanguageExplanation: short paragraph explaining the professional language score.\n"
#         "- OverallLanguageUsed: describe which language(s) the candidate used (e.g., English, Hindi, mixed).\n\n"
#         "Example format:\n"
#         "{\n"
#         '  "communication_point": {\n'
#         '    "Grammar": 8,\n'
#         '    "ProfessionalLanguage": 7,\n'
#         '    "OverallGrammarExplanation": "Grammar was mostly correct, with few minor sentence structure issues.",\n'
#         '    "OverallProfessionalLanguageExplanation": "The candidate used formal language but with occasional informal phrases.",\n'
#         '    "OverallLanguageUsed": "English"\n'
#         "  }\n"
#         "}\n\n"
#         f"Answers: {json.dumps(answers)}"
#     )

#     try:
#         model = genai.GenerativeModel("models/gemini-2.5-flash")

#         # Generate JSON response
#         response = model.generate_content(
#             prompt,
#             generation_config=genai.types.GenerationConfig(
#                 temperature=0.1,
#                 response_mime_type="application/json",
#             ),
#         )
#         result_text = response.text.strip()
#     except Exception as e:
#         print("error", e)
#         result_text = None

#     if not result_text:
#         return None

#     try:
#         result_json = json.loads(result_text)
#         if "communication_point" in result_json:
#             result_json = result_json["communication_point"]
#             hr_obj.communication = result_json
#             time.sleep(1)
#             hr_obj.save(update_fields=["communication"])

#             return result_json
#     except json.JSONDecodeError:
#         print("⚠️ Could not decode JSON:", result_text)
#         return None


def analyze_facial_expressions(hr_pk):
    """
    Analyze facial expressions for all photos attached to the given HrModels record.
    Uses FER with mtcnn=True. Saves a summary list to HrModels.emotion_summary.

    Returns a list of dicts like: [{"expression": "happy", "count": 3}, ...] or None.
    """
    # Verify dependencies
    if FER is None or cv2 is None:
        print("FER/OpenCV not available. Please install 'fer', 'opencv-python', and 'mtcnn'.")
        return None

    try:
        hr_obj = HrModels.objects.get(pk=hr_pk)
    except HrModels.DoesNotExist:
        return None

    photos_qs = getattr(hr_obj, "photos", None)
    if not photos_qs:
        return None

    photos = list(photos_qs.all())
    if not photos:
        return None

    detector = FER(mtcnn=True)
    counts = {}

    for photo in photos:
        # Ensure the image path exists
        try:
            img_path = photo.image.path
        except Exception:
            continue

        img = cv2.imread(img_path)
        if img is None:
            continue

        try:
            result = detector.detect_emotions(img)
        except Exception:
            result = []

        if result:
            # Choose top emotion for the first detected face
            emotions = result[0].get("emotions", {})
            if emotions:
                top_expr = max(emotions, key=emotions.get)
                counts[top_expr] = counts.get(top_expr, 0) + 1

    if not counts:
        summary = []
    else:
        summary = sorted(
            [{"expression": k, "count": v} for k, v in counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

    # Save to model and return
    hr_obj.emotion_summary = summary
    hr_obj.save(update_fields=["emotion_summary"])
    return summary