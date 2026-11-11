# SmartPad – Intelligent Text Editor & Student Productivity Suite

SmartPad extends the original Tkinter notepad with persistent student notes,
document history and recovery, password-protected notes, a writing assistant,
voice tools, and student/focus workflows. Notes and settings are stored in a
local SQLite database; ordinary text files remain supported.

## Requirements

- Python 3.10 or newer
- Tkinter (included with the standard Windows Python installer)
- Dependencies from `requirements.txt`

Microphone capture additionally needs PyAudio. Its Windows installation can
depend on having a wheel available for your Python version. SmartPad reports a
clear error if the microphone backend or permissions are unavailable.

## Project structure

- `main.py` starts the Tkinter event loop.
- `editor.py` integrates the desktop UI, menus, editor, and productivity actions.
- `database.py` stores notes, categories, revisions, recent files, and recovery
  data in SQLite.
- `security.py` encrypts protected note content with Fernet.
- `ai_assistant.py` talks to a configured OpenAI-compatible provider.
- `voice.py` wraps optional speech recognition and synthesis.
- `features.py` contains text tools and document templates.
- `themes.py` defines the light and dark palettes.
- `tests/test_core.py` checks core behavior and integration workflows.

## Run in VS Code

1. Open this project folder in VS Code.
2. Install the Microsoft Python extension if it is not already installed.
3. Choose a Python 3.10+ interpreter with **Python: Select Interpreter** from the
   Command Palette.
4. Open the integrated terminal (**Terminal → New Terminal**) and install the
   dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Start the application:

   ```powershell
   python main.py
   ```

On systems where the Python launcher is used, `py -m pip install -r
requirements.txt` and `py main.py` also work.

Run the automated checks from the project folder with:

```powershell
python -m unittest discover -s tests -v
```

## Features

- **Notes:** SQLite-backed create, rename, delete, search, categories, favorites,
  and recently opened notes. Default categories include College Notes,
  Programming, Assignments, Personal, and Important.
- **Files and editing:** Open/save UTF-8 text files, undo/redo, clipboard, find
  and replace, case conversion, word wrap, date/time, font family, size, and
  color.
- **History and recovery:** Automatic periodic saves, recovery after an
  unexpected exit, up to 100 recent versions per note and 50 per text file,
  and a backup manager.
- **Protected notes:** Fernet authenticated encryption with a per-note random
  salt and PBKDF2-HMAC-SHA256 key derivation. Passwords are never written to
  the database. If you forget a password, the note cannot be recovered.
- **AI writing assistant:** Grammar correction, writing improvements, rewrite,
  summary, word explanations, and paragraph generation. The app does not
  pretend to generate text when no provider is configured.
- **Voice:** Optional microphone dictation and text-to-speech. Dictation uses
  SpeechRecognition's Google Web Speech service and therefore requires an
  internet connection; it is not an offline speech model.
- **Student and focus modes:** Assignment word target/completion, study timer,
  focus countdown, distraction-free writing, and highlighted passages.
- **Templates:** Assignments, seminar reports, meeting notes, journals, project
  documentation, and study notes.
- **Appearance:** Dark mode is the default; toggle light mode or customize the
  focus writing background.

## Optional AI setup

The assistant uses an OpenAI-compatible chat-completions API. It supports a
local Ollama-compatible endpoint or a hosted provider. Set these environment
variables **before launching SmartPad**:

```powershell
$env:SMARTPAD_AI_BASE_URL = "http://localhost:11434/v1"
$env:SMARTPAD_AI_MODEL = "your-installed-model"
# Set only when your provider requires an API key:
$env:SMARTPAD_AI_API_KEY = "your-api-key"
python main.py
```

For hosted providers, use their OpenAI-compatible API base URL and model name.
Selected text is sent to that configured provider only when you run an
assistant action. Avoid sending confidential material to a provider you do not
trust. With no endpoint/model configured, the assistant displays setup
instructions rather than returning fabricated output.

## Data location and privacy

SmartPad stores its database at `%USERPROFILE%\.smartpad\smartpad.sqlite3` on
Windows. Protected note bodies and protected revisions are encrypted before
they are written. Unprotected notes and recovery drafts are stored locally as
ordinary text in the SQLite database. Keep a separate backup of important data.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N | New text document |
| Ctrl+O | Open |
| Ctrl+S | Save |
| Ctrl+F | Find and replace |
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |
| Ctrl+Shift+A | Open AI writing assistant |
