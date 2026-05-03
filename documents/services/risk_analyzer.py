"""Service for analyzing bidding direction risk using local AI."""
import json
import logging
import re
import time

from .ollama_client import OllamaClient

logger = logging.getLogger("documents.risk_analyzer")


ANALYSIS_PROMPT = """Você é um analista técnico de licitações públicas brasileiras.

Você receberá apenas um trecho de requisitos, especificações ou condições relevantes de um edital. Sua análise deve ser 100% ancorada no texto fornecido.

{focus_instruction}

OBJETIVO:
- Identificar exigências ou combinações de exigências que possam indicar direcionamento, restrição indevida à competitividade ou desproporcionalidade.
- Diferenciar requisitos usuais/necessários de requisitos excessivamente específicos.
- Explicar por que cada sinal de alerta realmente aumenta o risco.

MÉTODO OBRIGATÓRIO:
- Analise CADA requisito listado como [R#] individualmente antes de concluir.
- Identifique quais requisitos são usuais, quais são sensíveis e quais são potencialmente restritivos.
- Depois avalie o efeito da COMBINAÇÃO dos requisitos, e não apenas de cada item isolado.
- A justificativa final deve deixar claro quais requisitos foram decisivos para a conclusão.

REGRAS DE ANCORAGEM:
- Analise SOMENTE o texto fornecido.
- NÃO mencione itens que não estejam no texto.
- Se o texto fornecido tratar apenas de requisitos técnicos, NÃO fale de credenciamento, documentação, habilitação, proposta, fases do certame ou outros temas procedimentais.
- Em "justification", cite entre aspas duplas trechos EXATOS do texto analisado.
- Se o risco for "medio" ou "alto", a "justification" deve citar pelo menos 2 trechos exatos.
- Se o risco for "baixo", a "justification" deve citar pelo menos 1 trecho exato.
- Cada item de "warning_signs" deve começar com um trecho EXATO do texto, de preferência entre aspas duplas, seguido de ": " e depois a explicação.
- Se não houver sinais concretos, retorne "warning_signs": [].
- NÃO use frases vagas como "Análise detalhada..." ou "texto da análise aqui".
- NÃO use placeholders como "requisito 1: motivo", "requisito 2: motivo" ou "alerta 1".

O QUE PODE SER SINAL DE ALERTA:
- marca, modelo ou referência específica
- combinação de requisitos que estreita demais o mercado
- números exatos, faixas estreitas ou detalhamento excessivo sem justificativa aparente
- exigências estéticas, cosméticas ou de conforto sem relação clara com a finalidade
- certificações, prazos, garantias, quantitativos ou condições possivelmente desproporcionais
- exigências que parecem apontar para poucos fornecedores ou poucos produtos

O QUE NÃO É SINAL AUTOMÁTICO:
- item padrão de segurança
- requisito comum para a categoria do objeto
- especificação mínima usual e proporcional ao uso descrito

PONTUAÇÃO:
- 0-30 = baixo
- 31-60 = medio
- 61-100 = alto

Responda EXCLUSIVAMENTE com este JSON:

{{"risk_classification": "medio", "risk_score": 58, "justification": "Na análise requisito a requisito, \\"trecho exato 1\\" foi considerado sensível porque ... e \\"trecho exato 2\\" foi considerado potencialmente restritivo porque .... Em conjunto com \\"trecho exato 3\\", essas exigências podem reduzir a competitividade.", "warning_signs": ["\\"trecho exato 1\\": explique por que isso é restritivo", "\\"trecho exato 2\\": explique por que isso reduz a competitividade"], "reviewed_requirements": [{{"id": "R1", "requirement": "trecho exato 1", "assessment": "restritivo_isolado", "reason": "explicação objetiva"}}, {{"id": "R2", "requirement": "trecho exato 2", "assessment": "restritivo_por_combinacao", "reason": "explicação objetiva"}}]}}

{context_section}

TEXTO ANALISADO:
{text}"""


