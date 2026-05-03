"""Extract raw text from uploaded document files."""
import logging
import os
import time

logger = logging.getLogger("documents.text_extractor")


def extract_text(file_path: str) -> str:
    """Extract text content from a file (PDF, TXT, or DOCX)."""
    ext = os.path.splitext(file_path)[1].lower()
    size_kb = os.path.getsize(file_path) / 1024

    logger.info("Iniciando extração de texto...")
    logger.info("  Arquivo: %s", os.path.basename(file_path))
    logger.info("  Tipo: %s | Tamanho: %.1f KB", ext, size_kb)

    start = time.time()

    if ext == ".pdf":
        text = _extract_from_pdf(file_path)
    elif ext in (".txt", ".text"):
        text = _extract_from_text(file_path)
    elif ext in (".doc", ".docx"):
        text = _extract_from_docx(file_path)
    else:
        logger.warning("  Extensão '%s' não reconhecida, tentando como texto puro...", ext)
        text = _extract_from_text(file_path)

    elapsed = time.time() - start
    logger.info("  Extração concluída em %.2fs — %d caracteres extraídos", elapsed, len(text))

    if not text.strip():
        logger.warning("  AVISO: Nenhum texto foi extraído do documento!")

    return text


def _extract_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file using pdfplumber or PyPDF2."""
    try:
        import pdfplumber
        logger.info("  Usando pdfplumber para leitura do PDF...")
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info("  PDF possui %d página(s)", total_pages)
            for i, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    logger.debug("  Página %d/%d: %d caracteres", i, total_pages, len(page_text))
                else:
                    logger.debug("  Página %d/%d: sem texto extraível", i, total_pages)
        return "\n".join(text_parts)
    except ImportError:
        logger.info("  pdfplumber não disponível, tentando PyPDF2...")

    try:
        from PyPDF2 import PdfReader
        logger.info("  Usando PyPDF2 para leitura do PDF...")
        reader = PdfReader(file_path)
        logger.info("  PDF possui %d página(s)", len(reader.pages))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        logger.error("  ERRO: Nenhuma biblioteca PDF disponível! Instale pdfplumber ou PyPDF2.")
        return ""


def _extract_from_text(file_path: str) -> str:
    """Read a plain text file."""
    logger.info("  Lendo arquivo como texto puro...")
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        logger.error("  ERRO ao ler arquivo de texto: %s", e)
        return ""


def _extract_from_docx(file_path: str) -> str:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        logger.info("  Usando python-docx para leitura do DOCX...")
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        logger.info("  %d parágrafos extraídos", len(paragraphs))
        return "\n".join(paragraphs)
    except ImportError:
        logger.error("  ERRO: python-docx não instalado! pip install python-docx")
        return ""
    except Exception as e:
        logger.error("  ERRO ao ler DOCX: %s", e)
        return ""
