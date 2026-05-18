from http.client import HTTPSConnection 
from json import dumps, loads
from time import sleep 
import json
import threading
from datetime import datetime
import random
import os
import shutil
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.live import Live
from rich.align import Align

app = typer.Typer()
console = Console()

BANNER = "🤖 ✨ [bold cyan]A U T O   M S G   N I   A X L E[/bold cyan] ✨ 💬"

shutdown_event = threading.Event()
channel_statuses = {}
status_lock = threading.Lock()
total_sent_global = 0
bot_run_cache = {}

# --- Profile Management Helpers ---
def get_manager():
    if os.path.exists('./config_manager.json'):
        with open('./config_manager.json', 'r') as f:
            try: return json.load(f)
            except Exception: pass
    return {"active_profile": "default"}

def save_manager(data):
    with open('./config_manager.json', 'w') as f:
        json.dump(data, f, indent=4)

def list_profiles():
    profiles = []
    if os.path.exists('.'):
        for file in os.listdir('.'):
            if file.startswith('config_') and file.endswith('.json') and file != 'config_manager.json':
                profiles.append(file[7:-5])
    if not profiles:
        profiles = ["default"]
    return sorted(profiles)

def get_active_profile_name():
    active = get_manager().get("active_profile", "default")
    profiles = list_profiles()
    if active not in profiles:
        active = profiles[0]
        mgr = get_manager()
        mgr["active_profile"] = active
        save_manager(mgr)
    return active

def get_profile_filename(profile_name):
    return f"./config_{profile_name}.json"

def init_profile_system():
    active = get_active_profile_name()
    filename = get_profile_filename(active)
    
    if active == "default" and not os.path.exists(filename) and os.path.exists('./config.json'):
        try: os.rename('./config.json', filename)
        except Exception: pass
            
    if not os.path.exists(filename):
        with open(filename, 'w') as f:
            json.dump({"Discord_Token": "", "Config": []}, f, indent=4)

# --- Main Configuration Handlers ---
def load_config():
    init_profile_system()
    p_name = get_active_profile_name()
    filename = get_profile_filename(p_name)
    
    with open(filename, 'r') as f: 
        try:
            data = json.load(f)
            if "Global_Token" in data:
                data["Discord_Token"] = data.pop("Global_Token")
                with open(filename, 'w') as fw:
                    json.dump(data, fw, indent=4)
            return data
        except Exception:
            return {"Discord_Token": "", "Config": []}

def save_config(config_data):
    p_name = get_active_profile_name()
    filename = get_profile_filename(p_name)
    with open(filename, 'w') as f:
        json.dump(config_data, f, indent=4)

# --- Operational Logic Functions ---
def generate_status_table():
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Nickname", style="green", width=12)
    table.add_column("Channel ID", style="yellow", width=19)
    table.add_column("Interval", style="blue", width=11)
    table.add_column("Sent (Ch)", justify="center", style="bold cyan")
    table.add_column("Current Status", width=24)
    table.add_column("Last Sent", justify="right", style="dim")
    with status_lock:
        for name, info in sorted(channel_statuses.items()):
            cache = bot_run_cache.get(name, {"channel_id": "Unknown", "interval": "Unknown"})
            table.add_row(name, cache["channel_id"], cache["interval"], str(info['count']), info['msg'], info['ts'])
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
            conn = HTTPSConnection("discordapp.com", 443, timeout=10)
            conn.request("POST", f"/api/v9/channels/{cid}/messages", data, {"content-type": "application/json", "authorization": token}) 
            resp = conn.getresponse() 
            
            if 199 < resp.status < 300: 
                total_sent_global += 1
                with status_lock:
                    channel_statuses[name]["count"] += 1
                    current_count = channel_statuses[name]["count"]
                update_status(name, "[bold green]✓ Sent[/bold green]", datetime.now().strftime('%H:%M:%S'), count=current_count)
                return True
            elif resp.status == 429:
                body = resp.read().decode()
                wait_time = int(loads(body).get('retry_after', 5))
                for i in range(wait_time, 0, -1):
                    if shutdown_event.is_set(): return False
                    update_status(name, f"[bold red]⚠ Rate Limit: {i}s[/bold red]")
                    sleep(1)
                continue 
            elif resp.status == 401:
                update_status(name, "[bold red]❌ Err: Bad Token (401)[/bold red]")
                sleep(5)
                return False
            elif resp.status == 403:
                update_status(name, "[bold red]❌ Err: No Perms (403)[/bold red]")
                sleep(5)
                return False
            elif resp.status == 404:
                update_status(name, "[bold red]❌ Err: Not Found (404)[/bold red]")
                sleep(5)
                return False
            elif resp.status >= 500:
                update_status(name, f"[bold red]❌ Err: Discord Down ({resp.status})[/bold red]")
                sleep(5)
                continue
            else:
                update_status(name, f"[bold red]❌ Err: HTTP {resp.status}[/bold red]")
                sleep(5)
                return False 
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                update_status(name, "[bold red]❌ Err: Network Timeout[/bold red]")
            elif "connection" in err_str or "getaddrinfo" in err_str or "unreachable" in err_str:
                update_status(name, "[bold red]❌ Err: Offline/No Internet[/bold red]")
            else:
                update_status(name, f"[bold red]❌ Err: {str(e)[:18]}[/bold red]")
            sleep(5)
            continue