RETRY_PROMPT = """Você recebeu uma resposta de análise de licitação que falhou em pelo menos um destes pontos:
- ficou genérica
- falou de temas que não aparecem no texto
- não citou trechos exatos do edital
- trouxe sinais de alerta sem aderência ao texto

Gere uma NOVA resposta do zero, sem reaproveitar trechos genéricos da resposta anterior.

{focus_instruction}

REGRAS OBRIGATÓRIAS:
- Analise SOMENTE o texto fornecido abaixo.
- NÃO mencione qualquer assunto que não apareça no texto.
- Revise os itens [R#] um a um antes de concluir.
- Em "justification", cite entre aspas duplas trechos EXATOS do texto analisado.
- Se o risco for "medio" ou "alto", cite pelo menos 2 trechos exatos na "justification".
- Se o risco for "baixo", cite pelo menos 1 trecho exato na "justification".
- Cada item de "warning_signs" deve começar com um trecho EXATO do texto, seguido de ": " e da explicação.
- Se não houver sinais concretos, use "warning_signs": [].
- NÃO use placeholders, frases vagas ou explicações fora do escopo do texto.
- Se possível, inclua "reviewed_requirements" com a avaliação requisito a requisito.

JSON OBRIGATÓRIO:
{{"risk_classification": "baixo", "risk_score": 15, "justification": "Explique a análise citando \\"trechos exatos\\" do texto.", "warning_signs": ["\\"trecho exato\\": motivo concreto do alerta"], "reviewed_requirements": [{{"id": "R1", "requirement": "trecho exato", "assessment": "usual", "reason": "motivo"}}]}}

{context_section}

TEXTO ANALISADO:
{text}

RESPOSTA ANTERIOR:
{raw}"""


MINIMAL_PROMPT = """Analise SOMENTE o texto abaixo e responda APENAS com JSON válido.

{focus_instruction}

Regras:
- Não invente itens.
- Revise os itens [R#] um a um.
- Em "justification", cite entre aspas duplas trechos EXATOS do texto.
- Se o risco for "medio" ou "alto", cite pelo menos 2 trechos exatos.
- Cada item de "warning_signs" deve começar com um trecho EXATO do texto, seguido de ": ".
- Se não houver sinais concretos, retorne [].

Formato:
{{"risk_classification": "baixo ou medio ou alto", "risk_score": 0, "justification": "Análise citando \\"trechos exatos\\"", "warning_signs": ["\\"trecho exato\\": motivo"], "reviewed_requirements": [{{"id": "R1", "requirement": "trecho exato", "assessment": "usual", "reason": "motivo"}}]}}

{context_section}

TEXTO:
{text}"""


PRIMARY_FOCUS_INSTRUCTION = """PRIORIDADE OBRIGATÓRIA:
- O texto abaixo foi selecionado para representar principalmente o OBJETO, as especificações, os quantitativos, os prazos, as garantias e as condições diretamente ligadas ao objeto licitado.
- Sua análise deve focar primeiro no que pode restringir o próprio objeto.
- NÃO desvie para questões procedimentais ou fases do certame que não estejam no texto abaixo."""

SECONDARY_FOCUS_INSTRUCTION = """PRIORIDADE OBRIGATÓRIA:
- O texto abaixo reúne cláusulas complementares ou procedimentais.
- Analise este trecho somente porque a revisão focada no objeto não encontrou sinais concretos suficientes.
- Só aponte alerta aqui se a própria cláusula abaixo, por si só, parecer restritiva ou desproporcional."""

GENERAL_FOCUS_INSTRUCTION = """PRIORIDADE OBRIGATÓRIA:
- Se o texto misturar regras do objeto e regras procedimentais, priorize sempre o que restringe o objeto.
- Só trate de cláusulas procedimentais se o próprio texto não trouxer sinais relevantes ligados ao objeto licitado."""

