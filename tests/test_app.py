import io
from pathlib import Path
from unittest.mock import patch

import pytest
import tiktoken
from docx import Document
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

from app import app


ENCODING = tiktoken.get_encoding("cl100k_base")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def make_text_pdf(text):
    """Build a minimal one-page PDF containing a short ASCII text string."""
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 20 80 Td ({escaped_text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 120] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\n"
        b"stream\n" + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return bytes(pdf)


def make_docx(text):
    document = Document()
    document.add_paragraph(text)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def upload(client, filename, contents):
    return client.post(
        "/count",
        data={"file": (io.BytesIO(contents), filename)},
        content_type="multipart/form-data",
    )


def test_txt_upload_returns_basic_counts(client):
    text = "hello world"
    response = upload(client, "notes.txt", text.encode("utf-8"))

    assert response.status_code == 200
    result = response.get_json()
    assert result["filename"] == "notes.txt"
    assert result["characters"] == len(text)
    assert result["words"] == 2
    assert result["total_tokens"] == len(ENCODING.encode(text))
    assert result["tokens"] == result["total_tokens"]


def test_empty_text_file_returns_clear_error(client):
    response = upload(client, "empty.txt", b"")

    assert response.status_code == 400
    assert "empty or contains no text" in response.get_json()["error"].lower()


def test_pdf_upload_extracts_text(client):
    response = upload(client, "notes.pdf", make_text_pdf("PDF text works"))

    assert response.status_code == 200
    result = response.get_json()
    assert result["filename"] == "notes.pdf"
    assert result["words"] == 3
    assert result["characters"] >= len("PDF text works")
    assert result["total_tokens"] > 0


def test_docx_upload_extracts_text(client):
    response = upload(client, "notes.docx", make_docx("DOCX text works"))

    assert response.status_code == 200
    result = response.get_json()
    assert result["filename"] == "notes.docx"
    assert result["words"] == 3
    assert result["characters"] >= len("DOCX text works")
    assert result["total_tokens"] > 0


def test_unsupported_file_type_returns_clear_error(client):
    response = upload(client, "photo.jpg", b"not an image")

    assert response.status_code == 400
    assert "unsupported file format" in response.get_json()["error"].lower()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"file": (io.BytesIO(b"contents"), "")},
    ],
)
def test_missing_or_empty_filename_returns_clear_error(client, data):
    response = client.post("/count", data=data, content_type="multipart/form-data")

    assert response.status_code == 400
    assert "no file selected" in response.get_json()["error"].lower()


@pytest.mark.parametrize(
    ("filename", "contents"),
    [
        ("broken.pdf", b"%PDF-1.4\nthis is not a valid PDF"),
        ("broken.docx", b"this is not a valid DOCX archive"),
    ],
)
def test_corrupt_documents_return_friendly_error(client, filename, contents):
    response = upload(client, filename, contents)

    assert response.status_code == 400
    message = response.get_json()["error"].lower()
    assert "corrupted" in message or "could not read" in message


def test_pdf_without_extractable_text_mentions_scanned_images(client):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    output = io.BytesIO()
    writer.write(output)

    response = upload(client, "scan.pdf", output.getvalue())

    assert response.status_code == 400
    assert "may contain scanned images" in response.get_json()["error"].lower()


def test_upload_over_20_mib_returns_413(client):
    contents = b"x" * (20 * 1024 * 1024 + 1)

    response = upload(client, "large.txt", contents)

    assert response.status_code == 413
    assert "20 mb" in response.get_json()["error"].lower()


def test_uploaded_file_is_not_saved_to_disk(client):
    with patch.object(
        FileStorage,
        "save",
        side_effect=AssertionError("Uploaded data must remain in memory"),
    ) as save_file:
        response = upload(client, "memory.txt", b"keep this in memory")

    assert response.status_code == 200
    save_file.assert_not_called()


def test_paste_text_returns_counts(client):
    text = "Simple pasted text"

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert result["filename"] == "Pasted text"
    assert result["characters"] == len(text)
    assert result["words"] == 3
    assert result["total_tokens"] == len(ENCODING.encode(text))


def test_empty_paste_text_returns_clear_error(client):
    response = client.post("/count-text", json={"text": " \n\t"})

    assert response.status_code == 400
    assert "enter or paste" in response.get_json()["error"].lower()


def test_long_paste_text_is_counted_and_visualizer_is_limited(client):
    text = "word " * 10_000

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert result["characters"] == len(text)
    assert result["words"] == 10_000
    assert len(result["token_strings"]) <= 5_000
    assert result["truncated"] is True


