from django.db import models
import uuid

class Question(models.Model):
    TECHNOLOGY_CHOICES = [
        ('python', 'Python'),
        ('.net', '.NET'),
        ('java', 'Java'),
        ('react', 'React'),
    ]

    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    text = models.TextField()
    technology = models.CharField(max_length=50, choices=TECHNOLOGY_CHOICES)
    difficulty_level = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='medium'
    )
    time_limit = models.IntegerField(default=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.text[:50]}... ({self.technology})"
    


class Candidate(models.Model):
    TECHNOLOGY_CHOICES = [
        ('python', 'Python'),
        ('.net', '.NET'),
        ('java', 'Java'),
        ('react', 'React'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    technology = models.CharField(max_length=50, choices=TECHNOLOGY_CHOICES)
    experience = models.CharField(max_length=50)
    photo = models.ImageField(upload_to='photos/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
class QuestionAnswer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    answer_text = models.TextField(null=True, blank=True)
    ai_response = models.TextField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Answer to Q{self.question.id}: {self.answer_text[:30]}..."
