import json
from openai import OpenAI
from django.conf import settings
from .models import HrModels, QuestionAnswer
import time
from collections import Counter

try:
    from fer.fer import FER
    import cv2
except Exception as e:
    print("FER/OpenCV import failed:", e)
    FER = None
    cv2 = None


def analyze_facial_expressions(hr_obj):
    """
    Analyze facial expressions for all photos attached to the given HrModels record
    using FER (mtcnn=True). Looks at ALL detected faces in every image.

    Saves a structured summary to `HrModels.emotion_summary` and returns it, for example:
    {
        "total_photos": 3,
        "total_faces": 5,
        "emotion_counts": {"happy": 2, "neutral": 2, "angry": 1},
        "title_summary": {"Good": 2, "Neutral": 2, "Bad": 1},
        "report_lines": ["Good (40%): Facial expressions showed strong focus and interest.", ...]
    }
    """
    # Verify dependencies
    if FER is None or cv2 is None:
        print("FER/OpenCV not available. Please install 'fer', 'opencv-python', and 'mtcnn'.")
        return None

    photos_qs = getattr(hr_obj, "photos", None)
    if not photos_qs:
        return None

    photos = list(photos_qs.all())
    if not photos:
        return None

    # Initialize FER detectors (primary with MTCNN, fallback without)
    detector = FER(mtcnn=True)
    try:
        fallback_detector = FER(mtcnn=False)
    except Exception:
        fallback_detector = None

    # Store all detected emotions across all faces and photos
    all_emotions: list[str] = []
    total_faces = 0

    for photo in photos:
        # Resolve image path from Photo model
        try:
            img_path = photo.image.path
        except Exception:
            continue

        img = cv2.imread(img_path)
        if img is None:
            continue

        # Convert BGR (OpenCV) to RGB (expected by FER/MTCNN)
        try:
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        except Exception:
            img_rgb = img

        # Resize very large images to speed up and help detection; upscale very small ones
        try:
            h, w = img_rgb.shape[:2]
            max_side = max(h, w)
            min_side = min(h, w)
            # downscale overly large images
            if max_side > 1280:
                scale = 1280.0 / max_side
                new_w, new_h = int(w * scale), int(h * scale)
                img_rgb = cv2.resize(img_rgb, (new_w, new_h))
            # upscale very small images to help detectors
            elif min_side < 400:
                scale = 400.0 / float(min_side)
                new_w, new_h = int(w * scale), int(h * scale)
                img_rgb = cv2.resize(img_rgb, (new_w, new_h))
        except Exception:
            pass

        try:
            results = detector.detect_emotions(img_rgb)  # list of faces with emotions
        except Exception:
            results = []

        # Fallback: retry without MTCNN if nothing found
        if not results and fallback_detector is not None:
            try:
                results = fallback_detector.detect_emotions(img_rgb)
                print("fallback_without_mtcnn_faces", len(results))
            except Exception:
                pass

        # Second fallback: Haar Cascade face detection + per-face emotion on crops
        if not results:
            try:
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
                print("haar_faces", len(faces))
                crop_results = []
                for (x, y, w, h) in faces:
                    # pad a bit to include context
                    pad = int(0.1 * max(w, h))
                    x0 = max(0, x - pad)
                    y0 = max(0, y - pad)
                    x1 = min(img_rgb.shape[1], x + w + pad)
                    y1 = min(img_rgb.shape[0], y + h + pad)
                    face_crop = img_rgb[y0:y1, x0:x1]
                    if face_crop.size == 0:
                        continue
                    # Use the best available FER (fallback without mtcnn preferred on crops)
                    emotion = None
                    score = 0.0
                    try:
                        if fallback_detector is not None:
                            emotion, score = fallback_detector.top_emotion(face_crop)
                        else:
                            emotion, score = detector.top_emotion(face_crop)
                    except Exception:
                        pass
                    if emotion:
                        crop_results.append({"box": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)], "emotions": {emotion: score}})
                if crop_results:
                    results = crop_results
            except Exception as e:
                print("haar_fallback_error", e)

        # Count faces in this image
        total_faces += len(results)
        print("detected_faces_count", len(results))

        # Collect top emotion for each detected face
        for face in results:
            emotions = face.get("emotions", {})
            if not emotions:
                continue
            top_emotion = max(emotions, key=emotions.get)
            all_emotions.append(top_emotion)

    # Prepare the result structure
    if total_faces == 0:
        result_data = {
            "total_photos": len(photos),
            "total_faces": 0,
            "emotion_counts": {},
            "title_summary": {},
            "report_lines": ["No faces detected in the images."],
        }
    else:
        # Count each emotion across all faces
        emotion_counts = Counter(all_emotions)

        # Define 3 main titles mapping
        main_titles = {
            "Good": ["happy", "surprise"],               # Positive / focused
            "Neutral": ["neutral"],                        # Calm / composed
            "Bad": ["sad", "angry", "fear", "disgust"],   # Negative / distracted
        }

        # Prepare summary counts for the three buckets
        title_summary = {}
        for title, emotions in main_titles.items():
            count = sum(emotion_counts.get(e, 0) for e in emotions)
            title_summary[title] = count

        # Generate human-readable report lines
        total_expressions = sum(title_summary.values()) or 1
        report_lines = []
        for title, count in title_summary.items():
            if count > 0:
                percentage = round((count / total_expressions) * 100)
                if title == "Good":
                    comment = "Facial expressions showed strong focus and interest."
                elif title == "Neutral":
                    comment = "Facial expressions were calm and composed."
                else:
                    comment = "Facial expressions indicated distraction or stress."
                report_lines.append(f"{title} ({percentage}%): {comment}")

        result_data = {
            "total_photos": len(photos),
            "total_faces": total_faces,
            "emotion_counts": dict(emotion_counts),
            "title_summary": title_summary,
            "report_lines": report_lines,
        }
        print("result_data", result_data)
    # Save to model and return
    hr_obj.emotion_summary = result_data
    hr_obj.save(update_fields=["emotion_summary"])
    return result_data