def message_loop(msg, mini, maxi, cid, token, name):
    while not shutdown_event.is_set():
        update_status(name, "[bold yellow]⏳ Sending...[/bold yellow]")
        success = send_message_with_retry(cid, dumps({"content": msg}), token, name)
        if success and not shutdown_event.is_set():
            delay = int(random.uniform(mini, maxi))
            for i in range(delay, 0, -1):
                if shutdown_event.is_set(): break
                update_status(name, f"[bold yellow]⏲ Cooldown: {i}s[/bold yellow]")
                sleep(1)
        else:
            if shutdown_event.is_set(): break
            sleep(5)

def display_channel_content_table(config, title="Channel Messages"):
    table = Table(title=title, header_style="bold magenta")
    table.add_column("ID", justify="center", style="cyan")
    table.add_column("Nickname", style="green")
    table.add_column("Channel ID", style="yellow")
    table.add_column("Interval Range", style="blue")
    table.add_column("Message Content Preview", style="white")
    for i, entry in enumerate(config["Config"]):
        msg = entry["messages"][0]["content"]
        preview = (msg[:40] + '...') if len(msg) > 40 else msg
        m = entry["messages"][0]
        table.add_row(str(i+1), entry["name"], entry["channel_id"], f"{m['min_interval']}s-{m['max_interval']}s", preview)
    console.print(table)

def fetch_channel_and_guild_info(cid, token):
    try:
        conn = HTTPSConnection("discordapp.com", 443, timeout=10)
        conn.request("GET", f"/api/v9/channels/{cid}", body=None, headers={"authorization": token})
        resp = conn.getresponse()
        if 199 < resp.status < 300:
            channel_data = loads(resp.read().decode())
            channel_name = channel_data.get("name", "Unknown-Channel")
            guild_id = channel_data.get("guild_id")
            
            server_name = "Direct Message / Group"
            if guild_id:
                conn.request("GET", f"/api/v9/guilds/{guild_id}", body=None, headers={"authorization": token})
                g_resp = conn.getresponse()
                if 199 < g_resp.status < 300:
                    guild_data = loads(g_resp.read().decode())
                    server_name = guild_data.get("name", "Unknown Server")
            return server_name, channel_name
    except Exception:
        pass
    return None, None

# --- Application Configuration Wizards ---
def start_bot():
    global bot_run_cache
    console.clear()
    config = load_config()
    if not config or not config.get("Discord_Token"): 
        console.print("[bold red]Error: No Discord Token set![/bold red]")
        sleep(2)
        return
    tok = config['Discord_Token']
    shutdown_event.clear()
    channel_statuses.clear()
    
    bot_run_cache = {
        entry["name"]: {
            "channel_id": entry["channel_id"],
            "interval": f"{entry['messages'][0]['min_interval']}s-{entry['messages'][0]['max_interval']}s"
        } for entry in config.get('Config', [])
    }
    
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
    console.clear()
    config = load_config()
    tok = config.get("Discord_Token")
    
    if not tok or not tok.strip():
        console.print("[bold red]Error: Cannot add channels without a Discord Token. Please update your token first.[/bold red]")
        sleep(2)
        return
    
    cid = Prompt.ask("Channel ID (or 'c' to cancel)")
    if cid.lower() == 'c': return
    
    with console.status("[bold cyan]Fetching channel and server details...[/bold cyan]"):
        server_name, channel_name = fetch_channel_and_guild_info(cid, tok)
            
    if server_name and channel_name:
        console.print(f"[bold green]✓ Connected to Server: [yellow]{server_name}[/yellow] | Channel: [yellow]#{channel_name}[/yellow][/bold green]\n")
        default_name = channel_name
    else:
        console.print("[bold yellow]⚠ Could not fetch details automatically.[/bold yellow]\n")
        default_name = ""

    name = Prompt.ask("Nickname (or 'c' to cancel)", default=default_name)
    if name.lower() == 'c': return
    
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
    console.clear()
    config = load_config()
    new_token = Prompt.ask("Enter Discord Token (or 'c' to cancel)")
    if new_token.lower() == 'c': return
    config["Discord_Token"] = new_token
    save_config(config)

