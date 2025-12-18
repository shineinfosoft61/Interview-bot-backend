import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext as _
from django.core.exceptions import ValidationError
from .managers import CustomUserManager

TECHNOLOGY_CHOICES = [
    # Programming Languages
    ('python', 'Python'),
    ('java', 'Java'),
    ('javascript', 'JavaScript'),
    ('typescript', 'TypeScript'),
    ('php', 'PHP'),
    ('ruby', 'Ruby'),
    ('csharp', 'C#'),
    ('cpp', 'C++'),
    ('go', 'Go'),
    ('swift', 'Swift'),
    ('kotlin', 'Kotlin'),
    ('rust', 'Rust'),

    # Popular Stacks
    ('mern', 'MERN'),
    ('mean', 'MEAN'),
    ('mevn', 'MEVN'),
    ('lamp', 'LAMP'),

    # Frontend Technologies
    ('react', 'React'),
    ('angular', 'Angular'),
    ('vue', 'Vue.js'),
    ('svelte', 'Svelte'),

    # Backend Frameworks
    ('django', 'Django'),
    ('flask', 'Flask'),
    ('fastapi', 'FastAPI'),
    ('spring_boot', 'Spring Boot'),
    ('dotnet', '.NET'),
    ('nodejs', 'Node.js'),
    ('express', 'Express'),
    ('laravel', 'Laravel'),

    # Mobile
    ('flutter', 'Flutter'),
    ('react_native', 'React Native'),
    ('android', 'Android'),
    ('ios', 'iOS'),
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
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    objects = CustomUserManager()

    def __str__(self):
        return self.email



class Requirement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="requirements/", null=True, blank=True)
    name = models.CharField(max_length=100,blank=True, null=True)
    experience = models.CharField(max_length=50,blank=True, null=True)
    technology = models.CharField(max_length=200, blank=True, null=True)
    No_of_openings = models.IntegerField(null=True, blank=True)
    notice_period = models.IntegerField(null=True, blank=True)
    priority = models.BooleanField(default=False)
    base_text = models.TextField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def clean(self):
        if self.technology:
            tech_values = [t.strip() for t in self.technology.split(',')]
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            
            for tech in tech_values:
                if tech not in valid_techs:
                    raise ValidationError(
                        f'Invalid technology "{tech}". Valid technologies are: {", ".join(valid_techs)}'
                    )

    def get_technologies(self):
        """Return list of technologies"""
        if self.technology:
            return [t.strip() for t in self.technology.split(',') if t.strip()]
        return []

    def set_technologies(self, tech_list):
        """Set technologies from a list"""
        if tech_list:
            self.technology = ','.join(tech_list)
        else:
            self.technology = ''

    def get_technology_display_names(self):
        """Return list of technology display names"""
        tech_values = self.get_technologies()
        tech_dict = dict(TECHNOLOGY_CHOICES)
        return [tech_dict.get(tech, tech) for tech in tech_values]

    def __str__(self):
        return f"{self.name} ({self.experience})"


# Technology utility functions
def get_technology_choices():
    """Return technology choices for API responses"""
    return [{'value': choice[0], 'label': choice[1]} for choice in TECHNOLOGY_CHOICES]

def normalize_technology_string(tech_string):
    """Normalize and validate technology string against choices"""
    if not tech_string:
        return []
    
    tech_values = [t.strip().lower() for t in tech_string.split(',')]
    valid_techs = {choice[0].lower(): choice[0] for choice in TECHNOLOGY_CHOICES}
    
    normalized = []
    for tech in tech_values:
        if tech in valid_techs:
            normalized.append(valid_techs[tech])
        else:
            # Try to find partial match
            for valid_key in valid_techs:
                if tech in valid_key or valid_key in tech:
                    normalized.append(valid_techs[valid_key])
                    break
    
    return list(set(normalized))  # Remove duplicates


