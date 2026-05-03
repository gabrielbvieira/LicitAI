"""Admin configuration for document inspection."""
from django.contrib import admin
from .models import Document, RiskAnalysis


class RiskAnalysisInline(admin.StackedInline):
    model = RiskAnalysis
    extra = 0
    readonly_fields = ("analyzed_at", "context_used")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "document_name", "document_type", "city", "extraction_model", "status", "uploaded_at")
    list_filter = ("status", "document_type")
    search_fields = ("document_name", "document_number", "city", "requesting_agency")
    readonly_fields = ("uploaded_at", "extracted_text", "requirements")
    inlines = [RiskAnalysisInline]


@admin.register(RiskAnalysis)
class RiskAnalysisAdmin(admin.ModelAdmin):
    list_display = ("document", "risk_classification", "risk_score", "analysis_model", "has_context", "analyzed_at")
    list_filter = ("risk_classification", "analysis_model")
    readonly_fields = ("analyzed_at", "context_used")

    @admin.display(boolean=True, description="Contexto RAG")
    def has_context(self, obj):
        return bool(obj.context_used)