def test_counts_match_tokenizer_ids_for_text_without_space_only_tokens(client):
    text = "Hello,world!"
    token_ids = ENCODING.encode(text)

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert result["total_tokens"] == len(token_ids)
    assert result["unique_tokens"] == len(set(token_ids))


def test_whitespace_only_token_ids_are_excluded(client):
    text = "left\n\nright"
    token_ids = ENCODING.encode(text)
    counted_token_ids = [
        token_id for token_id in token_ids
        if not ENCODING.decode([token_id]).isspace()
    ]

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert len(counted_token_ids) < len(token_ids)
    assert result["total_tokens"] == len(counted_token_ids)
    assert result["unique_tokens"] == len(set(counted_token_ids))


def test_repeated_example_matches_tokenizer_id_counts(client):
    text = "the cat the cat the cat"
    token_ids = ENCODING.encode(text)
    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert result["total_tokens"] == len(token_ids) == 6
    assert result["unique_tokens"] == len(set(token_ids)) == 3


def test_repetition_ratio_is_unique_tokens_over_total(client):
    response = client.post("/count-text", json={"text": "repeat repeat repeat"})

    assert response.status_code == 200
    result = response.get_json()
    assert result["repetition_ratio"] == pytest.approx(
        result["unique_tokens"] / result["total_tokens"] * 100
    )


def test_top_tokens_are_decoded_sorted_and_limited_to_ten(client):
    text = "alpha alpha beta beta beta gamma gamma gamma gamma"

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    top_tokens = result["top_tokens"]
    assert len(top_tokens) <= 10
    assert [item["count"] for item in top_tokens] == sorted(
        (item["count"] for item in top_tokens),
        reverse=True,
    )
    for item in top_tokens:
        assert item["token"] == ENCODING.decode([item["id"]])
        assert item["count"] > 0
        assert item["percent"] == pytest.approx(
            item["count"] / result["total_tokens"] * 100
        )


def test_unique_words_ignore_case_and_punctuation(client):
    response = client.post(
        "/count-text",
        json={"text": "Cat, cat! DOG dog."},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["words"] == 4
    assert result["unique_words"] == 2


def test_tokenizer_selector_is_not_present():
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert "tokenizer" not in html.lower()
    assert "model-selector" not in html.lower()


def test_frontend_cost_and_context_logic_are_present():
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "const PRICE_PER_MILLION_TOKENS = 2.5;" in html
    assert "latestResult.total_tokens * PRICE_PER_MILLION_TOKENS / 1000000" in html
    for context_size in ("8192", "32768", "128000", "200000"):
        assert f'<option value="{context_size}">' in html
    assert "percentage > 100" in html
    assert "This text exceeds the selected context window." in html


def test_token_visualizer_uses_text_content_not_html_insertion():
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "span.textContent = token;" in html
    assert "tokenCell.textContent = showWhitespace(token.token);" in html
    assert ".innerHTML" not in html


def test_markup_like_pasted_text_is_returned_as_data_not_executed(client):
    text = "<script>alert(1)</script>"

    response = client.post("/count-text", json={"text": text})

    assert response.status_code == 200
    result = response.get_json()
    assert result["characters"] == len(text)
    assert result["filename"] == "Pasted text"


def test_frontend_mode_switch_visualizer_and_reduced_motion_hooks_exist():
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert 'id="upload-tab"' in html
    assert 'id="paste-tab"' in html
    assert 'id="visualizer"' in html
    assert "modeSwitch.classList.toggle(\"paste-active\", isPaste)" in html
    assert "@media (prefers-reduced-motion: no-preference)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "setTimeout(countPastedText, 300)" in html
    assert "MAX_VISUALIZED_TOKENS = 5000" in (PROJECT_ROOT / "app.py").read_text(
        encoding="utf-8"
    )


def test_header_cat_asset_and_responsive_styles_are_present(client):
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "static" / "style.css").read_text(encoding="utf-8")
    image_response = client.get("/static/cat-mascot.png")

    assert image_response.status_code == 200
    assert image_response.mimetype == "image/png"
    assert 'alt="Cat mascot"' in html
    assert 'class="brand-word">Tokenize' in html
    assert 'class="brand-badge">.me' in html
    assert "font-size: 2.25rem" in css
    assert "width: 120px" in css
    assert "width: 96px" in css
    assert "background-clip: text" in css
    assert "animation: mascot-float" in css
    assert "animation: mascot-bounce" in css
