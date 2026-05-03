# LicitAI — Análise de Documentos de Licitações com IA Local

Sistema Django para upload, extração automática de metadados e análise de risco de direcionamento em licitações públicas, usando IA local via Ollama.

## Estrutura do Projeto

```
licitai/
├── manage.py
├── requirements.txt
├── licitai/
│   ├── __init__.py
│   ├── settings.py          # Configurações (inclui OLLAMA_MODEL)
│   ├── urls.py
│   └── wsgi.py
├── documents/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py             # Document + RiskAnalysis
│   ├── forms.py              # Apenas upload de arquivo
│   ├── views.py              # Upload + Detail
│   ├── urls.py
│   ├── admin.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ollama_client.py  # Cliente isolado para Ollama
│   │   ├── text_extractor.py # Extração de texto (PDF/TXT/DOCX)
│   │   ├── metadata_extractor.py # Extração de metadados via IA
│   │   └── risk_analyzer.py  # Análise de direcionamento via IA
│   ├── templates/documents/
│   │   ├── base.html
│   │   ├── upload.html
│   │   └── detail.html
│   └── templatetags/
│       ├── __init__.py
│       └── document_tags.py
└── media/                    # Arquivos enviados (gerado automaticamente)
```

## Como Rodar

### 1. Pré-requisitos
- Python 3.10+
- Ollama instalado e rodando ([ollama.com](https://ollama.com))

### 2. Instalar o modelo no Ollama
```bash
ollama pull llama3.1:8b
```

### 3. Iniciar o Ollama
```bash
ollama serve
```

### 4. Configurar o projeto
```bash
cd licitai
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser  # opcional, para acessar /admin/
```

### 5. Rodar o servidor
```bash
python manage.py runserver
```

Acesse: http://127.0.0.1:8000

## Como Testar

1. Acesse http://127.0.0.1:8000
2. Faça upload de um edital de licitação (PDF ou TXT)
3. Aguarde o processamento (pode demorar ~30-60s dependendo do modelo)
4. Veja os metadados extraídos e a análise de risco

## Trocar o Modelo de IA

**Arquivo:** `licitai/settings.py`, linha final:

```python
OLLAMA_MODEL = "llama3.1:8b"  # <-- ALTERE AQUI
```

Basta trocar para qualquer modelo instalado no Ollama, por exemplo:
- `"mistral:7b"`
- `"gemma2:9b"`
- `"qwen2:7b"`
- `"llama3.1:70b"`

## Melhorias Futuras (não implementadas)

- OCR para PDFs escaneados (Tesseract)
- Fila assíncrona (Celery) para processamento em background
- Histórico de versões de análise
- Dashboard com estatísticas agregadas
- Fine-tuning do modelo com feedback de especialistas
- API REST para integração com outros sistemas
- Autenticação e controle de acesso
- Docker para facilitar deploy
