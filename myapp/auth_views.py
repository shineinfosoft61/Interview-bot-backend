from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, login as auth_login
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User
from .serializers import RegisterSerializer, LoginSerializer

class RegisterView(APIView):
    serializer_class = RegisterSerializer

    def get(self, request):
        users = User.objects.all()
        serializer = RegisterSerializer(users, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        data = request.data
        try:
            User.objects.get(username=data['username'])
            return Response({"status": "error", "message": f"User with this username address already exists."}, status=400)
        except:
            serializer = self.serializer_class(data=data)
            if serializer.is_valid():
                serializer.save()
                return Response({"status": "success", "message": "User created successfully!","data":serializer.data}, status=200)
            
            return Response(serializer.errors, status=400)
        
    def put(self, request, pk=None):
        data = request.data
        try:
            user_obj = User.objects.get(id=pk)
        except User.DoesNotExist:
            return Response({"status": "error", "message": f"User Does not exist with ID: {pk}"}, status=400)
        
        serializer = RegisterSerializer(user_obj, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "message": "Profile updated successfully!"}, status=200)
        return Response(serializer.errors, status=400)


class LoginView(APIView):
    serializer_class = LoginSerializer
    
    def post(self, request):
        data = request.data
        print("data-------", data)
        serializer = self.serializer_class(data=data)
        
        if serializer.is_valid():
            email = serializer.validated_data.get('email')
            password = serializer.validated_data.get('password')
            
            try:
                user_obj = User.objects.get(email=email)
                print(user_obj.is_active)
                if not user_obj.is_active:
                    return Response({"status": "error", "message": "Your account has been disabled!"}, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return Response({"status": "error", "message": "The email provided is invalid."}, status=status.HTTP_400_BAD_REQUEST)
            
            user = authenticate(email=email, password=password)
            if user is not None:
                auth_login(request, user)
                refresh = RefreshToken.for_user(user)
                
                response = {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'role': user.role,
                        'is_staff': user.is_staff,
                        }
                }
                return Response(response, status=status.HTTP_200_OK)
            return Response({"status": "error", "message": "The password provided is invalid."}, status=status.HTTP_400_BAD_REQUEST)
        print("-----------------")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
