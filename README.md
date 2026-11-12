# SmartPad – Intelligent Text Editor & Student Productivity Suite

SmartPad is a feature-rich desktop text editor developed using Python and Tkinter. It extends a traditional Notepad with intelligent writing assistance, student productivity tools, document security, automatic recovery, and smart note management.

## 1. Requirements

- Python 3.10 or newer
- Tkinter
- Dependencies listed in requirements.txt

Optional microphone functionality requires PyAudio. Some AI features require an AI provider or a locally running language model.

## 2. Project Structure

- `main.py` – Starts the application.
- `editor.py` – Main graphical user interface.
- `database.py` – SQLite database management.
- `security.py` – Password protection and document encryption.
- `ai_assistant.py` – AI writing assistant.
- `voice.py` – Voice typing and text-to-speech.
- `features.py` – Text processing and document templates.
- `themes.py` – Light and dark themes.
- `tests/` – Automated tests.

## 3. Main Features

### Text Editing
- Create, open and save documents.
- Cut, copy and paste.
- Undo and redo.
- Find and replace.
- Font customization.
- Word wrap.
- Date and time insertion.

### AI Writing Assistant
- Grammar correction.
- Sentence improvement.
- Text rewriting.
- Paragraph summarization.
- Difficult word explanations.
- Paragraph generation.

### Voice Features
- Voice typing.
- Speech-to-text conversion.
- Text-to-speech.
- Read selected text aloud.

### Smart Notes Manager
- Create and manage notes.
- Rename and delete notes.
- Search notes.
- Organize notes by categories.
- Mark favorite notes.
- Access recently opened notes.

### Security and Recovery
- Password-protected documents.
- Encrypted document contents.
- Automatic document backups.
- Unsaved document recovery.
- Document version history.

### Student Productivity Mode
- Assignment writing mode.
- Word count target.
- Assignment completion percentage.
- Study timer.
- Subject-wise note organization.
- Important text highlighting.

### Focus Mode
- Distraction-free writing.
- Focus timer.
- Customizable writing background.
- Live word count.

### Additional Features
- Light and dark themes.
- Document templates.
- Word and character counter.
- Line counter.
- Text case conversion.

## 4. Technologies Used

| Technology | Purpose |
|---|---|
| Python | Main programming language |
| Tkinter | GUI development |
| SQLite | Database management |
| Cryptography | Document encryption |
| SpeechRecognition | Voice typing |
| Text-to-Speech | Speech output |
| OpenAI-compatible API | AI writing assistance |

## 5. Installation

Clone the repository:

```bash
git clone https://github.com/amahakud328-spec/Python-Project.git
```

Open the project folder:

```bash
cd Python-Project
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## 6. Run the Application

Execute:

```bash
python main.py
```

## 7. Run Tests

Execute:

```bash
python -m unittest discover -s tests -v
```

## 8. Optional AI Configuration

SmartPad supports an OpenAI-compatible AI endpoint.

Example configuration for a local Ollama-compatible server:

```powershell
$env:SMARTPAD_AI_BASE_URL = "http://localhost:11434/v1"
$env:SMARTPAD_AI_MODEL = "your-installed-model"
python main.py
```

For hosted AI services, configure the appropriate endpoint, model and API key.

Never upload private API keys or passwords to GitHub.

## 9. Project Objective

The main objective of SmartPad is to transform a traditional text editor into an intelligent and productive writing environment.

It combines text editing, AI assistance, voice interaction, document security and student productivity tools in one desktop application.

## 10. Developed For

B.Tech Computer Science and Engineering (Artificial Intelligence)

**Project Name:** SmartPad – Intelligent Text Editor & Student Productivity Suite

**Repository:** Python-Project