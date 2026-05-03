import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .services.risk_analyzer import (
    _split_analysis_sections,
    _try_extract_result,
    analyze_risk,
)


SUV_REQUIREMENTS = """Locação de veículo de passeio, tipo SUV, bicombustível.
Cor preta, cinza ou chumbo.
Motor com potência mínima de 175CV e 2.0L.
Transmissão automática de 10 velocidades.
airbags.
Freios ABS.
Sistema de alerta de mudança de faixa.
Direção hidráulica ou elétrica.
Capacidade para 5 passageiros.
Injeção eletrônica.
portas.
Ar-condicionado.
Travas e vidros elétricos.
Central multimídia com conectividade Bluetooth via CarPlay (Apple) e Android Auto.
Auto falantes.
Película antifurto com proteção UV.
Transmissão luminosa mínima permitida pela legislação vigente (no mínimo 75% de transparência).
Rodas de liga leve 18".
Faróis em LED.
Retrovisores externos eletro-retráteis.
Coberto por seguro total, registrado e emplacado.
Sem condutor e sem combustível.
Franquia mínima de 5.000 km (cinco mil quilômetros) por mês.
Sem cobrança adicional de taxa por quilometragem dentro deste limite.
Modelo de referência: Toyota Corolla Cross XRE."""


NOTEBOOK_REQUIREMENTS = """Aquisição de notebooks corporativos.
Processador Intel Core i7 de 12ª geração ou superior.
Memória RAM mínima de 32GB DDR5.
SSD NVMe de 1TB.
Tela IPS de 14 polegadas.
Garantia on-site de 60 meses.
Prazo máximo de entrega de 10 dias corridos.
Marca de referência: Dell Latitude 5440."""


LOW_RISK_REQUIREMENTS = """Prestação de serviço de limpeza predial.
Equipe mínima compatível com a metragem do imóvel.
Fornecimento de EPIs.
Cumprimento das normas de segurança do trabalho.
Disponibilização de supervisor responsável pelo contrato."""

MIXED_TEXT = """O objeto da presente licitação é a locação de veículo SUV.
Motor com potência mínima de 175CV e 2.0L.
Transmissão automática de 10 velocidades.
Modelo de referência: Toyota Corolla Cross XRE.
O procedimento seguirá de acordo com o modo de disputa adotado.
Durante o transcurso da sessão pública, o licitante será informado do menor lance registrado."""


