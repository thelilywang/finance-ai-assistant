FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 把 bge-m3 的 tokenizer vocab 預先烘進 image（約 17MB）。否則 CHUNK_UNIT=token 時
# 會在執行期打 HuggingFace，讓入庫多一個開機時才會發現的外部相依。
RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('BAAI/bge-m3')"

COPY . .

EXPOSE 8000

CMD ["chainlit", "run", "src/app.py", "--host", "0.0.0.0", "--port", "8000"]
