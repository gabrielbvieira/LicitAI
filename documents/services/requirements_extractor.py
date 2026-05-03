"""Service for extracting technical requirements from bidding documents."""
import logging
import re
from typing import List, Set

from .ollama_client import OllamaClient

logger = logging.getLogger("documents.requirements_extractor")

BASE_REQUIREMENTS_PROMPT = """Você é um extrator de requisitos técnicos de licitações públicas.

Analise o trecho abaixo e extraia TODOS os requisitos técnicos, comerciais e operacionais do objeto licitado.

REGRAS:
- Retorne somente os requisitos.
- Um requisito por linha.
- Não explique.
- Não resuma.
- Não faça comentários.
- Não escreva introdução.
- Não escreva frases como "não encontrei" ou "segue abaixo".
- Inclua especificações técnicas, quantidades, unidades, prazos, condições de execução, seguros, franquias, exigências de entrega, modelo de referência, valores e qualquer detalhe que restrinja o objeto.

TRECHO:
{text}
"""

ADDITIONAL_REQUIREMENTS_PROMPT = """Você está revisando um edital para encontrar requisitos adicionais que possam ter ficado fora da seção principal.

REQUISITOS JÁ IDENTIFICADOS:
{known_requirements}

TAREFA:
- Leia o trecho abaixo.
- Extraia SOMENTE requisitos NOVOS que ainda não estejam na lista já identificada.
- Considere especificações técnicas, quantidades, unidades, prazos, condições de execução, seguro, franquia, entrega, modelo de referência, valores, garantia e qualquer restrição relevante do objeto.
- Se não houver nenhum requisito novo, responda apenas com:
NENHUM

REGRAS:
- Um requisito por linha.
- Não explique.
- Não comente.
- Não repita requisitos já identificados.

TRECHO:
{text}
"""

RELEVANT_KEYWORDS = [
    "especificações mínimas",
    "especificações técnicas",
    "descrição",
    "objeto",
    "termo de referência",
    "anexo i",
    "modelo de referência",
    "valor mensal",
    "valor total",
    "franquia",
    "seguro",
    "garantia",
    "prazo",
    "entrega",
    "execução",
    "veículo",
    "suv",
    "motor",
    "potência",
    "airbag",
    "freios",
    "bluetooth",
    "carplay",
    "android auto",
]


def _normalize_text(text: str) -> str:
    """Normalize extracted text.

    Args:
        text (str): Full extracted document text.

    Returns:
        str: Normalized text.
    """
    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _remove_noise_lines(text: str) -> str:
    """Remove common PDF extraction noise lines.

    Args:
        text (str): Raw extracted text.

    Returns:
        str: Cleaned text.
    """
    noise_exact = {
        "USTIMAKAT",
        "LAVRUD",
        "LEAFAR",
        ":AOSSEP",
        "ROP",
        "ODANISSA",
    }

    cleaned_lines: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        upper_line = line.upper()

        if upper_line in noise_exact:
            continue

        if upper_line.startswith("HTTP://") or upper_line.startswith("HTTPS://"):
            continue

        if "MARILIA.1DOC.COM.BR" in upper_line:
            continue

        if "ASSINATURAS" in upper_line and "VERIFICAR" in upper_line:
            continue

        if re.fullmatch(r"[A-Z0-9\\-]{8,}", upper_line):
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)

    replacements = [
        (r"eletro-\s*\n\s*retráteis", "eletro-retráteis"),
        (r"anti-\s*\n\s*furto", "antifurto"),
        (r"mudança de\s*\n\s*faixa", "mudança de faixa"),
        (r"Bluetooth via\s*\n\s*CarPlay", "Bluetooth via CarPlay"),
        (r"Franquia\s*\n\s*mínima", "Franquia mínima"),
        (r"sem condutor e sem\s*\n\s*combustível", "sem condutor e sem combustível"),
        (
            r"taxa por quilometragem\s*\n\s*dentro deste limite",
            "taxa por quilometragem dentro deste limite",
        ),
        (r"MODELO DE REFERÊCIA", "MODELO DE REFERÊNCIA"),
    ]

    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_main_requirements_section(text: str) -> str:
    """Extract the main requirements section from the document.

    Args:
        text (str): Full normalized document text.

    Returns:
        str: Main requirements section or an empty string if not found.
    """
    upper_text = text.upper()

    start_keywords = [
        "ESPECIFICAÇÕES MÍNIMAS",
        "ESPECIFICAÇÕES TÉCNICAS",
        "ANEXO I",
    ]

    end_keywords = [
        "OBSERVAÇÕES:",
        "ANEXO II",
        "MODELO DE PROPOSTA",
        "5. DA JUSTIFICATIVA",
        "5. JUSTIFICATIVA",
    ]

    start_pos = -1
    used_start_keyword = ""

    for keyword in start_keywords:
        pos = upper_text.find(keyword)
        if pos != -1:
            start_pos = pos
            used_start_keyword = keyword
            break

    if start_pos == -1:
        logger.warning("Main requirements section not found.")
        return ""

    end_pos = len(text)
    used_end_keyword = ""

    for keyword in end_keywords:
        pos = upper_text.find(keyword, start_pos + 1)
        if pos != -1:
            end_pos = pos
            used_end_keyword = keyword
            break

    section = text[start_pos:end_pos].strip()

    logger.info(
        "Main requirements section found using start '%s' and end '%s' (%d chars).",
        used_start_keyword,
        used_end_keyword or "EOF",
        len(section),
    )
    return section