def edit_message_wizard():
    config = load_config()
    if not config or not config.get("Config"): 
        console.clear()
        console.print("[bold red]No channels found in the active profile! Please add a channel first.[/bold red]")
        sleep(2)
        return
        
    while True:
        console.clear()
        display_channel_content_table(config, "Select Channel to Edit Message")
        choice = Prompt.ask("Select ID, 'all', or 'c' to cancel")
        if choice.lower() == 'c': return
        if choice.lower() == 'all': break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(config["Config"]): break
            console.print(f"[bold red]Error: ID {choice} is out of range.[/bold red]")
            sleep(1)
        except ValueError:
            console.print(f"[bold red]Error: '{choice}' is not a valid ID.[/bold red]")
            sleep(1)

    new_msg = get_multiline_input("Enter new message")
    if new_msg.lower() == 'c': return
    if choice.lower() == 'all':
        for entry in config["Config"]: entry["messages"][0]["content"] = new_msg
    else:
        config["Config"][int(choice)-1]["messages"][0]["content"] = new_msg
    save_config(config)
    console.print("[bold green]Message updated successfully![/bold green]")
    sleep(1.5)

def interval_wizard():
    config = load_config()
    if not config or not config.get("Config"): 
        console.clear()
        console.print("[bold red]No channels found in the active profile! Please add a channel first.[/bold red]")
        sleep(2)
        return
        
    while True:
        console.clear()
        display_interval_table(config)
        choice = Prompt.ask("Select ID, 'all', or 'c' to cancel")
        if choice.lower() == 'c': return
        if choice.lower() == 'all' or (choice.isdigit() and 1 <= int(choice) <= len(config["Config"])):
            break
        console.print("[bold red]Invalid selection. Try again.[/bold red]")
        sleep(1)
    
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
    console.print("[bold green]Intervals updated successfully![/bold green]")
    sleep(1.5)

def delete_channel_wizard():
    config = load_config()
    if not config or not config.get("Config"): 
        console.clear()
        console.print("[bold red]No channels found in the active profile![/bold red]")
        sleep(2)
        return
        
    while True:
        console.clear()
        display_channel_content_table(config, "Select Channel to Delete")
        console.print("[dim]Use 'all' to delete ALL channels in this profile.[/dim]")
        choice = Prompt.ask("Select ID, 'all', or 'c' to cancel")
        if choice.lower() == 'c': return
        
        if choice.lower() == 'all':
            confirm = Prompt.ask("[bold red]Are you absolutely sure you want to delete ALL channels?[/bold red] (y/n)", choices=["y", "n"], default="n")
            if confirm.lower() == 'y':
                config["Config"] = []
                save_config(config)
                console.print("[bold green]All channels deleted.[/bold green]")
                sleep(1.5)
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(config["Config"]):
                target_name = config["Config"][idx]["name"]
                confirm = Prompt.ask(f"Delete '[bold red]{target_name}[/bold red]'? (y/n)", choices=["y", "n"], default="n")
                if confirm.lower() == 'y':
                    config["Config"].pop(idx)
                    save_config(config)
                    console.print(f"[bold green]Successfully deleted '{target_name}'.[/bold green]")
                    sleep(1.5)
                break
            else:
                console.print("[bold red]ID out of range.[/bold red]")
        except ValueError:
            console.print("[bold red]Please enter a valid number or 'all'.[/bold red]")
        sleep(1)

