from rest_framework import serializers
from .models import Question, QuestionAnswer, Candidate, Photo, Requirement, User


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
    class Meta:
        model = Question
        fields = '__all__'

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
    class Meta:
        model = Candidate
        fields = '__all__'

class RequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Requirement
        fields = '__all__'

class InstagramDownloadSerializer(serializers.Serializer):
    url = serializers.URLField(required=True)


class ChatAiSerializer(serializers.Serializer):
    question = serializers.CharField()
