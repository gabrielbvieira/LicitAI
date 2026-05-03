from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_add_context_used"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="requirements",
            field=models.TextField(
                blank=True, default="",
                help_text="Lista de requisitos e especificações técnicas extraídos do edital pela IA.",
                verbose_name="Requisitos Técnicos",
            ),
        ),
    ]