def _split_text_into_chunks(
    text: str,
    chunk_size: int = 3500,
    overlap: int = 400,
) -> List[str]:
    """Split text into overlapping chunks.

    Args:
        text (str): Text to split.
        chunk_size (int): Maximum chunk size.
        overlap (int): Overlap size between chunks.

    Returns:
        List[str]: List of text chunks.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0

    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end == len(text):
            break

        start = max(end - overlap, start + 1)

    return chunks


def _is_relevant_chunk(text: str) -> bool:
    """Check whether a chunk is relevant for requirements discovery.

    Args:
        text (str): Chunk text.

    Returns:
        bool: True if the chunk looks relevant.
    """
    lower_text = text.lower()
    return any(keyword in lower_text for keyword in RELEVANT_KEYWORDS)


def _normalize_requirement_line(line: str) -> str:
    """Normalize one requirement line for deduplication.

    Args:
        line (str): Raw requirement line.

    Returns:
        str: Normalized requirement line.
    """
    normalized = line.strip()
    normalized = re.sub(r"^[\-\*\•\d\.\)\(]+\s*", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" :;-").strip()


def _parse_requirements_response(response: str) -> List[str]:
    """Parse the LLM response into a list of requirement lines.

    Args:
        response (str): Raw response from the model.

    Returns:
        List[str]: Parsed requirement lines.
    """
    if not response.strip():
        return []

    raw_lines = response.splitlines()
    parsed: List[str] = []

    invalid_starts = (
        "segue",
        "não encontrei",
        "nenhum",
        "não há",
        "foram encontrados",
        "requisitos identificados",
        "aqui estão",
    )

    for raw_line in raw_lines:
        line = _normalize_requirement_line(raw_line)

        if not line:
            continue

        if len(line) < 4:
            continue

        if line.lower().startswith(invalid_starts):
            continue

        parsed.append(line)

    return parsed


def _deduplicate_requirements(requirements: List[str]) -> List[str]:
    """Deduplicate requirements preserving order.

    Args:
        requirements (List[str]): Raw requirements.

    Returns:
        List[str]: Deduplicated requirements.
    """
    seen: Set[str] = set()
    unique: List[str] = []

    for requirement in requirements:
        normalized = _normalize_requirement_line(requirement).lower()
        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        unique.append(_normalize_requirement_line(requirement))

    return unique


def _extract_with_ollama(client: OllamaClient, prompt: str) -> List[str]:
    """Run one extraction prompt against Ollama.

    Args:
        client (OllamaClient): Ollama client instance.
        prompt (str): Prompt to send.

    Returns:
        List[str]: Extracted requirement lines.
    """
    response = client.generate(prompt)
    logger.info("Ollama raw response (first 800 chars): %s", response[:800])
    return _parse_requirements_response(response)


def extract_requirements(text: str) -> str:
    """Extract requirements from the document using a hybrid approach.

    Args:
        text (str): Full extracted text from the document.

    Returns:
        str: Requirements listed one per line.
    """
    logger.info("=" * 60)
    logger.info("EXTRAÇÃO HÍBRIDA DE REQUISITOS")
    logger.info("=" * 60)

    if not text or not text.strip():
        logger.warning("Texto vazio. Extração de requisitos ignorada.")
        return ""

    try:
        normalized_text = _normalize_text(text)
        cleaned_text = _remove_noise_lines(normalized_text)

        logger.info("Texto completo limpo: %d caracteres.", len(cleaned_text))

        main_section = _extract_main_requirements_section(cleaned_text)
        client = OllamaClient()

        base_requirements: List[str] = []

        if main_section:
            logger.info(
                "Extraindo requisitos da seção principal (%d caracteres).",
                len(main_section),
            )
            base_prompt = BASE_REQUIREMENTS_PROMPT.format(text=main_section[:10000])
            base_requirements = _extract_with_ollama(client, base_prompt)
            logger.info(
                "Requisitos encontrados na seção principal: %d.",
                len(base_requirements),
            )
        else:
            logger.warning(
                "Seção principal não encontrada. Pulando etapa base com Ollama."
            )

        all_chunks = _split_text_into_chunks(cleaned_text)
        candidate_chunks = [chunk for chunk in all_chunks if _is_relevant_chunk(chunk)]

        logger.info(
            "Chunks totais: %d | Chunks candidatos para varredura adicional: %d.",
            len(all_chunks),
            len(candidate_chunks),
        )

        additional_requirements: List[str] = []
        known_requirements = _deduplicate_requirements(base_requirements)

        for index, chunk in enumerate(candidate_chunks[:8], 1):
            logger.info(
                "Varrendo chunk adicional %d/%d (%d caracteres).",
                index,
                min(len(candidate_chunks), 8),
                len(chunk),
            )

            prompt = ADDITIONAL_REQUIREMENTS_PROMPT.format(
                known_requirements="\n".join(known_requirements) or "Nenhum ainda.",
                text=chunk[:5000],
            )

            found = _extract_with_ollama(client, prompt)

            if len(found) == 1 and found[0].strip().upper() == "NENHUM":
                continue

            if found:
                logger.info(
                    "Chunk %d trouxe %d requisito(s) adicional(is).",
                    index,
                    len(found),
                )
                additional_requirements.extend(found)
                known_requirements = _deduplicate_requirements(
                    known_requirements + found
                )

        final_requirements = _deduplicate_requirements(
            base_requirements + additional_requirements
        )

        if not final_requirements:
            logger.warning("Nenhum requisito identificado pelo processo híbrido.")
            return ""

        logger.info("Total final de requisitos únicos: %d.", len(final_requirements))

        for index, requirement in enumerate(final_requirements[:15], 1):
            logger.info("  %d. %s", index, requirement[:140])

        if len(final_requirements) > 15:
            logger.info(
                "  ... e mais %d requisitos.",
                len(final_requirements) - 15,
            )

        return "\n".join(final_requirements)

    except Exception as exc:
        logger.exception("Erro inesperado na extração de requisitos: %s", exc)
        return ""