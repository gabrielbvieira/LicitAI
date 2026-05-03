from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="extraction_model",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="Modelo IA (Extração)"),
        ),
        migrations.AddField(
            model_name="riskanalysis",
            name="analysis_model",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="Modelo IA (Análise)"),
        ),
    ]
