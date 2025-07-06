# Time Tracking AI

---

Have you started remote working or freelancing and find it hard to keep track of your time? Time tracking is a great way to understand how you spend your time and improve your productivity. This AI Time Tracking chatbot helps you track your time spent on different tasks using natural language commands without the tedious process of manually entering time logs.

---

# Features

- Natural language based time tracking
- Supports both CLI and Discord bot interfaces
- Uses Gemini as the LLM and PostgreSQL as the database
- More features coming soon! (Work In Progress)

### Planned Features
- Creating a visual timesheet
- Being able to edit time logs and ongoing tasks
- Vector search for natural language task retrieval
- Reminders for tasks that you might have forgotten to end
- Task suggestions based on your past activities

---

# Installation

- Using the application requires a .env file.
- You can create a .env file with the following content:

```env
GEMINI_API_KEY=
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=
POSTGRES_PORT=
DISCORD_BOT_TOKEN=
```

---

# Usage for CLI Bot

- Make sure you have the necessary Python packages installed. 
- Make sure you have a PostgreSQL database set up and the required environment variables in your `.env` file.
- Ensure the PostgreSQL server is running and accessible with the credentials provided in your `.env` file.
- Run the python file `time_tracker.py` to start the application. You can run it with the command:
```bash
python time_tracker.py
```
- This runs the application in your CLI. Type 'exit' to stop the application.

---

# Usage for Discord Bot

- Make sure you have the necessary Python packages installed. 
- Make sure you have a PostgreSQL database set up and the required environment variables in your `.env` file.
- Ensure the PostgreSQL server is running and accessible with the credentials provided in your `.env` file.
- Create a Discord bot and get the bot token. Add the token to your `.env` file.
- Run the python file `discord_time_tracker.py` to start the Discord bot. You can run it with the command:
```bash
python discord_time_tracker.py
```
- On the developer portal, go to Bot settings and enable the "MESSAGE CONTENT INTENT" to allow the bot to read messages.
- Invite the bot to your server using the OAuth2 URL with the `bot` and `applications.commands` scopes. Under "Bot Permissions", select the permissions - `Send Messages`, `Read Message History`, and `Use Slash Commands`.
- Now you can use the bot in your Discord server. Type `/help` to see the available commands.