"""Forms for document upload."""
from django import forms
from .models import Document


class DocumentUploadForm(forms.ModelForm):
    """Simple form with only the file field."""

    class Meta:
        model = Document
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(
                attrs={"accept": ".pdf,.txt,.doc,.docx", "class": "form-control"}
            ),
        }
