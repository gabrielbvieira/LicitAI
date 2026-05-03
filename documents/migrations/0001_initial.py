from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="documents/%Y/%m/", verbose_name="Documento Original")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True, verbose_name="Data de Upload")),
                ("status", models.CharField(choices=[("pendente", "Pendente"), ("processado", "Processado"), ("erro", "Erro no processamento")], default="pendente", max_length=30, verbose_name="Status")),
                ("processing_error", models.TextField(blank=True, default="", verbose_name="Erro de Processamento")),
                ("document_name", models.CharField(blank=True, default="", max_length=500, verbose_name="Nome do Documento")),
                ("document_number", models.CharField(blank=True, default="", max_length=200, verbose_name="Nº Documento")),
                ("document_type", models.CharField(blank=True, default="", max_length=200, verbose_name="Tipo de Documento")),
                ("document_date", models.CharField(blank=True, default="", max_length=100, verbose_name="Data do Documento")),
                ("city", models.CharField(blank=True, default="", max_length=300, verbose_name="Cidade Origem")),
                ("requesting_agency", models.CharField(blank=True, default="", max_length=500, verbose_name="Órgão Solicitante")),
                ("identified_objects", models.TextField(blank=True, default="", verbose_name="Objetos Identificados")),
                ("extracted_text", models.TextField(blank=True, default="", verbose_name="Texto Extraído")),
            ],
            options={"ordering": ["-uploaded_at"], "verbose_name": "Documento", "verbose_name_plural": "Documentos"},
        ),
        migrations.CreateModel(
            name="RiskAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("risk_classification", models.CharField(choices=[("baixo", "Baixo Risco"), ("medio", "Médio Risco"), ("alto", "Alto Risco")], default="baixo", max_length=20, verbose_name="Classificação de Risco")),
                ("risk_score", models.IntegerField(default=0, verbose_name="Pontuação de Risco (0-100)")),
                ("justification", models.TextField(blank=True, default="", verbose_name="Justificativa")),
                ("warning_signs", models.TextField(blank=True, default="", help_text="Lista de sinais identificados, armazenada como JSON", verbose_name="Sinais de Alerta")),
                ("analyzed_at", models.DateTimeField(auto_now_add=True, verbose_name="Data da Análise")),
                ("analysis_error", models.TextField(blank=True, default="", verbose_name="Erro na Análise")),
                ("document", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="analysis", to="documents.document", verbose_name="Documento")),
            ],
            options={"verbose_name": "Análise de Risco", "verbose_name_plural": "Análises de Risco"},
        ),
    ]
