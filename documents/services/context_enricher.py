"""Service for enriching risk analysis with web-searched context about the procurement."""
import json
import logging
import time

from .ollama_client import OllamaClient

logger = logging.getLogger("documents.context_enricher")

QUERY_PROMPT = """Preciso pesquisar na web se uma compra pública faz sentido.

CIDADE: {city}
OBJETO DA LICITAÇÃO: {objects}

Sua tarefa: identifique O TEMA REAL por trás dessa compra e gere 3 consultas de busca que tragam DADOS CONCRETOS.

EXEMPLOS DE COMO PENSAR:
- "Coleira repelente para leishmaniose" → o tema é LEISHMANIOSE → buscar dados epidemiológicos
  Boas queries: "leishmaniose visceral Marília SP casos 2024", "leishmaniose Marília endemia", "boletim epidemiológico leishmaniose Marília"
- "Locação de veículo SUV para gabinete" → o tema é FROTA ADMINISTRATIVA → buscar necessidade
  Boas queries: "frota veículos prefeitura Marília", "locação veículo gabinete prefeito custo", "licitação SUV gabinete prefeito irregularidade"
- "Equipamento raio-X" → o tema é SAÚDE/HOSPITAL → buscar infraestrutura
  Boas queries: "hospital municipal Marília equipamentos", "raio-X saúde pública Marília", "demanda exames radiológicos Marília"

REGRAS:
- NÃO busque definições de palavras (dicionário, sinônimos)
- NÃO busque o que é o produto
- BUSQUE dados sobre o PROBLEMA que o produto resolve na CIDADE específica
- Inclua o nome da cidade nas queries
- Inclua termos como: casos, índices, dados, boletim, epidemiológico, estatística, quando pertinente

Responda APENAS com JSON:
{{"queries": ["query 1", "query 2", "query 3"]}}"""

SUMMARY_PROMPT = """Resuma objetivamente os resultados abaixo para avaliar se esta compra pública faz sentido.

CIDADE: {city}
OBJETO: {objects}

RESULTADOS:
{search_results}

Responda apenas o que os dados dizem sobre:
1. Existe demanda real para essa compra neste município? (dados, números, casos)
2. A compra é proporcional ao porte e necessidades da cidade?
3. Algum dado levanta dúvida?

Se os resultados não trouxerem dados úteis, diga isso em uma frase.
Máximo 200 palavras. Texto corrido, sem JSON."""


def enrich_context(city: str, identified_objects: str) -> str:
    """Search the web for context about the procurement and municipality."""
    logger.info("=" * 60)
    logger.info("ETAPA RAG: PESQUISA DE CONTEXTO NA WEB")
    logger.info("=" * 60)

    if not city and not identified_objects:
        logger.warning("Cidade e objeto vazios — pesquisa ignorada.")
        return ""

    logger.info("  Cidade : %s", city or "(não identificada)")
    logger.info("  Objeto : %s", identified_objects[:120] if identified_objects else "(vazio)")

    # Step 1: Generate focused search queries
    queries = _generate_queries(city, identified_objects)
    if not queries:
        logger.warning("  Não foi possível gerar queries de busca.")
        return ""

    for i, q in enumerate(queries, 1):
        logger.info("  Query %d: %s", i, q)

    # Step 2: Search the web
    all_results = []
    for query in queries:
        results = _web_search(query)
        if results:
            all_results.extend(results)

    if not all_results:
        logger.warning("  Nenhum resultado encontrado nas buscas.")
        return ""

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(r)
    all_results = unique

    logger.info("  Total de resultados únicos: %d", len(all_results))

    # Step 3: Format raw results
    raw_context = _format_results(all_results)

    # Step 4: Summarize
    summary = _summarize_results(city, identified_objects, raw_context)

    if summary and len(summary.strip()) > 30:
        final = f"RESUMO DA PESQUISA:\n{summary}\n\nFONTES CONSULTADAS:\n{raw_context}"
        logger.info("  Contexto final: %d caracteres", len(final))
        return final

    logger.info("  Usando resultados brutos (%d caracteres).", len(raw_context))
    return raw_context


def _generate_queries(city: str, objects: str) -> list:
    """Use AI to generate focused search queries, with smart fallback."""
    # First try AI
    try:
        client = OllamaClient()
        prompt = QUERY_PROMPT.format(
            city=city or "município não identificado",
            objects=objects or "objeto não identificado",
        )

        logger.info("  Gerando queries de busca via IA...")
        response = client.generate(prompt)
        parsed = _parse_json(response)

        if parsed and "queries" in parsed:
            queries = [str(q).strip() for q in parsed["queries"] if str(q).strip()]
            # Validate: reject queries that look like dictionary searches
            good = [q for q in queries if not _is_bad_query(q)]
            if good:
                # Ensure city is in at least some queries
                final = []
                for q in good[:3]:
                    if city and city.lower() not in q.lower():
                        q = f"{q} {city}"
                    final.append(q)
                return final

        logger.info("  Queries da IA descartadas, usando fallback...")
    except Exception as e:
        logger.warning("  Erro ao gerar queries via IA: %s", e)

    return _fallback_queries(city, objects)


def _is_bad_query(query: str) -> bool:
    """Check if a query is likely to return useless results."""
    bad_terms = [
        "significado", "definição", "dicionário", "sinônimo",
        "o que é", "conceito de", "wikipedia",
    ]
    q_lower = query.lower()
    return any(term in q_lower for term in bad_terms)


def _fallback_queries(city: str, objects: str) -> list:
    """Build direct search queries without AI."""
    queries = []
    obj_clean = (objects or "")[:80].strip()
    city_clean = (city or "").strip()

    if city_clean and obj_clean:
        queries.append(f"{obj_clean} {city_clean}")
        queries.append(f"{obj_clean} licitação município")
        queries.append(f"{city_clean} saúde pública dados")
    elif obj_clean:
        queries.append(f"{obj_clean} licitação pública")
    elif city_clean:
        queries.append(f"licitações {city_clean} irregularidades")

    return queries[:3]


def _web_search(query: str) -> list:
    """Search the web using DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error(
            "  duckduckgo-search não instalado! "
            "Execute: pip install duckduckgo-search"
        )
        return []

    try:
        logger.info("  Buscando: '%s'", query)
        start = time.time()

        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="br-pt", max_results=3))

        elapsed = time.time() - start
        logger.info("  %d resultados em %.1fs", len(results), elapsed)

        return [
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            }
            for r in results
        ]
    except Exception as e:
        logger.warning("  Erro na busca web: %s", e)
        return []


def _format_results(results: list) -> str:
    """Format search results into readable text."""
    lines = []
    for r in results:
        title = r.get("title", "Sem título")
        snippet = r.get("snippet", "")
        url = r.get("url", "")
        lines.append(f"- {title}\n  {snippet}\n  Fonte: {url}")
    return "\n\n".join(lines)


def _summarize_results(city: str, objects: str, raw: str) -> str:
    """Ask AI to summarize search findings."""
    try:
        client = OllamaClient()
        prompt = SUMMARY_PROMPT.format(
            city=city or "não identificada",
            objects=objects or "não identificado",
            search_results=raw[:3000],
        )

        logger.info("  Resumindo achados via IA...")
        start = time.time()
        response = client.generate(prompt)
        elapsed = time.time() - start
        logger.info("  Resumo em %.1fs (%d caracteres)", elapsed, len(response))
        return response.strip()
    except Exception as e:
        logger.warning("  Erro ao resumir: %s", e)
        return ""


def _parse_json(text: str) -> dict | None:
    """Try to extract JSON from AI response."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None
