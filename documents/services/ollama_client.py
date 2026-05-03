"""Client for communicating with the local Ollama instance."""
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger("documents.ollama")


class OllamaClient:
    """Simple client to send prompts to a local Ollama model.

    The model used is defined in settings.OLLAMA_MODEL.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT
        logger.info("OllamaClient inicializado — modelo: %s | url: %s", self.model, self.base_url)

    def generate(self, prompt: str) -> str:
        """Send a prompt to Ollama and return the response text."""
        url = f"{self.base_url}/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": False}

        logger.info("Enviando prompt ao Ollama (%d caracteres)...", len(prompt))
        logger.debug("Prompt (primeiros 300 chars): %s", prompt[:300])

        start = time.time()

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except requests.ConnectionError:
            logger.error("FALHA DE CONEXÃO: Ollama não encontrado em %s", self.base_url)
            raise ConnectionError(
                f"Não foi possível conectar ao Ollama em {self.base_url}. "
                "Verifique se o Ollama está rodando (ollama serve)."
            )
        except requests.Timeout:
            logger.error("TIMEOUT: Ollama não respondeu em %ds", self.timeout)
            raise RuntimeError(f"Timeout ao aguardar resposta do Ollama ({self.timeout}s).")
        except requests.HTTPError as e:
            logger.error("ERRO HTTP do Ollama: %s", e)
            raise RuntimeError(f"Erro na API do Ollama: {e}")

        elapsed = time.time() - start
        data = response.json()
        text = data.get("response", "")

        # Strip <think>...</think> tags (qwen3 and other models with thinking mode)
        text = _strip_thinking_tags(text)

        logger.info("Resposta recebida do Ollama em %.1fs (%d caracteres)", elapsed, len(text))
        logger.debug("Resposta (primeiros 500 chars): %s", text[:500])

        return text


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model responses."""
    # Remove complete <think>...</think> blocks (including multiline)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Remove orphan opening <think> tag (model started thinking but didn't close)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()