class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requirement = models.ForeignKey(Requirement, on_delete=models.CASCADE, related_name="candidates",null=True, blank=True)
    upload_doc = models.FileField(upload_to='uploads/', blank=True, null=True)
    snapshots = models.FileField(upload_to='snapshorts/', blank=True, null=True)
    q_ans_file = models.FileField(upload_to='question-answer/', blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    name = models.CharField(max_length=100,blank=True, null=True)
    technology = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=15,blank=True, null=True)
    gmeet_link = models.URLField(max_length=300, blank=True, null=True)
    shine_link = models.URLField(max_length=300, blank=True, null=True)
    time = models.DateTimeField(blank=True, null=True)
    interview_status = models.CharField(max_length=50, choices=INTERVIEW_CHOICES, blank=True, null=True, default="Pending")
    interview_closed = models.BooleanField(default=False)
    photo = models.ImageField(upload_to='profile/', null=True, blank=True)
    experience = models.CharField(max_length=50, null=True, blank=True)
    tab_count = models.IntegerField(default=0)  
    photos = models.ManyToManyField('Photo', related_name='candidate_records', blank=True)
    emotion_summary = models.JSONField(blank=True, null=True)
    communication = models.JSONField(default=dict)
    company = models.JSONField(default=list)
    base_text = models.TextField(null=True, blank=True)
    is_selected = models.BooleanField(null=True, blank=True)
    is_quick = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def clean(self):
        if self.technology:
            tech_values = [t.strip() for t in self.technology.split(',')]
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            
            for tech in tech_values:
                if tech not in valid_techs:
                    raise ValidationError(
                        f'Invalid technology "{tech}". Valid technologies are: {", ".join(valid_techs)}'
                    )

    def get_technologies(self):
        """Return list of technologies"""
        if self.technology:
            return [t.strip() for t in self.technology.split(',') if t.strip()]
        return []

    def set_technologies(self, tech_list):
        """Set technologies from a list"""
        if tech_list:
            self.technology = ','.join(tech_list)
        else:
            self.technology = ''

    def get_technology_display_names(self):
        """Return list of technology display names"""
        tech_values = self.get_technologies()
        tech_dict = dict(TECHNOLOGY_CHOICES)
        return [tech_dict.get(tech, tech) for tech in tech_values]

    def __str__(self):
        return f"{self.name} ({self.email})"


class QuestionBank(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text = models.TextField(null=True, blank=True)
    technology = models.CharField(max_length=200, null=True, blank=True)
    difficulty_level = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='medium',null=True, blank=True
    )
    time_limit = models.IntegerField(default=120)
    is_default = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    


class Question(models.Model):
    text = models.TextField(null=True, blank=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="questions",null=True, blank=True)
    technology = models.CharField(max_length=200, null=True, blank=True)
    difficulty_level = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default='medium',null=True, blank=True
    )
    time_limit = models.IntegerField(default=120)
    is_default = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at']

    def clean(self):
        if self.technology:
            tech_values = [t.strip() for t in self.technology.split(',')]
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            
            for tech in tech_values:
                if tech not in valid_techs:
                    raise ValidationError(
                        f'Invalid technology "{tech}". Valid technologies are: {", ".join(valid_techs)}'
                    )

    def get_technologies(self):
        """Return list of technologies"""
        if self.technology:
            return [t.strip() for t in self.technology.split(',') if t.strip()]
        return []

    def set_technologies(self, tech_list):
        """Set technologies from a list"""
        if tech_list:
            self.technology = ','.join(tech_list)
        else:
            self.technology = ''

    def get_technology_display_names(self):
        """Return list of technology display names"""
        tech_values = self.get_technologies()
        tech_dict = dict(TECHNOLOGY_CHOICES)
        return [tech_dict.get(tech, tech) for tech in tech_values]

class Photo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ImageField(upload_to='photos/')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"Photo {self.id}"


class QuestionAnswer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="answers",null=True, blank=True)
    answer_text = models.TextField(null=True, blank=True)
    ai_response = models.TextField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)




