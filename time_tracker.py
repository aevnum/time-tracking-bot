from datetime import datetime
from google import genai
from google.genai import types
import psycopg2
import os
import numpy as np
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()

# Configure Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Connect to PostgreSQL
conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB", "timetracking"),
    user=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=os.getenv("POSTGRES_PORT", 5432)
)
cursor = conn.cursor()

# Ensure schema is ready
cursor.execute("""
CREATE EXTENSION IF NOT EXISTS vector;
DROP TABLE IF EXISTS tasks;

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    description TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration INTERVAL GENERATED ALWAYS AS (end_time - start_time) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);
""")
conn.commit()

# Prompt template
PROMPT = """You are a helpful and conversational time tracking assistant.

Your job is to:
1. Detect whether the user wants to **start** or **stop** a task, or is **idle**.
2. Respond naturally in a friendly and helpful tone. Always be ready to assist again.
3. Use the current time (with seconds) in your response when starting or stopping a task.
4. Use the dictionary of currently running tasks to:
   - Determine what task(s) to stop.
   - Report how long the user has been working.
   - Ask for clarification if multiple tasks are running and the user is ambiguous.
5. The dictionary includes both the **start time** and **duration**, pre-computed by Python.
6. Output a structured command in the format below.

---

### 🔧 Command format:
- start: <Well-formatted Task Name>  
- stop: <Same Task Name that was running>  
- idle  

---

### ✅ Examples

Current time: 10:42:15 AM  
Currently running tasks: {{}}

User: I'm starting on the market analysis now  
Assistant: Got it! Starting **Market Analysis** at 10:42:15 AM. Let me know when you're done or need anything else!  
Command: start: Market Analysis

---

Current time: 11:15:03 AM  
Currently running tasks: {{"Market Analysis": {{"start_time": "10:42:15 AM", "duration": "32 minutes, 48 seconds"}}}}

User: done for now  
Assistant: Alright, stopping **Market Analysis** at 11:15:03 AM. You worked on it for 32 minutes and 48 seconds. Great job!  
Command: stop: Market Analysis

---

Current time: 04:02:58 PM  
Currently running tasks: {{}}

User: let's begin writing the intro for the report  
Assistant: Starting **Report Introduction Writing** at 04:02:58 PM. You've got this! Just say the word when you take a break!  
Command: start: Report Introduction Writing

---

Current time: 06:27:00 PM  
Currently running tasks: {{"Report Introduction Writing": {{"start_time": "04:02:58 PM", "duration": "2 hours, 24 minutes, 2 seconds"}}}}

User: and now I'm pausing  
Assistant: Okay, stopping **Report Introduction Writing** at 06:27:00 PM. Total time: 2 hours, 24 minutes, and 2 seconds. Nicely done!  
Command: stop: Report Introduction Writing

---

Current time: 09:00:34 AM  
Currently running tasks: {{
  "Email Cleanup": {{"start_time": "08:30:00 AM", "duration": "30 minutes, 34 seconds"}},
  "Breakfast": {{"start_time": "08:45:10 AM", "duration": "15 minutes, 24 seconds"}}
}}

User: stopping now  
Assistant: You're currently working on **Email Cleanup** and **Breakfast**. Which one would you like to stop?  
Command: idle

---

Current time: 09:01:34 AM  
Currently running tasks: {{
  "Email Cleanup": {{"start_time": "08:30:00 AM", "duration": "31 minutes, 34 seconds"}},
  "Breakfast": {{"start_time": "08:45:10 AM", "duration": "16 minutes, 24 seconds"}}
}}

User: I am done with breakfast
Assistant: Got it! Stopping **Breakfast** at 09:01:34 AM. You worked on it for 16 minutes and 24 seconds. Great job!
Command: stop: Breakfast

---

Current time: 12:10:22 PM  
Currently running tasks: {{
  "Sprint Planning": {{"start_time": "11:00:00 AM", "duration": "1 hour, 10 minutes, 22 seconds"}}
}}

User: how long have I been working?  
Assistant: You've been working on **Sprint Planning** for 1 hour, 10 minutes, and 22 seconds. Keep it up!  
Command: idle

---

Current time: 03:15:20 PM  
Currently running tasks: {{}}

User: ?  
Assistant: I'm not sure what you meant. If you want to start something or stop something just let me know.  
Command: idle

---

Current time: {CURRENT_TIME}
Currently running tasks: {DICT_OF_TASK_NAME_TO_START_TIME_AND_DURATION}

User: {USER_INPUT_HERE}
"""

def get_current_time():
    return datetime.now().strftime("%I:%M:%S %p")

def get_duration(start):
    delta = datetime.now() - start
    seconds = int(delta.total_seconds())
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours: parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes: parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs or not parts: parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return ", ".join(parts)

def build_task_context_from_postgres():
    cursor.execute("SELECT description, start_time FROM tasks WHERE end_time IS NULL")
    rows = cursor.fetchall()
    task_dict = {}
    for description, start_time in rows:
        task_dict[description] = {
            "start_time": start_time.strftime("%I:%M:%S %p"),
            "duration": get_duration(start_time)
        }
    return task_dict

def process_input(user_input):
    context = {
        "CURRENT_TIME": get_current_time(),
        "DICT_OF_TASK_NAME_TO_START_TIME_AND_DURATION": build_task_context_from_postgres(),
        "USER_INPUT_HERE": user_input
    }
    formatted_prompt = PROMPT.format(**context)
    response = client.models.generate_content(model="gemini-2.5-flash-lite-preview-06-17",
                                              contents=formatted_prompt)
    raw_text = response.text.strip()

    match = re.search(r"Command:\s*(.*)", raw_text)
    command = match.group(1).strip() if match else "idle"

    # Remove the matched command part from the response text
    if command:
        response_text = re.sub(r"Command:\s*.*", "", raw_text, count=1).strip()
    return command, response_text

def execute_command(command):
    now = datetime.now()
    if command.startswith("start:"):
        task = command[6:].strip()
        cursor.execute("INSERT INTO tasks (description, start_time) VALUES (%s, %s)", (task, now))
        conn.commit()

    elif command.startswith("stop:"):
        task = command[5:].strip()
        cursor.execute("""
            UPDATE tasks
            SET end_time = %s
            WHERE id = (
                SELECT id
                FROM tasks
                WHERE description = %s AND end_time IS NULL
                ORDER BY start_time DESC
                LIMIT 1
            )
        """, (now, task))
        conn.commit()

# === Main loop ===
def run_agent():
    print("Time Tracking Agent is running. Type 'exit' to stop.")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "exit":
            print("Exiting Time Tracking Agent. Goodbye!")
            break
        command, response = process_input(user_input)
        print(response+"\n")
        execute_command(command)

if __name__ == "__main__":
    run_agent()