class RiskAnalyzerParsingTests(SimpleTestCase):
    def test_split_analysis_sections_prioritizes_object_lines(self):
        sections = _split_analysis_sections(MIXED_TEXT)

        self.assertIn("Motor com potência mínima de 175CV e 2.0L.", sections["primary_text"])
        self.assertIn("Modelo de referência: Toyota Corolla Cross XRE.", sections["primary_text"])
        self.assertNotIn("modo de disputa", sections["primary_text"].lower())
        self.assertIn("modo de disputa", sections["secondary_text"].lower())

    def test_rejects_placeholder_justification_without_details(self):
        raw = """
        {
          "risk_classification": "medio",
          "risk_score": 45,
          "justification": "Análise detalhada de cada requisito restritivo encontrado",
          "warning_signs": []
        }
        """

        result = _try_extract_result(raw, "teste", SUV_REQUIREMENTS)

        self.assertIsNone(result)

    def test_rebuilds_justification_from_grounded_warning_signs(self):
        raw = """
        {
          "risk_classification": "alto",
          "risk_score": 82,
          "justification": "Análise detalhada de cada requisito restritivo encontrado",
          "warning_signs": [
            "\\"Motor com potência mínima de 175CV e 2.0L\\": potência e cilindrada mínimas podem restringir o universo de veículos compatíveis.",
            "\\"Modelo de referência: Toyota Corolla Cross XRE\\": referência explícita pode apontar para direcionamento do conjunto das especificações."
          ]
        }
        """

        result = _try_extract_result(raw, "teste", SUV_REQUIREMENTS)

        self.assertIsNotNone(result)
        self.assertIn("motor com potência mínima de 175cv e 2.0l".lower(), result["justification"].lower())
        self.assertIn("modelo de referência: toyota corolla cross xre".lower(), result["justification"].lower())

    def test_builds_requirement_focused_justification_from_reviews(self):
        raw = """
        {
          "risk_classification": "alto",
          "risk_score": 84,
          "justification": "Resumo genérico",
          "warning_signs": [],
          "reviewed_requirements": [
            {
              "id": "R2",
              "requirement": "Motor com potência mínima de 175CV e 2.0L.",
              "assessment": "restritivo_isolado",
              "reason": "a potência e a cilindrada mínimas podem reduzir o universo de veículos compatíveis"
            },
            {
              "id": "R3",
              "requirement": "Transmissão automática de 10 velocidades.",
              "assessment": "restritivo_por_combinacao",
              "reason": "o número exato de marchas estreita ainda mais a comparação entre modelos"
            },
            {
              "id": "R4",
              "requirement": "Modelo de referência: Toyota Corolla Cross XRE.",
              "assessment": "restritivo_por_combinacao",
              "reason": "a referência explícita reforça o apontamento para um conjunto reduzido de soluções"
            }
          ]
        }
        """

        result = _try_extract_result(raw, "teste", SUV_REQUIREMENTS)

        self.assertIsNotNone(result)
        self.assertIn("análise requisito a requisito", result["justification"].lower())
        self.assertIn("transmissão automática de 10 velocidades", result["justification"].lower())
        self.assertEqual(len(result["warning_signs"]), 3)

    def test_accepts_grounded_result_for_non_vehicle_case(self):
        raw = """
        {
          "risk_classification": "alto",
          "risk_score": 76,
          "justification": "Os trechos \\"Garantia on-site de 60 meses\\", \\"Prazo máximo de entrega de 10 dias corridos\\" e \\"Marca de referência: Dell Latitude 5440\\" sugerem uma combinação potencialmente restritiva, pois reúnem exigências muito específicas e um referencial de produto que pode reduzir o universo competitivo.",
          "warning_signs": [
            "\\"Garantia on-site de 60 meses\\": prazo de garantia elevado pode restringir fornecedores sem justificativa técnica explícita.",
            "\\"Prazo máximo de entrega de 10 dias corridos\\": prazo muito curto pode limitar a participação de fornecedores capazes de atender o objeto.",
            "\\"Marca de referência: Dell Latitude 5440\\": referência explícita a produto específico pode direcionar as especificações."
          ]
        }
        """

        result = _try_extract_result(raw, "teste", NOTEBOOK_REQUIREMENTS)

        self.assertIsNotNone(result)
        self.assertEqual(result["risk_classification"], "alto")
        self.assertEqual(len(result["warning_signs"]), 3)

    def test_filters_placeholder_and_ungrounded_warning_signs(self):
        raw = """
        {
          "risk_classification": "medio",
          "risk_score": 48,
          "justification": "Os trechos \\"Garantia on-site de 60 meses\\" e \\"Prazo máximo de entrega de 10 dias corridos\\" mostram exigências potencialmente desproporcionais para parte do mercado.",
          "warning_signs": [
            "requisito 1: motivo",
            "\\"Garantia on-site de 60 meses\\": prazo de garantia elevado pode restringir fornecedores.",
            "\\"Motor com potência mínima de 175CV e 2.0L\\": exigência fora do escopo deste edital."
          ]
        }
        """

        result = _try_extract_result(raw, "teste", NOTEBOOK_REQUIREMENTS)

        self.assertIsNotNone(result)
        self.assertEqual(
            result["warning_signs"],
            ['"Garantia on-site de 60 meses": prazo de garantia elevado pode restringir fornecedores.'],
        )

    def test_rejects_off_topic_result_without_grounding(self):
        raw = """
        {
          "risk_classification": "baixo",
          "risk_score": 18,
          "justification": "Foram avaliados os requisitos Credenciamento, Documentação, Declaração de Conhecimento do Teor do Ato Convocatório, Proposta Econômica e Habilitação Legal. Concluímos que esses requisitos são necessários para garantir a transparência e igualdade entre os participantes.",
          "warning_signs": [
            "Motor mínimo elevado: exigência possivelmente desproporcional para o uso descrito",
            "Modelo de referência específico: pode restringir a competição a poucos fornecedores"
          ]
        }
        """

        result = _try_extract_result(raw, "teste", SUV_REQUIREMENTS)

        self.assertIsNone(result)

    def test_accepts_grounded_low_risk_result_without_warning_signs(self):
        raw = """
        {
          "risk_classification": "baixo",
          "risk_score": 18,
          "justification": "Os trechos \\"Fornecimento de EPIs\\" e \\"Cumprimento das normas de segurança do trabalho\\" apontam exigências usuais e proporcionais para a execução do serviço, sem detalhamento excessivo ou combinação que indique restrição indevida à competitividade.",
          "warning_signs": []
        }
        """

        result = _try_extract_result(raw, "teste", LOW_RISK_REQUIREMENTS)

        self.assertIsNotNone(result)
        self.assertEqual(result["risk_classification"], "baixo")

    @patch("documents.services.risk_analyzer.OllamaClient.generate")
    def test_analyze_risk_uses_primary_object_text_first(self, mock_generate):
        mock_generate.return_value = json.dumps(
            {
                "risk_classification": "alto",
                "risk_score": 85,
                "justification": (
                    'Os trechos "Motor com potência mínima de 175CV e 2.0L.", '
                    '"Transmissão automática de 10 velocidades." e '
                    '"Modelo de referência: Toyota Corolla Cross XRE." sugerem '
                    "combinação excessivamente específica para o objeto licitado."
                ),
                "warning_signs": [
                    '"Motor com potência mínima de 175CV e 2.0L.": potência e cilindrada mínimas podem restringir o mercado.',
                    '"Transmissão automática de 10 velocidades.": especificação muito específica para o objeto.',
                    '"Modelo de referência: Toyota Corolla Cross XRE.": referência explícita pode direcionar o certame.',
                ],
            }
        )

        result = analyze_risk(MIXED_TEXT)

        self.assertEqual(result["risk_classification"], "alto")
        self.assertEqual(mock_generate.call_count, 1)

        first_prompt = mock_generate.call_args_list[0].args[0]
        self.assertIn("[R1]", first_prompt)
        self.assertIn("Analise CADA requisito listado como [R#] individualmente", first_prompt)
        self.assertIn("Motor com potência mínima de 175CV e 2.0L.", first_prompt)
        self.assertIn("Modelo de referência: Toyota Corolla Cross XRE.", first_prompt)
        self.assertNotIn("modo de disputa adotado", first_prompt.lower())

    @patch("documents.services.risk_analyzer.OllamaClient.generate")
    def test_analyze_risk_checks_secondary_only_when_primary_is_clean(self, mock_generate):
        mock_generate.side_effect = [
            json.dumps(
                {
                    "risk_classification": "baixo",
                    "risk_score": 12,
                    "justification": (
                        'Os trechos "O objeto da presente licitação é a locação de veículo SUV." '
                        'e "Motor com potência mínima de 175CV e 2.0L." não bastam, por si só, '
                        "para indicar restrição indevida neste recorte."
                    ),
                    "warning_signs": [],
                }
            ),
            json.dumps(
                {
                    "risk_classification": "medio",
                    "risk_score": 44,
                    "justification": (
                        'O trecho "O procedimento seguirá de acordo com o modo de disputa adotado." '
                        'isoladamente não é suficiente, mas "Durante o transcurso da sessão pública, '
                        'o licitante será informado do menor lance registrado." pode demandar revisão '
                        "quanto à forma de condução da disputa."
                    ),
                    "warning_signs": [
                        '"Durante o transcurso da sessão pública, o licitante será informado do menor lance registrado.": a cláusula merece revisão para verificar se a dinâmica competitiva está adequadamente disciplinada.'
                    ],
                }
            ),
        ]

        result = analyze_risk(MIXED_TEXT)

        self.assertEqual(result["risk_classification"], "medio")
        self.assertEqual(mock_generate.call_count, 2)
        first_prompt = mock_generate.call_args_list[0].args[0]
        second_prompt = mock_generate.call_args_list[1].args[0]
        self.assertNotIn("modo de disputa adotado", first_prompt.lower())
        self.assertIn("modo de disputa adotado", second_prompt.lower())
