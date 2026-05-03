"""Service for extracting metadata from document text using local AI."""
import json
import logging
import time

from .ollama_client import OllamaClient

logger = logging.getLogger("documents.metadata_extractor")

EXTRACTION_PROMPT = """Você é um assistente especializado em análise de documentos de licitações públicas brasileiras.

Analise o texto abaixo e extraia os seguintes metadados. Responda APENAS com um JSON válido, sem texto antes ou depois.

INSTRUÇÕES OBRIGATÓRIAS:
- Extraia os dados diretamente do texto.
- Se um campo não for encontrado no texto, use string vazia "".
- NÃO invente dados. Extraia apenas o que está presente.
- Responda SOMENTE com o JSON, sem explicações.

Responda exatamente neste formato:
{{
  "document_name": "nome ou título do documento/edital",
  "document_number": "número do documento, edital ou processo",
  "document_type": "tipo (Edital, Pregão Eletrônico, Tomada de Preços, Convite, Concorrência, etc.)",
  "document_date": "data do documento no formato encontrado",
  "city": "cidade de origem",
  "requesting_agency": "órgão ou entidade solicitante",
  "identified_objects": "descrição do objeto da licitação — o que está sendo contratado ou adquirido"
}}

TEXTO DO DOCUMENTO:
---
{text}
---

JSON:"""


def extract_metadata(text: str) -> dict:
    """Extract metadata from document text using the Ollama AI model."""
    default = {
        "document_name": "",
        "document_number": "",
        "document_type": "",
        "document_date": "",
        "city": "",
        "requesting_agency": "",
        "identified_objects": "",
    }

    logger.info("=" * 60)
    logger.info("ETAPA 1: EXTRAÇÃO DE METADADOS")
    logger.info("=" * 60)

    if not text or not text.strip():
        logger.warning("Texto vazio fornecido — retornando metadados padrão.")
        return default

    truncated = text[:6000]
    logger.info("Texto truncado para %d caracteres (de %d originais)", len(truncated), len(text))

    max_attempts = 2
    client = OllamaClient()

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Tentativa %d/%d — Chamando Ollama para extração de metadados...", attempt, max_attempts)
            start = time.time()

            prompt = EXTRACTION_PROMPT.format(text=truncated)
            response = client.generate(prompt)

            elapsed = time.time() - start
            logger.info("Resposta da IA recebida em %.1fs", elapsed)
            logger.debug("Resposta bruta: %s", response[:800])

            metadata = _parse_json_response(response)
            if metadata:
                # Validate: at least some expected keys must be present
                matched_keys = set(metadata.keys()) & set(default.keys())
                if len(matched_keys) >= 3:
                    result = {k: str(metadata.get(k, "")) for k in default}
                    logger.info("Metadados extraídos com sucesso (%d/%d campos reconhecidos):", len(matched_keys), len(default))
                    for k, v in result.items():
                        display = (v[:80] + "...") if len(str(v)) > 80 else v
                        logger.info("  %-22s: %s", k, display or "(vazio)")
                    return result
                else:
                    logger.warning(
                        "Tentativa %d: JSON parseado mas estrutura inválida — apenas %d chaves reconhecidas: %s",
                        attempt, len(matched_keys), matched_keys
                    )
                    logger.warning("Chaves recebidas da IA: %s", list(metadata.keys()))
            else:
                logger.warning("Tentativa %d: Resposta não é JSON válido.", attempt)

            if attempt < max_attempts:
                logger.info("Realizando nova tentativa...")

        except (ConnectionError, RuntimeError) as e:
            logger.error("ERRO na comunicação com Ollama: %s", e)
            raise
        except Exception as e:
            logger.error("ERRO inesperado na extração de metadados: %s", e)
            raise

    logger.warning("Todas as tentativas falharam. Retornando metadados vazios.")
    return default


def _parse_json_response(text: str) -> dict | None:
    """Try to parse a JSON object from the AI response."""
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None
