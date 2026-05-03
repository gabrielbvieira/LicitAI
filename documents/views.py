"""Views for document upload and detail display."""
import json
import logging
import time

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings

from .models import Document, RiskAnalysis
from .forms import DocumentUploadForm
from .services.text_extractor import extract_text
from .services.metadata_extractor import extract_metadata
from .services.requirements_extractor import extract_requirements
from .services.context_enricher import enrich_context
from .services.risk_analyzer import analyze_risk

logger = logging.getLogger("documents.views")


def upload_document(request):
    """Handle document upload, trigger extraction and analysis."""
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES["file"]
            logger.info("=" * 60)
            logger.info("NOVO DOCUMENTO RECEBIDO")
            logger.info("=" * 60)
            logger.info("  Nome do arquivo: %s", uploaded_file.name)
            logger.info("  Tamanho: %.1f KB", uploaded_file.size / 1024)
            logger.info("  Tipo MIME: %s", uploaded_file.content_type)

            doc = form.save()
            logger.info("  Documento salvo no banco — ID: %d", doc.pk)
            logger.info("  Caminho: %s", doc.file.path)

            total_start = time.time()

            # Step 1: Extract text
            logger.info("-" * 60)
            try:
                text = extract_text(doc.file.path)
                doc.extracted_text = text
            except Exception as e:
                doc.status = "erro"
                doc.processing_error = f"Erro na extração de texto: {e}"
                doc.save()
                logger.error("PIPELINE INTERROMPIDO: Falha na extração de texto — %s", e)
                messages.warning(request, "Documento salvo, mas houve erro na extração de texto.")
                return redirect("document_detail", pk=doc.pk)

            # Step 2: Extract metadata via AI
            logger.info("-" * 60)
            try:
                metadata = extract_metadata(text)
                doc.document_name = metadata.get("document_name", "")
                doc.document_number = metadata.get("document_number", "")
                doc.document_type = metadata.get("document_type", "")
                doc.document_date = metadata.get("document_date", "")
                doc.city = metadata.get("city", "")
                doc.requesting_agency = metadata.get("requesting_agency", "")
                doc.identified_objects = metadata.get("identified_objects", "")
                doc.extraction_model = settings.OLLAMA_MODEL
                doc.status = "processado"
            except Exception as e:
                doc.status = "erro"
                doc.processing_error = f"Erro na extração de metadados: {e}"
                doc.save()
                logger.error("PIPELINE INTERROMPIDO: Falha na extração de metadados — %s", e)
                messages.warning(
                    request,
                    "Documento salvo, mas a extração de metadados falhou. "
                    "Verifique se o Ollama está rodando."
                )
                return redirect("document_detail", pk=doc.pk)

            doc.save()
            logger.info("Metadados salvos no banco de dados.")

            # Step 3: Extract technical requirements
            logger.info("-" * 60)
            requirements = extract_requirements(text)
            if requirements:
                doc.requirements = requirements
                doc.save(update_fields=["requirements"])
                logger.info("Requisitos salvos no banco (%d caracteres).", len(requirements))
            else:
                logger.warning("Nenhum requisito extraído — análise usará texto completo.")

            # Step 4: Context enrichment via web search (RAG)
            logger.info("-" * 60)
            context = enrich_context(
                city=doc.city,
                identified_objects=doc.identified_objects,
            )

            # Step 5: Risk analysis (using ONLY requirements, not full document)
            logger.info("-" * 60)
            analysis_input = requirements if requirements else text
            logger.info("Análise de risco usando: %s", "REQUISITOS" if requirements else "TEXTO COMPLETO (fallback)")
            try:
                result = analyze_risk(analysis_input, context=context)
                RiskAnalysis.objects.create(
                    document=doc,
                    risk_classification=result["risk_classification"],
                    risk_score=result["risk_score"],
                    justification=result["justification"],
                    warning_signs=json.dumps(
                        result.get("warning_signs", []), ensure_ascii=False
                    ),
                    analysis_model=settings.OLLAMA_MODEL,
                    context_used=context,
                )
                logger.info("Análise de risco salva no banco de dados.")
            except Exception as e:
                RiskAnalysis.objects.create(
                    document=doc,
                    analysis_model=settings.OLLAMA_MODEL,
                    context_used=context,
                    analysis_error=f"Erro na análise de risco: {e}",
                )
                logger.error("Análise de risco falhou — %s", e)
                logger.info("Registro de erro salvo no banco.")
                messages.warning(request, "Metadados extraídos, mas a análise de risco falhou.")

            total_elapsed = time.time() - total_start
            logger.info("=" * 60)
            logger.info("PIPELINE CONCLUÍDO em %.1fs — Documento ID: %d", total_elapsed, doc.pk)
            logger.info("=" * 60)

            messages.success(request, "Documento processado com sucesso!")
            return redirect("document_detail", pk=doc.pk)
    else:
        form = DocumentUploadForm()

    recent_docs = Document.objects.all()[:10]
    return render(request, "documents/upload.html", {
        "form": form,
        "recent_docs": recent_docs,
    })


def document_detail(request, pk):
    """Display extracted metadata and risk analysis for a document."""
    doc = get_object_or_404(Document, pk=pk)
    analysis = getattr(doc, "analysis", None)
    logger.debug("Visualizando documento ID: %d", pk)
    return render(request, "documents/detail.html", {
        "doc": doc,
        "analysis": analysis,
    })
