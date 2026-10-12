# Smart Park no Render (ou em qualquer servidor com Docker).
# Roda o sistema completo em modo demonstração (sem ESP32), com a planta de 250 vagas,
# a leitura de placa por foto (OpenCV + Tesseract) e o modo "carro de teste" em /carro.
FROM python:3.12-slim

# Tesseract é o OCR que lê os caracteres da placa
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY raspberry/requirements-render.txt raspberry/requirements-render.txt
RUN pip install --no-cache-dir -r raspberry/requirements-render.txt

COPY . .
# Treino o preditor aqui, com a mesma versão do scikit-learn que vai rodar no servidor, e já deixo
# pronto um banco de demonstração (cadastro + 4 semanas de histórico): assim o servidor sobe em segundos.
RUN cd raspberry && python -W ignore -m simulador.treinar_preditor \
 && python scripts/cadastrar.py demo --banco smartpark/dados/demo_base.db \
 && python -W ignore scripts/gerar_historico_demo.py --layout planta --banco smartpark/dados/demo_base.db

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["bash", "raspberry/scripts/iniciar_render.sh"]