OBJECT_KEYWORDS = (
    "objeto",
    "especifica",
    "requisito",
    "item",
    "lote",
    "quantidade",
    "quantitativo",
    "unidade",
    "prazo de entrega",
    "prazo de execução",
    "prazo de execucao",
    "garantia",
    "assistência técnica",
    "assistencia tecnica",
    "suporte",
    "desempenho",
    "capacidade",
    "potência",
    "potencia",
    "motor",
    "cilindrada",
    "transmissão",
    "transmissao",
    "memória",
    "memoria",
    "processador",
    "ssd",
    "armazenamento",
    "tela",
    "material",
    "dimensão",
    "dimensao",
    "medida",
    "marca",
    "modelo",
    "fabricante",
    "execução",
    "execucao",
    "instalação",
    "instalacao",
    "fornecimento",
    "serviço",
    "servico",
    "locação",
    "locacao",
    "veículo",
    "veiculo",
    "equipamento",
    "software",
    "licença",
    "licenca",
    "cor",
)

PROCEDURAL_KEYWORDS = (
    "licitante",
    "sessão pública",
    "sessao publica",
    "modo de disputa",
    "lance",
    "habilitação",
    "habilitacao",
    "credenciamento",
    "proposta",
    "recurso",
    "julgamento",
    "pregoeiro",
    "comissão",
    "comissao",
    "documentação",
    "documentacao",
    "certame",
    "adjudicação",
    "adjudicacao",
    "homologação",
    "homologacao",
    "envelope",
    "sessão",
    "sessao",
)

GENERIC_JUSTIFICATIONS = {
    "análise detalhada de cada requisito restritivo encontrado",
    "analise detalhada de cada requisito restritivo encontrado",
    "texto da analise aqui",
    "texto da análise aqui",
    "sua analise aqui",
    "sua análise aqui",
}

GENERIC_WARNING_SIGN_PATTERNS = (
    r"^requisito\s*\d+\s*:\s*motivo$",
    r"^alerta\s*\d+$",
    r"^alerta\s*\d+\s*:\s*motivo$",
    r"^item\s*\d+\s*:\s*motivo$",
)

RESTRICTIVE_ASSESSMENTS = {
    "sensivel",
    "restritivo_isolado",
    "restritivo_por_combinacao",
}


def analyze_risk(text: str, context: str = "") -> dict:
    """Analyze a document for bidding direction risk indicators."""
    logger.info("=" * 60)
    logger.info("ETAPA 2: ANÁLISE DE RISCO DE DIRECIONAMENTO")
    logger.info("=" * 60)

    if not text or not text.strip():
        logger.warning("Texto vazio — análise de risco ignorada.")
        return _empty_result("Documento sem conteúdo textual para análise.")

    source_text = text.strip()
    logger.info("Texto recebido para análise: %d caracteres", len(source_text))

    if context and context.strip():
        context_section = (
            "CONTEXTO PESQUISADO NA WEB (use apenas para avaliar proporcionalidade e necessidade):\n"
            "---\n"
            f"{context.strip()[:3000]}\n"
            "---"
        )
        logger.info("Contexto RAG injetado: %d caracteres", len(context))
    else:
        context_section = ""
        logger.info("Sem contexto RAG.")

    sections = _split_analysis_sections(source_text)
    logger.info(
        "Linhas classificadas para análise: principal=%d | secundário=%d",
        sections["primary_count"],
        sections["secondary_count"],
    )

    client = OllamaClient()
    best_raw = ""

    if sections["primary_text"]:
        logger.info("Iniciando análise priorizando requisitos do objeto.")
        primary_result, primary_raw = _run_analysis_stage(
            client=client,
            analyzed_text=sections["primary_text"],
            context_section=context_section,
            focus_instruction=PRIMARY_FOCUS_INSTRUCTION,
            stage_name="Análise principal do objeto",
        )
        best_raw = primary_raw or best_raw

        if primary_result and _has_concrete_findings(primary_result):
            _log_result(primary_result)
            return primary_result

        if sections["secondary_text"]:
            logger.info("Análise principal sem alertas concretos. Revisando cláusulas secundárias.")
            secondary_result, secondary_raw = _run_analysis_stage(
                client=client,
                analyzed_text=sections["secondary_text"],
                context_section=context_section,
                focus_instruction=SECONDARY_FOCUS_INSTRUCTION,
                stage_name="Análise secundária de cláusulas complementares",
            )
            best_raw = secondary_raw or best_raw

            if secondary_result and _has_concrete_findings(secondary_result):
                _log_result(secondary_result)
                return secondary_result

        if primary_result:
            _log_result(primary_result)
            return primary_result
    else:
        logger.info("Sem separação clara de requisitos do objeto. Usando análise geral.")
        general_result, general_raw = _run_analysis_stage(
            client=client,
            analyzed_text=source_text,
            context_section=context_section,
            focus_instruction=GENERAL_FOCUS_INSTRUCTION,
            stage_name="Análise geral",
        )
        best_raw = general_raw or best_raw

        if general_result:
            _log_result(general_result)
            return general_result

    logger.warning("Todas as tentativas falharam. Usando resposta bruta como fallback.")
    fallback = _build_fallback(best_raw)
    _log_result(fallback)
    return fallback


