from django.urls import path
from . import views

urlpatterns = [
    path("", views.upload_document, name="upload_document"),
    path("documento/<int:pk>/", views.document_detail, name="document_detail"),
]
