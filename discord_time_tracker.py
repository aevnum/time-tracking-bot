import discord
from discord.ext import commands
from datetime import datetime
from google import genai
from google.genai import types
import psycopg2
import os
import numpy as np
from dotenv import load_dotenv
import re
import asyncio

# Load environment variables
load_dotenv()

# Configure Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database connection pool
class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()
    
    def connect(self):
        try:
            self.conn = psycopg2.connect(
                dbname=os.getenv("POSTGRES_DB", "timetracking"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD"),
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=os.getenv("POSTGRES_PORT", 5432)
            )
            self.cursor = self.conn.cursor()
            self.setup_schema()
        except Exception as e:
            print(f"Database connection error: {e}")
    
    def setup_schema(self):
        # Create user-specific tables
        self.cursor.execute("""
        CREATE EXTENSION IF NOT EXISTS vector;
        
        CREATE TABLE IF NOT EXISTS user_tasks (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            description TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration INTERVAL GENERATED ALWAYS AS (end_time - start_time) STORED,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_user_tasks_user_id ON user_tasks(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_tasks_active ON user_tasks(user_id, end_time) WHERE end_time IS NULL;
        """)
        self.conn.commit()

# Global database manager
db = DatabaseManager()

# Prompt template (modified for Discord context)
PROMPT = """You are a helpful and conversational time tracking assistant for Discord.

Your job is to:
1. Detect whether the user wants to **start** or **stop** a task, or is **idle**.
2. Respond naturally in a friendly and helpful tone. Keep responses concise for Discord.
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
Assistant: 📊 Starting **Market Analysis** at 10:42:15 AM. Let me know when you're done!  
Command: start: Market Analysis

---

Current time: 11:15:03 AM  
Currently running tasks: {{"Market Analysis": {{"start_time": "10:42:15 AM", "duration": "32 minutes, 48 seconds"}}}}

User: done for now  
Assistant: ✅ Stopping **Market Analysis** at 11:15:03 AM. You worked for 32 minutes and 48 seconds. Great job!  
Command: stop: Market Analysis

---

Current time: 09:00:34 AM  
Currently running tasks: {{
  "Email Cleanup": {{"start_time": "08:30:00 AM", "duration": "30 minutes, 34 seconds"}},
  "Breakfast": {{"start_time": "08:45:10 AM", "duration": "15 minutes, 24 seconds"}}
}}

User: stopping now  
Assistant: 🤔 You're currently working on **Email Cleanup** and **Breakfast**. Which one would you like to stop?  
Command: idle

---

Current time: 12:10:22 PM  
Currently running tasks: {{
  "Sprint Planning": {{"start_time": "11:00:00 AM", "duration": "1 hour, 10 minutes, 22 seconds"}}
}}

User: how long have I been working?  
Assistant: ⏱️ You've been working on **Sprint Planning** for 1 hour, 10 minutes, and 22 seconds. Keep it up!  
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

def build_task_context_from_postgres(user_id):
    db.cursor.execute("SELECT description, start_time FROM user_tasks WHERE user_id = %s AND end_time IS NULL", (user_id,))
    rows = db.cursor.fetchall()
    task_dict = {}
    for description, start_time in rows:
        task_dict[description] = {
            "start_time": start_time.strftime("%I:%M:%S %p"),
            "duration": get_duration(start_time)
        }
    return task_dict

async def process_input(user_input, user_id):
    context = {
        "CURRENT_TIME": get_current_time(),
        "DICT_OF_TASK_NAME_TO_START_TIME_AND_DURATION": build_task_context_from_postgres(user_id),
        "USER_INPUT_HERE": user_input
    }
    formatted_prompt = PROMPT.format(**context)
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite-preview-06-17",
            contents=formatted_prompt
        )
        raw_text = response.text.strip()
        
        match = re.search(r"Command:\s*(.*)", raw_text)
        command = match.group(1).strip() if match else "idle"
        
        # Remove the matched command part from the response text
        if command:
            response_text = re.sub(r"Command:\s*.*", "", raw_text, count=1).strip()
        return command, response_text
    except Exception as e:
        return "idle", f"❌ Error processing request: {str(e)}"

def execute_command(command, user_id, username):
    now = datetime.now()
    try:
        if command.startswith("start:"):
            task = command[6:].strip()
            db.cursor.execute(
                "INSERT INTO user_tasks (user_id, username, description, start_time) VALUES (%s, %s, %s, %s)",
                (user_id, username, task, now)
            )
            db.conn.commit()
            
        elif command.startswith("stop:"):
            task = command[5:].strip()
            db.cursor.execute("""
                UPDATE user_tasks
                SET end_time = %s
                WHERE id = (
                    SELECT id
                    FROM user_tasks
                    WHERE user_id = %s AND description = %s AND end_time IS NULL
                    ORDER BY start_time DESC
                    LIMIT 1
                )
            """, (now, user_id, task))
            db.conn.commit()
    except Exception as e:
        print(f"Database error: {e}")
        db.connect()  # Reconnect on error

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} servers')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(f'Error syncing commands: {e}')

@bot.tree.command(name='track', description='Track time with natural language')
async def track_time(interaction: discord.Interaction, message: str):
    """Main time tracking command"""
    user_id = interaction.user.id
    username = str(interaction.user)
    
    # Defer response to allow processing time
    await interaction.response.defer()
    
    command, response = await process_input(message, user_id)
    execute_command(command, user_id, username)
    
    await interaction.followup.send(response)

@bot.tree.command(name='status', description='Show your current active tasks')
async def current_status(interaction: discord.Interaction):
    """Show current active tasks"""
    user_id = interaction.user.id
    tasks = build_task_context_from_postgres(user_id)
    
    if not tasks:
        await interaction.response.send_message("🔄 No active tasks running.")
        return
    
    response = "📋 **Your Active Tasks:**\n"
    for task_name, info in tasks.items():
        response += f"• **{task_name}** - {info['duration']} (started at {info['start_time']})\n"
    
    await interaction.response.send_message(response)

@bot.tree.command(name='history', description='Show task history for the last N days')
async def task_history(interaction: discord.Interaction, days: int = 1):
    """Show task history for the last N days"""
    user_id = interaction.user.id
    
    db.cursor.execute("""
        SELECT description, start_time, end_time, duration
        FROM user_tasks 
        WHERE user_id = %s AND end_time IS NOT NULL 
        AND start_time >= NOW() - INTERVAL '%s days'
        ORDER BY start_time DESC
        LIMIT 10
    """, (user_id, days))
    
    rows = db.cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message(f"📅 No completed tasks found in the last {days} day(s).")
        return
    
    response = f"📊 **Task History (Last {days} day(s)):**\n"
    for desc, start, end, duration in rows:
        start_str = start.strftime("%m/%d %I:%M %p")
        duration_str = str(duration).split('.')[0]  # Remove microseconds
        response += f"• **{desc}** - {duration_str} ({start_str})\n"
    
    if len(response) > 2000:  # Discord message limit
        response = response[:1900] + "\n... (truncated)"
    
    await interaction.response.send_message(response)

@bot.tree.command(name='stats', description='Show today\'s time tracking statistics')
async def daily_stats(interaction: discord.Interaction):
    """Show today's time tracking stats"""
    user_id = interaction.user.id
    
    # Get today's completed tasks
    db.cursor.execute("""
        SELECT description, SUM(EXTRACT(EPOCH FROM duration)) as total_seconds
        FROM user_tasks 
        WHERE user_id = %s AND end_time IS NOT NULL 
        AND DATE(start_time) = CURRENT_DATE
        GROUP BY description
        ORDER BY total_seconds DESC
    """, (user_id,))
    
    rows = db.cursor.fetchall()
    
    if not rows:
        await interaction.response.send_message("📈 No completed tasks today yet.")
        return
    
    total_time = sum(row[1] for row in rows)
    hours = int(total_time // 3600)
    minutes = int((total_time % 3600) // 60)
    
    response = f"📈 **Today's Stats** (Total: {hours}h {minutes}m):\n"
    for desc, seconds in rows:
        task_hours = int(seconds // 3600)
        task_minutes = int((seconds % 3600) // 60)
        response += f"• **{desc}** - {task_hours}h {task_minutes}m\n"
    
    await interaction.response.send_message(response)

@bot.tree.command(name='help', description='Show help for time tracking commands')
async def help_tracking(interaction: discord.Interaction):
    """Show help for time tracking commands"""
    embed = discord.Embed(
        title="⏱️ Time Tracking Bot Help",
        description="Track your time with natural language!",
        color=0x00ff00
    )
    
    embed.add_field(
        name="🎯 Main Commands",
        value=(
            "`/track <message>` - Start/stop tasks naturally\n"
            "`/status` - Show active tasks\n"
            "`/history [days]` - Show recent history\n"
            "`/stats` - Show today's stats"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💬 Natural Language Examples",
        value=(
            "• `/track starting work on the presentation`\n"
            "• `/track done with coding for now`\n"
            "• `/track how long have I been working?`\n"
            "• `/track taking a break`"
        ),
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required argument. Use `!help_track` for usage info.")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")
        print(f"Error: {error}")

if __name__ == "__main__":
    # Get Discord token from environment
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables")
        exit(1)
    
    bot.run(token)