def _run_analysis_stage(
    client,
    analyzed_text: str,
    context_section: str,
    focus_instruction: str,
    stage_name: str,
) -> tuple[dict | None, str]:
    """Run one analysis stage with retries and grounding validation."""
    prepared_text = _prepare_requirement_review_text(analyzed_text)

    raw_response = _call_ollama(
        client,
        ANALYSIS_PROMPT.format(
            text=prepared_text,
            context_section=context_section,
            focus_instruction=focus_instruction,
        ),
        f"{stage_name} - Tentativa 1",
    )
    result = _try_extract_result(raw_response, f"{stage_name} - Tentativa 1", analyzed_text)
    if result:
        return result, raw_response

    retry_response = ""
    if raw_response and raw_response.strip():
        logger.info("-" * 40)
        logger.info("%s: pedindo nova resposta ancorada no texto...", stage_name)
        retry_response = _call_ollama(
            client,
            RETRY_PROMPT.format(
                text=prepared_text,
                context_section=context_section,
                raw=raw_response[:3000],
                focus_instruction=focus_instruction,
            ),
            f"{stage_name} - Tentativa 2",
        )
        result = _try_extract_result(retry_response, f"{stage_name} - Tentativa 2", analyzed_text)
        if result:
            return result, retry_response

    logger.info("-" * 40)
    logger.info("%s: prompt mínimo ancorado...", stage_name)
    minimal_response = _call_ollama(
        client,
        MINIMAL_PROMPT.format(
            text=prepared_text[:8000],
            context_section=context_section,
            focus_instruction=focus_instruction,
        ),
        f"{stage_name} - Tentativa 3",
    )
    result = _try_extract_result(minimal_response, f"{stage_name} - Tentativa 3", analyzed_text)
    if result:
        return result, minimal_response

    return None, raw_response or retry_response or minimal_response


def _call_ollama(client, prompt: str, label: str) -> str:
    """Call Ollama and return raw response, handling errors gracefully."""
    try:
        logger.info("[%s] Enviando prompt (%d caracteres)...", label, len(prompt))
        start = time.time()
        response = client.generate(prompt)
        elapsed = time.time() - start
        logger.info("[%s] Resposta em %.1fs (%d caracteres)", label, elapsed, len(response))
        logger.debug("[%s] Resposta bruta:\n%s", label, response[:1000])
        return response
    except (ConnectionError, RuntimeError) as exc:
        logger.error("[%s] ERRO de conexão: %s", label, exc)
        raise
    except Exception as exc:
        logger.error("[%s] ERRO inesperado: %s", label, exc)
        raise


