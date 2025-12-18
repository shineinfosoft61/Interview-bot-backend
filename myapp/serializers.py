from rest_framework import serializers
from .models import Question, QuestionAnswer, Candidate, Photo, Requirement, User, QuestionBank, get_technology_choices, normalize_technology_string


class RegisterSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ['id','username','email','password','role']
    
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = super().create(validated_data)
        user.set_password(password)
        user.save()
        return user
    
class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField()
    
class QuestionSerializer(serializers.ModelSerializer):
    technology_list = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of technology values (e.g., ['python', 'aws'])"
    )
    technology_display = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="List of technology display names"
    )
    
    class Meta:
        model = Question
        fields = '__all__'
    
    def validate_technology_list(self, value):
        """Validate technology list against choices"""
        if value:
            valid_techs = [choice[0] for choice in Question._meta.get_field('technology').choices] if hasattr(Question._meta.get_field('technology'), 'choices') else []
            if valid_techs:  # Only validate if choices are defined
                for tech in value:
                    if tech not in valid_techs:
                        raise serializers.ValidationError(f"Invalid technology '{tech}'. Valid technologies: {valid_techs}")
        return value
    
    def create(self, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list:
            validated_data['technology'] = ','.join(technology_list)
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list is not None:
            instance.technology = ','.join(technology_list)
        return super().update(instance, validated_data)
    
    def to_representation(self, instance):
        """Add technology_display field"""
        data = super().to_representation(instance)
        data['technology_display'] = instance.get_technology_display_names()
        return data

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionAnswer
        fields = '__all__'

class AnswerHrSerializer(serializers.ModelSerializer):
    question = QuestionSerializer()
    class Meta:
        model = QuestionAnswer
        fields = '__all__'

class PhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Photo
        fields = '__all__'

class HrSerializer(serializers.ModelSerializer):
    answers = AnswerHrSerializer(many=True, read_only=True)
    photos = PhotoSerializer(many=True, read_only=True)
    technology_list = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of technology values (e.g., ['python', 'aws'])"
    )
    technology_display = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="List of technology display names"
    )
    
    class Meta:
        model = Candidate
        fields = '__all__'
    
    def validate_technology_list(self, value):
        """Validate technology list against choices"""
        if value:
            from .models import TECHNOLOGY_CHOICES
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            for tech in value:
                if tech not in valid_techs:
                    raise serializers.ValidationError(f"Invalid technology '{tech}'. Valid technologies: {valid_techs}")
        return value
    
    def create(self, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list:
            validated_data['technology'] = ','.join(technology_list)
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list is not None:
            instance.technology = ','.join(technology_list)
        return super().update(instance, validated_data)
    
    def to_representation(self, instance):
        """Add technology_display field"""
        data = super().to_representation(instance)
        data['technology_display'] = instance.get_technology_display_names()
        return data

class PublicCandidateSerializer(serializers.ModelSerializer):
    technology_display = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="List of technology display names"
    )
    
    class Meta:
        model = Candidate
        fields = ['interview_closed', 'name', 'technology', 'experience', 'technology_display']
    
    def to_representation(self, instance):
        """Add technology_display field"""
        data = super().to_representation(instance)
        data['technology_display'] = instance.get_technology_display_names()
        return data

class RequirementSerializer(serializers.ModelSerializer):
    technology_list = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
        help_text="List of technology values (e.g., ['python', 'aws'])"
    )
    technology_display = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="List of technology display names"
    )
    
    class Meta:
        model = Requirement
        fields = '__all__'
    
    def validate_technology_list(self, value):
        """Validate technology list against choices"""
        if value:
            from .models import TECHNOLOGY_CHOICES
            valid_techs = [choice[0] for choice in TECHNOLOGY_CHOICES]
            for tech in value:
                if tech not in valid_techs:
                    raise serializers.ValidationError(f"Invalid technology '{tech}'. Valid technologies: {valid_techs}")
        return value
    
    def create(self, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list:
            validated_data['technology'] = ','.join(technology_list)
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        """Handle technology_list field"""
        technology_list = validated_data.pop('technology_list', None)
        if technology_list is not None:
            instance.technology = ','.join(technology_list)
        return super().update(instance, validated_data)
    
    def to_representation(self, instance):
        """Add technology_display field"""
        data = super().to_representation(instance)
        data['technology_display'] = instance.get_technology_display_names()
        return data

class InstagramDownloadSerializer(serializers.Serializer):
    url = serializers.URLField(required=True)


class ChatAiSerializer(serializers.Serializer):
    question = serializers.CharField()

class TechnologyChoicesSerializer(serializers.Serializer):
    """Serializer to return technology choices for frontend"""
    choices = serializers.SerializerMethodField()
    
    def get_choices(self, obj):
        return get_technology_choices()


class QuestionBankSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionBank
        fields = "__all__"