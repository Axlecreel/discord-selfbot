from http.client import HTTPSConnection 
from json import dumps, loads
from time import sleep 
import json
import threading
from datetime import datetime
import random
import os
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.live import Live
from rich.align import Align

app = typer.Typer()
console = Console()

BANNER = """
 █████╗ ██╗   ██╗████████╗ ██████╗     ███╗   ███╗███████╗ ██████╗ 
██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗    ████╗ ████║██╔════╝██╔════╝ 
███████║██║   ██║   ██║   ██║   ██║    ██╔████╔██║███████╗██║  ███╗
██╔══██║██║   ██║   ██║   ██║   ██║    ██║╚██╔╝██║╚════██║██║   ██║
██║  ██║╚██████╔╝   ██║   ╚██████╔╝    ██║ ╚═╝ ██║███████║╚██████╔╝
╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝     ╚═╝     ╚═╝╚══════╝ ╚═════╝ 
"""

shutdown_event = threading.Event()
channel_statuses = {}
status_lock = threading.Lock()
total_sent_global = 0

def save_config(config_data):
    with open('./config.json', 'w') as f:
        json.dump(config_data, f, indent=4)

def load_config():
    if not os.path.exists('./config.json'): return None
    with open('./config.json', 'r') as f: return json.load(f)

def generate_status_table():
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Nickname", style="green", width=15)
    table.add_column("Sent (Ch)", justify="center", style="bold cyan")
    table.add_column("Current Status", width=30)
    table.add_column("Last Sent", justify="right", style="dim")
    with status_lock:
        for name, info in sorted(channel_statuses.items()):
            table.add_row(name, str(info['count']), info['msg'], info['ts'])
    return Panel(
        Align.center(table),
        title=f"[bold white]Live Monitor[/bold white] | [bold green]Total Global Sent: {total_sent_global}[/bold green]",
        border_style="blue",
        subtitle="[dim]Press Ctrl+C to Stop[/dim]"
    )

def update_status(name, msg, ts=None, count=None):
    with status_lock:
        if name not in channel_statuses:
            channel_statuses[name] = {"msg": "", "ts": "-", "count": 0}
        channel_statuses[name]["msg"] = msg
        if ts: channel_statuses[name]["ts"] = ts
        if count is not None: channel_statuses[name]["count"] = count

def send_message_with_retry(cid, data, token, name): 
    global total_sent_global
    while not shutdown_event.is_set():
        try:
            conn = HTTPSConnection("discordapp.com", 443)
            conn.request("POST", f"/api/v9/channels/{cid}/messages", data, {"content-type": "application/json", "authorization": token}) 
            resp = conn.getresponse() 
            if 199 < resp.status < 300: 
                total_sent_global += 1
                with status_lock:
                    channel_statuses[name]["count"] += 1
                    current_count = channel_statuses[name]["count"]
                update_status(name, "[bold green]✓ Success[/bold green]", datetime.now().strftime('%H:%M:%S'), count=current_count)
                return True
            elif resp.status == 429:
                body = resp.read().decode()
                wait_time = int(loads(body).get('retry_after', 5))
                for i in range(wait_time, 0, -1):
                    if shutdown_event.is_set(): return False
                    update_status(name, f"[bold red]⚠ Rate Limit: {i}s[/bold red]")
                    sleep(1)
                continue 
            return False 
        except Exception:
            sleep(5)
            continue

def message_loop(msg, mini, maxi, cid, token, name):
    while not shutdown_event.is_set():
        success = send_message_with_retry(cid, dumps({"content": msg}), token, name)
        if success and not shutdown_event.is_set():
            delay = int(random.uniform(mini, maxi))
            for i in range(delay, 0, -1):
                if shutdown_event.is_set(): break
                update_status(name, f"[bold yellow]⏲ Cooldown: {i}s[/bold yellow]")
                sleep(1)

def display_channel_content_table(config, title="Channel Messages"):
    table = Table(title=title)
    table.add_column("ID", justify="center", style="cyan")
    table.add_column("Nickname", style="green")
    table.add_column("Message Content", style="white")
    for i, entry in enumerate(config["Config"]):
        msg = entry["messages"][0]["content"]
        preview = (msg[:50] + '...') if len(msg) > 50 else msg
        table.add_row(str(i+1), entry["name"], preview)
    console.print(table)

def start_bot():
    config = load_config()
    if not config or not config.get("Global_Token"): 
        console.print("[bold red]Error: No Global Token set![/bold red]")
        sleep(2)
        return
    tok = config['Global_Token']
    shutdown_event.clear()
    channel_statuses.clear()
    for entry in config.get('Config', []):
        update_status(entry["name"], "[dim]Wait...[/dim]", count=0)
        threading.Thread(target=message_loop, args=(entry['messages'][0]['content'], entry['messages'][0]['min_interval'], entry['messages'][0]['max_interval'], entry["channel_id"], tok, entry["name"]), daemon=True).start()
    with Live(generate_status_table(), refresh_per_second=2) as live:
        try:
            while not shutdown_event.is_set():
                live.update(generate_status_table())
                sleep(0.5)
        except KeyboardInterrupt:
            shutdown_event.set()