def _split_analysis_sections(text: str) -> dict:
    """Split source text into primary object requirements and secondary clauses."""
    primary_lines = []
    secondary_lines = []

    for line in _extract_analysis_lines(text):
        if _is_primary_object_line(line):
            primary_lines.append(line)
        else:
            secondary_lines.append(line)

    return {
        "primary_text": "\n".join(primary_lines).strip(),
        "secondary_text": "\n".join(secondary_lines).strip(),
        "primary_count": len(primary_lines),
        "secondary_count": len(secondary_lines),
    }


def _extract_analysis_lines(text: str) -> list[str]:
    """Split the analyzed text into clean lines."""
    lines = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*\u2022\d\.\)\(]+\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def _prepare_requirement_review_text(text: str) -> str:
    """Render the analysis text as enumerated requirements for line-by-line review."""
    lines = _extract_analysis_lines(text)
    if not lines:
        return text.strip()

    return "\n".join(f"[R{index}] {line}" for index, line in enumerate(lines, 1))


def _is_primary_object_line(line: str) -> bool:
    """Detect whether a line is primarily about the object or its requirements."""
    normalized = _normalize_text(line)

    if any(keyword in normalized for keyword in PROCEDURAL_KEYWORDS):
        return False

    if any(keyword in normalized for keyword in OBJECT_KEYWORDS):
        return True

    word_count = len(normalized.split())
    return 1 <= word_count <= 18 and len(normalized) <= 140


def _has_concrete_findings(result: dict) -> bool:
    """Check whether the result contains concrete alert findings."""
    return bool(result.get("warning_signs")) or result.get("risk_score", 0) > 30


def _try_extract_result(raw: str, label: str, source_text: str = "") -> dict | None:
    """Try to parse raw response into a valid result dict."""
    if not raw or not raw.strip():
        logger.warning("[%s] Resposta vazia.", label)
        return None

    parsed = _parse_json(raw)
    if not parsed:
        logger.warning("[%s] Não foi possível extrair JSON da resposta.", label)
        return None

    has_classification = "risk_classification" in parsed
    has_score = "risk_score" in parsed
    has_justification = "justification" in parsed
    has_signs = "warning_signs" in parsed

    logger.info(
        "[%s] Chaves encontradas: classification=%s, score=%s, justification=%s, signs=%s",
        label,
        has_classification,
        has_score,
        has_justification,
        has_signs,
    )

    if not has_justification and not has_classification:
        logger.warning(
            "[%s] JSON não contém nenhuma chave esperada. Chaves: %s",
            label,
            list(parsed.keys()),
        )
        return None

    classification = ""
    if has_classification:
        value = str(parsed["risk_classification"]).strip().lower()
        if value in ("baixo", "medio", "médio", "alto"):
            classification = "medio" if value == "médio" else value

    score = 0
    if has_score:
        try:
            score = max(0, min(100, int(parsed["risk_score"])))
        except (TypeError, ValueError):
            pass

    if not classification:
        classification = _classify_score(score)

    requirement_reviews = _parse_requirement_reviews(
        parsed.get("reviewed_requirements"),
        source_text,
        label,
    )
    warning_signs = _parse_warning_signs(parsed.get("warning_signs"), source_text, label)

    if not warning_signs and requirement_reviews:
        warning_signs = _build_warning_signs_from_reviews(requirement_reviews)

    justification = ""
    if has_justification and isinstance(parsed["justification"], str):
        justification = parsed["justification"].strip()

    if requirement_reviews:
        rebuilt_from_reviews = _build_justification_from_reviews(
            requirement_reviews,
            classification,
            score,
        )
        if rebuilt_from_reviews:
            justification = rebuilt_from_reviews

    if _is_generic_justification(justification):
        logger.warning("[%s] Justificativa genérica detectada: %s", label, justification)
        justification = _build_justification_from_warning_signs(warning_signs, score)
        if justification:
            logger.info("[%s] Justificativa reconstruída a partir dos sinais de alerta.", label)

    if source_text and not _has_grounded_justification(
        justification,
        source_text,
        classification,
        warning_signs,
    ):
        logger.warning("[%s] Justificativa sem aderência suficiente ao texto analisado.", label)
        rebuilt = _build_justification_from_warning_signs(warning_signs, score)
        if rebuilt:
            justification = rebuilt

    if not justification or len(justification) < 20:
        logger.warning("[%s] Justificativa ausente, curta ou genérica demais.", label)
        return None

    if source_text and not _has_grounded_justification(
        justification,
        source_text,
        classification,
        warning_signs,
    ):
        logger.warning("[%s] Justificativa final continua sem grounding suficiente.", label)
        return None

    if classification in ("medio", "alto") and not warning_signs:
        logger.warning(
            "[%s] Classificação %s sem sinais de alerta concretos.",
            label,
            classification,
        )
        return None

    logger.info("[%s] Resultado válido extraído com sucesso.", label)
    return {
        "risk_classification": classification,
        "risk_score": score,
        "justification": justification,
        "warning_signs": warning_signs,
    }


