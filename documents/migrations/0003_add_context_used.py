from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_add_model_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="riskanalysis",
            name="context_used",
            field=models.TextField(
                blank=True, default="",
                help_text="Dados pesquisados na web e injetados no prompt para enriquecer a análise.",
                verbose_name="Contexto Pesquisado (RAG)",
            ),
        ),
    ]