def setup_wizard():
    config = load_config() or {"Global_Token": "", "Config": []}
    name = Prompt.ask("Nickname (or 'c' to cancel)")
    if name.lower() == 'c': return
    cid = Prompt.ask("Channel ID")
    msg = get_multiline_input("Message content")
    if msg.lower() == 'c': return
    
    while True:
        try:
            mini = float(Prompt.ask("Min delay", default="60"))
            maxi = float(Prompt.ask("Max delay", default="120"))
            break
        except ValueError:
            console.print("[bold red]Invalid number. Please enter digits only.[/bold red]")

    config["Config"].append({"name": name, "channel_id": cid, "messages": [{"content": msg, "min_interval": mini, "max_interval": maxi}]})
    save_config(config)

def update_token_wizard():
    config = load_config() or {"Global_Token": "", "Config": []}
    new_token = Prompt.ask("Enter Global Token (or 'c' to cancel)")
    if new_token.lower() == 'c': return
    config["Global_Token"] = new_token
    save_config(config)

def edit_message_wizard():
    config = load_config()
    if not config or not config["Config"]: return
    while True:
        display_channel_content_table(config, "Select Channel to Edit Message")
        choice = Prompt.ask("Select ID, 'all', or 'c' to cancel")
        if choice.lower() == 'c': return
        if choice.lower() == 'all': break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(config["Config"]): break
            console.print(f"[bold red]Error: ID {choice} is out of range.[/bold red]")
        except ValueError:
            console.print(f"[bold red]Error: '{choice}' is not a valid ID.[/bold red]")

    new_msg = get_multiline_input("Enter new message (or 'c' to cancel)")
    if new_msg.lower() == 'c': return
    if choice.lower() == 'all':
        for entry in config["Config"]: entry["messages"][0]["content"] = new_msg
    else:
        config["Config"][int(choice)-1]["messages"][0]["content"] = new_msg
    save_config(config)

def interval_wizard():
    config = load_config()
    if not config or not config["Config"]: return
    while True:
        display_interval_table(config)
        choice = Prompt.ask("Select ID, 'all', or 'c' to cancel")
        if choice.lower() == 'c': return
        if choice.lower() == 'all' or (choice.isdigit() and 1 <= int(choice) <= len(config["Config"])):
            break
        console.print("[bold red]Invalid selection. Try again.[/bold red]")
    
    while True:
        try:
            mini = float(Prompt.ask("New Min"))
            maxi = float(Prompt.ask("New Max"))
            break
        except ValueError:
            console.print("[bold red]Please enter valid numbers for intervals.[/bold red]")

    if choice.lower() == 'all':
        for entry in config["Config"]:
            entry["messages"][0]["min_interval"], entry["messages"][0]["max_interval"] = mini, maxi
    else:
        config["Config"][int(choice)-1]["messages"][0]["min_interval"], config["Config"][int(choice)-1]["messages"][0]["max_interval"] = mini, maxi
    save_config(config)

def delete_channel_wizard():
    config = load_config()
    if not config or not config["Config"]: return
    while True:
        display_channel_content_table(config, "Select Channel to Delete")
        choice = Prompt.ask("Select ID to delete or 'c' to cancel")
        if choice.lower() == 'c': return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(config["Config"]):
                config["Config"].pop(idx)
                break
            console.print("[bold red]ID out of range.[/bold red]")
        except ValueError:
            console.print("[bold red]Please enter a valid number ID.[/bold red]")
    save_config(config)

def get_multiline_input(prompt_text):
    console.print(f"[yellow]{prompt_text}[/yellow] [dim](Type 'END' to save, 'c' to cancel)[/dim]")
    lines = []
    while True:
        line = input()
        if line.strip().lower() == 'c': return 'c'
        if line.strip().upper() == "END": break
        lines.append(line)
    return "\n".join(lines)

def display_interval_table(config):
    table = Table(title="Channel Intervals")
    table.add_column("ID", justify="center", style="cyan")
    table.add_column("Nickname", style="green")
    table.add_column("Range", style="yellow")
    for i, entry in enumerate(config["Config"]):
        m = entry["messages"][0]
        table.add_row(str(i+1), entry["name"], f"{m['min_interval']}s-{m['max_interval']}s")
    console.print(table)

@app.command()
def main():
    while True:
        console.print(Panel.fit(BANNER, title="Discord Automator", border_style="blue"))
        console.print("\n1. [bold green]Start Bot[/bold green]\n2. [bold cyan]Add New Channels[/bold cyan]\n3. [bold magenta]Update Global Token[/bold magenta]\n4. [bold yellow]Edit Messages[/bold yellow]\n5. [bold blue]Change Intervals[/bold blue]\n6. [bold red]Delete Channels[/bold red]\n7. Exit")
        c = Prompt.ask("Action", choices=["1","2","3","4","5","6","7"])
        if c == "1": start_bot()
        elif c == "2": setup_wizard()
        elif c == "3": update_token_wizard()
        elif c == "4": edit_message_wizard()
        elif c == "5": interval_wizard()
        elif c == "6": delete_channel_wizard()
        elif c == "7": break

if __name__ == '__main__':
    app()