def _parse_requirement_reviews(reviews_raw, source_text: str, label: str) -> list[dict]:
    """Parse optional requirement-by-requirement reviews returned by the model."""
    if not isinstance(reviews_raw, list):
        return []

    reviews = []
    for item in reviews_raw:
        if not isinstance(item, dict):
            continue

        requirement = str(item.get("requirement", "")).strip()
        assessment = _normalize_text(str(item.get("assessment", "")))
        reason = str(item.get("reason", "")).strip()
        review_id = str(item.get("id", "")).strip()

        if len(requirement) < 4 or len(reason) < 8:
            continue

        if source_text and not _is_fragment_grounded(requirement, source_text):
            logger.warning(
                "[%s] Review descartado por falta de aderência ao texto: %s",
                label,
                requirement[:180],
            )
            continue

        reviews.append(
            {
                "id": review_id,
                "requirement": requirement,
                "assessment": assessment,
                "reason": reason,
            }
        )

    return reviews


def _parse_warning_signs(signs_raw, source_text: str, label: str) -> list[str]:
    """Parse, clean and validate warning signs."""
    warning_signs = []

    if isinstance(signs_raw, list):
        warning_signs = [
            str(sign).strip()
            for sign in signs_raw
            if isinstance(sign, str) and len(str(sign).strip()) > 5
        ]
    elif isinstance(signs_raw, str) and signs_raw.strip():
        warning_signs = [signs_raw.strip()]

    warning_signs = _filter_generic_warning_signs(warning_signs, label)

    if source_text:
        warning_signs = _filter_ungrounded_warning_signs(
            warning_signs, source_text, label
        )

    return warning_signs


def _parse_json(text: str) -> dict | None:
    """Try multiple strategies to extract a JSON object from text."""
    text = text.strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if block.startswith("{"):
                try:
                    obj = json.loads(block)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        fixed = candidate.replace("'", '"')
        fixed = re.sub(r',\s*([}\]])', r"\1", fixed)
        try:
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                logger.info("JSON recuperado após correção de formatação.")
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _is_generic_justification(text: str) -> bool:
    """Identify placeholder-like justifications that do not describe the analysis."""
    normalized = _normalize_text(text)
    if len(normalized) < 10:
        return True

    if normalized in GENERIC_JUSTIFICATIONS:
        return True

    generic_patterns = (
        "explique a análise citando",
        "explique a analise citando",
        "descreva objetivamente os requisitos avaliados",
        "análise técnica do edital",
        "analise tecnica do edital",
    )
    return any(pattern in normalized for pattern in generic_patterns)


def _build_justification_from_warning_signs(warning_signs: list[str], score: int) -> str:
    """Create a readable justification from grounded warning signs."""
    if not warning_signs:
        return ""

    listed_signs = "; ".join(sign.rstrip(".") for sign in warning_signs[:4])

    if score <= 30:
        closing = (
            "Mesmo com esses pontos, o conjunto dos indícios ainda parece limitado e "
            "não eleva significativamente o risco."
        )
    elif score <= 60:
        closing = (
            "Em conjunto, esses elementos sugerem restrição relevante à competitividade "
            "e merecem revisão criteriosa."
        )
    else:
        closing = (
            "Em conjunto, esses elementos indicam forte potencial de restrição da "
            "competitividade ou direcionamento."
        )

    return (
        "A análise identificou os seguintes pontos de atenção no texto do edital: "
        f"{listed_signs}. {closing}"
    )


