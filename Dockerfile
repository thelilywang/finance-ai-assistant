# 以 digest 釘住 base image；要升級時手動改這行（docker buildx imagetools inspect python:3.11-slim）
FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# 把 bge-m3 的 tokenizer vocab 預先烘進 image（約 17MB）。否則 CHUNK_UNIT=token 時
# 會在執行期打 HuggingFace，讓入庫多一個開機時才會發現的外部相依。
RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('BAAI/bge-m3')"

COPY . .

EXPOSE 8000

CMD ["chainlit", "run", "src/app.py", "--host", "0.0.0.0", "--port", "8000"]
