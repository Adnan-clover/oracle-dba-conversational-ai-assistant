# Oracle DBA Conversational AI Assistant

An intelligent conversational AI assistant built with Streamlit to assist with Oracle Database Administration (DBA) tasks.

---

## 🚀 Getting Started

Follow these step-by-step instructions to get the application running locally on your machine.

### 📋 Prerequisites
Before starting, ensure you have the following software installed:
* **Python** (v3.8 or higher)
* **Docker**

---

## 🛠️ Installation & Setup

### 1. Start the Oracle Database Container
Run the following command to pull and launch a local Oracle Express Edition (XE) database instance via Docker:

```bash
docker run -d --name oracle-xe -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-xe
```

### 2. Set Up a Virtual Environment
Create an isolated Python environment for your project:

```bash
python -m venv .venv
```

### 3. Activate the Virtual Environment
Activate the environment based on your current operating system:

* **macOS / Linux:**
  ```bash
  source .venv/bin/activate
  ```
* **Windows (Command Prompt):**
  ```cmd
  .venv\Scripts\activate.bat
  ```
* **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

### 4. Install Project Dependencies
Ensure your environment is active, then install all required libraries:

```bash
pip install -r requirements.txt
```

---

## 🏃 Running the Application

Launch the Streamlit web application using the command below:

```bash
streamlit run oracle_dba_assistant.py
```

After executing, the app will automatically open in your default browser at `http://localhost:8501`.

---

## 🛑 How to Stop the Application

* **Stop the App**: Press `Ctrl + C` in your terminal to shut down the Streamlit server.
* **Deactivate Environment**: Type `deactivate` to exit the Python virtual environment.
* **Stop Database**: Run `docker stop oracle-xe` to pause the database container.