def _build_warning_signs_from_reviews(reviews: list[dict]) -> list[str]:
    """Build grounded warning signs from requirement-level reviews."""
    warning_signs = []

    for review in reviews:
        if review["assessment"] not in RESTRICTIVE_ASSESSMENTS:
            continue
        warning_signs.append(f'"{review["requirement"]}": {review["reason"]}')

    return warning_signs[:8]


def _build_justification_from_reviews(
    reviews: list[dict],
    classification: str,
    score: int,
) -> str:
    """Build a requirement-focused justification from line-by-line reviews."""
    restrictive_reviews = [
        review for review in reviews if review["assessment"] in RESTRICTIVE_ASSESSMENTS
    ]
    usual_reviews = [
        review for review in reviews if review["assessment"] not in RESTRICTIVE_ASSESSMENTS
    ]

    if classification in ("medio", "alto") and restrictive_reviews:
        selected = restrictive_reviews[:3]
        fragments = [
            f'"{review["requirement"]}" foi considerado problemático porque {review["reason"]}'
            for review in selected
        ]
        closing = (
            "Em conjunto, a leitura requisito a requisito indica que essas exigências "
            "podem estreitar indevidamente o mercado e aumentar o risco de direcionamento."
            if classification == "alto"
            else "Em conjunto, a leitura requisito a requisito sugere restrição relevante "
            "à competitividade e justifica revisão criteriosa do edital."
        )
        return "Na análise requisito a requisito, " + "; ".join(fragments) + f". {closing}"

    if classification == "baixo" and usual_reviews:
        selected = usual_reviews[:2]
        fragments = [
            f'"{review["requirement"]}" foi tratado como exigência usual porque {review["reason"]}'
            for review in selected
        ]
        return (
            "Na análise requisito a requisito, "
            + "; ".join(fragments)
            + ". O conjunto não mostrou combinação suficientemente específica para elevar o risco."
        )

    if restrictive_reviews:
        return _build_justification_from_warning_signs(
            _build_warning_signs_from_reviews(restrictive_reviews),
            score,
        )

    return ""


def _filter_generic_warning_signs(warning_signs: list[str], label: str) -> list[str]:
    """Discard placeholder warning signs returned by the model."""
    filtered = [
        sign for sign in warning_signs if not _is_generic_warning_sign(sign)
    ]

    removed_count = len(warning_signs) - len(filtered)
    if removed_count:
        logger.warning(
            "[%s] %d sinal(is) de alerta genérico(s) descartado(s).",
            label,
            removed_count,
        )

    return filtered


def _is_generic_warning_sign(text: str) -> bool:
    """Detect placeholder warning signs such as 'requisito 1: motivo'."""
    normalized = _normalize_text(text)
    if len(normalized) < 8:
        return True

    return any(
        re.fullmatch(pattern, normalized)
        for pattern in GENERIC_WARNING_SIGN_PATTERNS
    )


def _filter_ungrounded_warning_signs(
    warning_signs: list[str],
    source_text: str,
    label: str,
) -> list[str]:
    """Keep only warning signs that cite or reproduce text from the source."""
    filtered = []

    for sign in warning_signs:
        candidates = _extract_grounding_candidates(sign)
        if any(_is_fragment_grounded(candidate, source_text) for candidate in candidates):
            filtered.append(sign)
        else:
            logger.warning(
                "[%s] Sinal descartado por falta de aderência ao texto: %s",
                label,
                sign[:180],
            )

    return filtered


