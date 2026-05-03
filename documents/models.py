"""Models for storing bidding documents, extracted metadata, and risk analysis."""
from django.db import models


class Document(models.Model):
    """Stores the uploaded document and its automatically extracted metadata."""

    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("processado", "Processado"),
        ("erro", "Erro no processamento"),
    ]

    # Original file
    file = models.FileField("Documento Original", upload_to="documents/%Y/%m/")
    uploaded_at = models.DateTimeField("Data de Upload", auto_now_add=True)

    # Processing status
    status = models.CharField(
        "Status", max_length=30, choices=STATUS_CHOICES, default="pendente"
    )
    processing_error = models.TextField("Erro de Processamento", blank=True, default="")

    # Automatically extracted metadata (all nullable for resilience)
    document_name = models.CharField("Nome do Documento", max_length=500, blank=True, default="")
    document_number = models.CharField("Nº Documento", max_length=200, blank=True, default="")
    document_type = models.CharField("Tipo de Documento", max_length=200, blank=True, default="")
    document_date = models.CharField("Data do Documento", max_length=100, blank=True, default="")
    city = models.CharField("Cidade Origem", max_length=300, blank=True, default="")
    requesting_agency = models.CharField("Órgão Solicitante", max_length=500, blank=True, default="")
    identified_objects = models.TextField("Objetos Identificados", blank=True, default="")
    requirements = models.TextField(
        "Requisitos Técnicos", blank=True, default="",
        help_text="Lista de requisitos e especificações técnicas extraídos do edital pela IA."
    )

    # AI model used for metadata extraction
    extraction_model = models.CharField("Modelo IA (Extração)", max_length=200, blank=True, default="")

    # Raw extracted text (for reference)
    extracted_text = models.TextField("Texto Extraído", blank=True, default="")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"

    def __str__(self):
        return self.document_name or f"Documento #{self.pk}"

    @property
    def filename(self):
        """Return just the filename from the file path."""
        if self.file:
            return self.file.name.split("/")[-1]
        return ""


class RiskAnalysis(models.Model):
    """Stores the AI-generated risk analysis for a document."""

    RISK_CHOICES = [
        ("baixo", "Baixo Risco"),
        ("medio", "Médio Risco"),
        ("alto", "Alto Risco"),
    ]

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="analysis",
        verbose_name="Documento"
    )
    risk_classification = models.CharField(
        "Classificação de Risco", max_length=20, choices=RISK_CHOICES, default="baixo"
    )
    risk_score = models.IntegerField("Pontuação de Risco (0-100)", default=0)
    justification = models.TextField("Justificativa", blank=True, default="")
    warning_signs = models.TextField(
        "Sinais de Alerta", blank=True, default="",
        help_text="Lista de sinais identificados, armazenada como JSON"
    )
    analyzed_at = models.DateTimeField("Data da Análise", auto_now_add=True)
    analysis_model = models.CharField("Modelo IA (Análise)", max_length=200, blank=True, default="")
    context_used = models.TextField(
        "Contexto Pesquisado (RAG)", blank=True, default="",
        help_text="Dados pesquisados na web e injetados no prompt para enriquecer a análise."
    )
    analysis_error = models.TextField("Erro na Análise", blank=True, default="")

    class Meta:
        verbose_name = "Análise de Risco"
        verbose_name_plural = "Análises de Risco"

    def __str__(self):
        return f"Análise: {self.document} - {self.get_risk_classification_display()}"

    @property
    def warning_signs_list(self):
        """Return warning signs as a Python list."""
        import json
        if not self.warning_signs:
            return []
        try:
            return json.loads(self.warning_signs)
        except (json.JSONDecodeError, TypeError):
            return [self.warning_signs]
