import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext as _
from .managers import CustomUserManager

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

USER_CHOICES = [
        ('Admin', 'Admin'),
        ('Normal', 'Normal'),
    ]

INTERVIEW_CHOICES = [
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Scheduled', 'Scheduled'),
        ('All', 'All'),
    ]

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True)
    designation = models.CharField(max_length=150, blank=True, null=True)
    role = models.CharField(max_length=50, choices=USER_CHOICES, blank=True, null=True, default="Normal")

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    objects = CustomUserManager()

    def __str__(self):
        return self.email


class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    technology = models.CharField(max_length=50, choices=TECHNOLOGY_CHOICES)
    experience = models.CharField(max_length=50)
    photo = models.ImageField(upload_to='photos/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Requirement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="requirements/", null=True, blank=True)
    name = models.CharField(max_length=100,blank=True, null=True)
    experience = models.CharField(max_length=50,blank=True, null=True)
    technology = models.CharField(max_length=50,blank=True, null=True)
    No_of_openings = models.IntegerField(null=True, blank=True)
    notice_period = models.IntegerField(null=True, blank=True)
    priority = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.experience})"


class HrModels(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requirement = models.ForeignKey(Requirement, on_delete=models.CASCADE, related_name="requirement",null=True, blank=True)
    upload_doc = models.FileField(upload_to='uploads/', blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    name = models.CharField(max_length=100,blank=True, null=True)
    technology = models.CharField(max_length=50,blank=True, null=True)
    phone = models.CharField(max_length=15,blank=True, null=True)
    gmeet_link = models.URLField(max_length=300, blank=True, null=True)
    shine_link = models.URLField(max_length=300, blank=True, null=True)
    time = models.DateTimeField(blank=True, null=True)
    interview_status = models.CharField(max_length=50, choices=INTERVIEW_CHOICES, blank=True, null=True, default="Pending")
    interview_closed = models.BooleanField(default=False)
    photo = models.ImageField(upload_to='photos/', null=True, blank=True)
    experience = models.CharField(max_length=50, null=True, blank=True)
    tab_count = models.IntegerField(default=0)
    photos = models.ManyToManyField('Photo', related_name='hr_records', blank=True)
    emotion_summary = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    communication = models.JSONField(default=dict)
    company = models.JSONField(default=list)

    def __str__(self):
        return f"{self.name} ({self.email})"


class Question(models.Model):
    text = models.TextField(null=True, blank=True)
    hr = models.ForeignKey(HrModels, on_delete=models.CASCADE, related_name="questions",null=True, blank=True)
    technology = models.CharField(max_length=50, choices=TECHNOLOGY_CHOICES,null=True, blank=True)
    difficulty_level = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='medium',null=True, blank=True
    )
    time_limit = models.IntegerField(default=120)
    created_at = models.DateTimeField(auto_now_add=True)


class Photo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ImageField(upload_to='photos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo {self.id}"


class QuestionAnswer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    hr = models.ForeignKey(HrModels, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    answer_text = models.TextField(null=True, blank=True)
    ai_response = models.TextField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)



