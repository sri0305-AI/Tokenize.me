# Tokenize.me

Tokenize.me is a small Flask app for counting tokens in text or documents. Upload a TXT, PDF, or DOCX file, or paste text into the page to see token, word, and character statistics.

## Features

- Upload TXT, PDF, and DOCX files, or count pasted text as you type.
- Show total tokens, unique tokens, repetition ratio, word counts, and character count.
- See a token-by-token preview and the 10 most frequent tokens.
- Estimate cost using the app's fixed rate of $2.50 per million tokens.
- Compare token usage with 8K, 32K, 128K, and 200K context windows.
- Display a clear warning when text exceeds the selected context window.
- Process uploaded documents in memory; files are not saved to disk.
- Support files up to 20 MiB.

Token counts use the `cl100k_base` encoding. Whitespace-only token IDs are excluded from total and unique token statistics. Tokenized spaces attached to words remain part of those tokens. The visualizer shows up to 5,000 tokens.

## Requirements

- Python 3.10 or later
- Windows, macOS, or Linux

## Run locally

### Windows PowerShell

1. Open a terminal in the project folder.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the app dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the development server:

   ```powershell
   python app.py
   ```

5. Open <http://127.0.0.1:5000> in your browser.

If PowerShell blocks virtual-environment activation, you can run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Run tests

Install pytest in the active environment and run the test suite:

```powershell
python -m pip install pytest
python -m pytest -q
```

The tests cover upload and paste routes, token statistics, input errors, document parsing, the upload-size limit, and safe display of token text.

## API

### `POST /count`

Send a multipart form upload using the field name `file`. Accepted file extensions are `.txt`, `.pdf`, and `.docx`.

### `POST /count-text`

Send JSON containing a non-empty `text` string:

```json
{
  "text": "Paste text to count"
}
```

Both endpoints return JSON with the filename, character and word counts, total and unique token counts, repetition ratio, top tokens, and visualizer data.

## Project structure

```text
token_counter_app/
├── app.py
├── requirements.txt
├── templates/
│   └── index.html
├── static/
│   ├── cat-mascot.png
│   └── style.css
└── tests/
    └── test_app.py
```

The built-in Flask server is for local development. Use a production WSGI server and disable debug mode before deploying the app publicly.