# --- Config Loadout Management Wizard ---
def profile_manager_wizard():
    while True:
        console.clear()
        active = get_active_profile_name()
        profiles = list_profiles()
        
        table = Table(title="Profile & Loadout Configuration Manager", header_style="bold magenta")
        table.add_column("ID", justify="center", style="cyan")
        table.add_column("Profile Name", style="green")
        table.add_column("Channels Connected", justify="center", style="blue")
        table.add_column("Discord Token State", style="white")
        table.add_column("Active", justify="center", style="magenta")
        
        for i, p in enumerate(profiles):
            status = "[bold yellow]●[/bold yellow]" if p == active else ""
            p_file = get_profile_filename(p)
            channels_count = "0"
            token_status = "[bold red]Missing[/bold red]"
            
            if os.path.exists(p_file):
                try:
                    with open(p_file, 'r') as f:
                        p_data = json.load(f)
                        channels_count = str(len(p_data.get("Config", [])))
                        tok = p_data.get("Discord_Token", "")
                        if tok and tok.strip():
                            token_status = f"[bold green]Configured[/bold green]"
                except Exception: pass
                
            table.add_row(str(i+1), p, channels_count, token_status, status)
            
        console.print(table)
        console.print("\n1. [bold green]Switch Profile[/bold green]\n2. [bold cyan]Create New[/bold cyan]\n3. [bold yellow]Rename[/bold yellow]\n4. [bold blue]Clone[/bold blue]\n5. [bold red]Delete Profile[/bold red]\n6. Go Back")
        choice = Prompt.ask("Action", choices=["1","2","3","4","5","6"])
        
        if choice == "1":
            idx_str = Prompt.ask("Switch to Profile ID")
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(profiles):
                    mgr = get_manager()
                    mgr["active_profile"] = profiles[idx]
                    save_manager(mgr)
            except (ValueError, IndexError): pass
        elif choice == "2":
            new_name = Prompt.ask("New Profile Name").strip()
            if not new_name: continue
            clean_name = "".join([c for c in new_name if c.isalnum() or c in ('-', '_')])
            filename = get_profile_filename(clean_name)
            if not os.path.exists(filename):
                with open(filename, 'w') as f:
                    json.dump({"Discord_Token": "", "Config": []}, f, indent=4)
        elif choice == "5":
            idx_str = Prompt.ask("Delete Profile ID")
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(profiles) and len(profiles) > 1:
                    del_name = profiles[idx]
                    os.remove(get_profile_filename(del_name))
                    if del_name == active:
                        mgr = get_manager()
                        mgr["active_profile"] = [p for p in profiles if p != del_name][0]
                        save_manager(mgr)
            except (ValueError, IndexError): pass
        elif choice == "6": break

# --- Utilities ---
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
    table = Table(title="Channel Intervals", header_style="bold magenta")
    table.add_column("ID", justify="center", style="cyan")
    table.add_column("Nickname", style="green")
    table.add_column("Channel ID", style="yellow")
    table.add_column("Interval Range", style="blue")
    table.add_column("Message Preview", style="dim white")
    for i, entry in enumerate(config["Config"]):
        m = entry["messages"][0]
        msg = m["content"]
        preview = (msg[:35] + '...') if len(msg) > 35 else msg
        table.add_row(str(i+1), entry["name"], entry["channel_id"], f"{m['min_interval']}s-{m['max_interval']}s", preview)
    console.print(table)

@app.command()
def main():
    init_profile_system()
    while True:
        console.clear()
        active_p = get_active_profile_name()
        display_title = f"Discord Automator | Active Loadout: [bold yellow]{active_p}[/bold yellow]"
        console.print(Panel.fit(BANNER, title=display_title, border_style="blue"))
        console.print("\n1. [bold green]Start Bot[/bold green]\n2. [bold cyan]Add New Channels[/bold cyan]\n3. [bold magenta]Update Discord Token[/bold magenta]\n4. [bold yellow]Edit Messages[/bold yellow]\n5. [bold blue]Change Intervals[/bold blue]\n6. [bold red]Delete Channels[/bold red]\n7. [bold white]Profile Manager[/bold white]\n8. Exit")
        c = Prompt.ask("Action", choices=["1","2","3","4","5","6","7","8"])
        if c == "1": start_bot()
        elif c == "2": setup_wizard()
        elif c == "3": update_token_wizard()
        elif c == "4": edit_message_wizard()
        elif c == "5": interval_wizard()
        elif c == "6": delete_channel_wizard()
        elif c == "7": profile_manager_wizard()
        elif c == "8": break

if __name__ == '__main__':
    app()
