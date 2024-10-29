# gphoto-bot

gphoto-bot is a [Discord](https://discord.com) bot that uses [gPhoto2](http://gphoto.org) to control a camera connected to the host machine. This allows the camera to be remotely controlled by multiple accounts through the Discord interface.

gphoto-bot is built using [discord.py](https://github.com/Rapptz/discord.py) for interacting with Discord and the [python-gphoto2](https://github.com/jim-easterbrook/python-gphoto2) interface for [libgphoto2](http://www.gphoto.org/proj/libgphoto2/).

# Installation

Follow these steps to install and run the bot.

### 1. Prerequisites

Make sure you have Python >= 3.12 installed, as well as `gphoto2`.

### 2. Create a Discord bot

Create a Discord bot at [https://discord.com/developers](https://discord.com/developers).

Start a new application, add a bot, and save the API token. You'll need that later. Invite the bot to your Discord server.

### 3. Clone this Repository

```bash
git clone https://github.com/kwilinsi/gphoto-bot.git
cd gphoto-bot
```

### 4. Install dependencies

Use a virtual environment to install the dependencies from `pip` listed in `requirements.txt`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `python-gphoto2` does not install correctly, you may need to run this command:

```bash
pip install gphoto2 --user --only-binary :all:
```

See [here](https://github.com/jim-easterbrook/python-gphoto2?tab=readme-ov-file#installation) for more information.

### 5. Initial run

Start the bot. It will throw an error, because we haven't set the bot's API token.

```bash
python3 -m gphotobot
```

This will automatically create the `config.ini` file. Edit that file, and supply the required configurations.

### 6. Re-run, and sync commands

Re-run the bot, this time with the `-s global` flag to sync the global slash commands.

```bash
python3 -m gphotobot -s global
```

This bot operates via Discord's slash command interface, not text commands.

Note that it may take up to an hour on Discord's end to sync slash commands. If you don't want to wait that long, you can sync with one server immediately. Use `-s dev` to sync with the development server specified in the configuration file.

To view a list of arguments, use

```bash
python3 -m gphotobot --help
```

### 7. Done!

You're all set. In the future, you can restart the bot without syncing. (Don't sync too often, or else Discord might rate-limit you).

```bash
python3 -m gphotobot
```

In Discord, you can see a list of available commands by typing `/` in a text channel where the bot is present.

When you're done using the bot, deactivate the virtual environment:

```bash
deactivate
```
