from rest_framework import serializers
from .models import Candidate, Question, QuestionAnswer, HrModels, Photo

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = '__all__'


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
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
        model = HrModels
        fields = '__all__'