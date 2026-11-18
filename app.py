import io
import os
import unicodedata
from collections import Counter

import tiktoken
from docx import Document
from flask import Flask, jsonify, render_template, request
from pypdf import PdfReader

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB request limit

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
MAX_VISUALIZED_TOKENS = 5000

# Load the encoding once when the app starts, not for each request.
ENCODING = tiktoken.get_encoding("cl100k_base")


def extract_text(file_storage):
    """Read an uploaded TXT, PDF or DOCX file without saving it to disk."""
    extension = os.path.splitext(file_storage.filename)[1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file format. Use TXT, PDF or DOCX.")

    data = file_storage.read()

    if extension == ".txt":
        return data.decode("utf-8", errors="replace")

    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError(
                "No text could be extracted from this PDF. It may contain scanned images."
            )
        return text

    document = Document(io.BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def make_count_result(text, filename):
    """Count the text once and prepare details for the results page."""
    token_ids = ENCODING.encode(text, disallowed_special=())
    token_text_by_id = {
        token_id: ENCODING.decode([token_id]) for token_id in set(token_ids)
    }

    # Keep whitespace-only pieces out of the counts, but preserve them in the preview.
    counted_token_ids = [
        token_id for token_id in token_ids if not token_text_by_id[token_id].isspace()
    ]
    token_counts = Counter(counted_token_ids)
    total_tokens = len(counted_token_ids)
    unique_tokens = len(token_counts)
    repetition_ratio = (unique_tokens / total_tokens * 100) if total_tokens else 0.0

    unique_words = set()
    for word in text.split():
        # Remove punctuation and normalize case before comparing words.
        normalized_word = "".join(
            character
            for character in word.casefold()
            if not unicodedata.category(character).startswith("P")
        )
        if normalized_word:
            unique_words.add(normalized_word)

    top_tokens = [
        {
            "token": token_text_by_id[token_id],
            "id": token_id,
            "count": count,
            "percent": count / total_tokens * 100 if total_tokens else 0.0,
        }
        for token_id, count in token_counts.most_common(10)
    ]
    visible_ids = token_ids[:MAX_VISUALIZED_TOKENS]

    return {
        "filename": filename,
        "characters": len(text),
        "words": len(text.split()),
        "unique_words": len(unique_words),
        "tokens": total_tokens,
        "total_tokens": total_tokens,
        "unique_tokens": unique_tokens,
        "repetition_ratio": repetition_ratio,
        "top_tokens": top_tokens,
        "token_strings": [token_text_by_id[token_id] for token_id in visible_ids],
        "truncated": len(token_ids) > MAX_VISUALIZED_TOKENS,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/count", methods=["POST"])
def count():
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify(error="No file selected."), 400

    try:
        text = extract_text(file)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        return jsonify(
            error="Could not read this file. It may be corrupted or password-protected."
        ), 400

    if not text.strip():
        return jsonify(error="The selected file is empty or contains no text."), 400

    return jsonify(make_count_result(text, file.filename))


@app.route("/count-text", methods=["POST"])
def count_text():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Send text as a JSON object."), 400

    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Enter or paste some text to count."), 400

    return jsonify(make_count_result(text, "Pasted text"))


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="The request is too large. The limit is 20 MB."), 413


if __name__ == "__main__":
    app.run(debug=True)