def _has_grounded_justification(
    justification: str,
    source_text: str,
    classification: str,
    warning_signs: list[str],
) -> bool:
    """Require the justification to cite concrete fragments from the source text."""
    if not justification.strip():
        return False

    required_mentions = 1 if classification == "baixo" else 2
    grounded_mentions = set()
    normalized_justification = _normalize_text(justification)

    for fragment in _extract_grounding_candidates(justification):
        if _is_fragment_grounded(fragment, source_text):
            grounded_mentions.add(_normalize_text(fragment))

    for sign in warning_signs:
        for fragment in _extract_grounding_candidates(sign):
            normalized_fragment = _normalize_text(fragment)
            if not normalized_fragment:
                continue
            if (
                normalized_fragment in normalized_justification
                and _is_fragment_grounded(fragment, source_text)
            ):
                grounded_mentions.add(normalized_fragment)

    return len(grounded_mentions) >= required_mentions


def _extract_grounding_candidates(text: str) -> list[str]:
    """Extract exact-ish fragments that can be matched against source text."""
    candidates = [fragment.strip() for fragment in re.findall(r'"([^"]+)"', text)]

    if candidates:
        return [candidate for candidate in candidates if len(candidate.strip()) >= 4]

    for separator in (":", " - ", " — ", " – "):
        if separator in text:
            prefix = text.split(separator, 1)[0].strip().strip('"')
            if len(prefix) >= 4:
                return [prefix]

    return []


def _is_fragment_grounded(fragment: str, source_text: str) -> bool:
    """Check whether a fragment appears in the analyzed source text."""
    normalized_fragment = _normalize_text(fragment)
    normalized_source = _normalize_text(source_text)

    if len(normalized_fragment) < 4:
        return False

    return normalized_fragment in normalized_source


def _classify_score(score: int) -> str:
    """Classify a numeric score into baixo/medio/alto."""
    if score <= 30:
        return "baixo"
    if score <= 60:
        return "medio"
    return "alto"


def _normalize_text(text: str) -> str:
    """Normalize free text for resilient comparisons."""
    normalized = re.sub(r"\[r\d+\]\s*", "", (text or ""), flags=re.IGNORECASE)
    normalized = normalized.replace("\r", "\n")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" .:;,-").lower()


def _build_fallback(raw_response: str) -> dict:
    """Build a fallback result using the raw AI response as justification."""
    cleaned = raw_response.strip()
    if not cleaned:
        cleaned = (
            "A IA não retornou uma análise utilizável. Recomenda-se análise manual "
            "do documento."
        )

    for char in "{}[]":
        cleaned = cleaned.replace(char, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(",").strip('"').strip()

    if len(cleaned) < 20:
        cleaned = (
            "A IA não retornou uma análise utilizável. Recomenda-se análise manual "
            "do documento."
        )

    return {
        "risk_classification": "baixo",
        "risk_score": 0,
        "justification": f"[Análise não estruturada] {cleaned[:2000]}",
        "warning_signs": [],
    }


def _empty_result(reason: str) -> dict:
    """Return a default empty result."""
    return {
        "risk_classification": "baixo",
        "risk_score": 0,
        "justification": reason,
        "warning_signs": [],
    }


def _log_result(final: dict):
    """Log the final analysis result to terminal."""
    logger.info("=" * 40)
    logger.info("RESULTADO FINAL DA ANÁLISE:")
    logger.info("  Classificação : %s", final["risk_classification"].upper())
    logger.info("  Pontuação     : %d/100", final["risk_score"])

    justification = final["justification"]
    if len(justification) > 200:
        logger.info("  Justificativa : %s...", justification[:200])
    else:
        logger.info("  Justificativa : %s", justification)

    if final["warning_signs"]:
        logger.info("  Sinais de alerta (%d):", len(final["warning_signs"]))
        for index, sign in enumerate(final["warning_signs"], 1):
            logger.info("    %d. %s", index, sign)
    else:
        logger.info("  Sinais de alerta: nenhum identificado.")
    logger.info("=" * 40)
