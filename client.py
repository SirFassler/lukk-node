#!/usr/bin/env python3
"""
🛰️ LUKK-NODE CLI & WORKLOAD DISPATCHER
Remote control, hardware telemetry monitor, and delegated LLM inference dispatcher
for local GPU nodes running Ollama and NVIDIA GPUs.
Zero external dependencies (Python 3 standard library only).
Version: 1.2.0
"""

import sys
import os
import re
import json
import socket
import argparse
import urllib.request
import urllib.error
import time
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "lukk" / "tower.conf"

def load_tower_ip():
    """
    Loads configured IP with seamless auto-failover:
    Prefers ultra-low latency LAN IP (192.168.100.150) when at home.
    Automatically switches to Tailscale Mesh IP (100.105.89.3) when at INACAP or on mobile data.
    """
    lan_ip = ""
    ts_ip = ""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TOWER_IP="):
                        lan_ip = line.split("=", 1)[1].strip()
                    elif line.startswith("TOWER_TAILSCALE_IP="):
                        ts_ip = line.split("=", 1)[1].strip()
        except Exception:
            pass

    # Quick LAN heartbeat probe (250ms timeout)
    if lan_ip and lan_ip not in ("127.0.0.1", "localhost"):
        try:
            with socket.create_connection((lan_ip, 9876), timeout=0.25):
                return lan_ip
        except Exception:
            if ts_ip:
                return ts_ip

    return ts_ip or lan_ip or os.environ.get("LUKK_NODE_HOST", "127.0.0.1")

def save_tower_ip(ip: str):
    """Saves the target GPU node IP to local configuration, preserving other settings."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = []
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                existing_lines = [l.strip() for l in f if not l.strip().startswith("TOWER_IP=")]
        except Exception:
            pass
    existing_lines.append(f"TOWER_IP={ip}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines) + "\n")
    print(f"✅ Target node IP configured: {ip}")

def load_tower_mac() -> str:
    """Loads the configured MAC address of the target GPU node."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TOWER_MAC="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        except Exception:
            pass
    return os.environ.get("LUKK_NODE_MAC", "")

def save_tower_mac(mac: str):
    """Saves the target GPU node MAC to local configuration, preserving other settings."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = []
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                existing_lines = [l.strip() for l in f if not l.strip().startswith("TOWER_MAC=")]
        except Exception:
            pass
    existing_lines.append(f"TOWER_MAC={mac}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines) + "\n")
    print(f"✅ Target node MAC configured: {mac}")

def load_tower_token():
    """Loads the configured authentication token of the target GPU node."""
    token = os.environ.get("LUKK_NODE_TOKEN", "").strip()
    if token:
        return token
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TOKEN="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        except Exception:
            pass
    return ""

def save_tower_token(token: str):
    """Saves the authentication token to local configuration, preserving other settings."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = []
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                existing_lines = [l.strip() for l in f if not l.strip().startswith("TOKEN=")]
        except Exception:
            pass
    existing_lines.append(f"TOKEN={token}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines) + "\n")
    print(f"✅ Target node token configured (length: {len(token)} chars).")

def make_bar(percent, length=20):
    """Generates an ASCII progress bar."""
    percent = max(0.0, min(100.0, percent))
    filled = int(length * (percent / 100))
    bar = "█" * filled + "░" * (length - filled)
    return bar

def format_node_url(ip: str, path: str) -> str:
    """Formats the node URL handling custom ports gracefully."""
    ip = ip.strip()
    if ip.startswith("http://") or ip.startswith("https://"):
        base = ip.rstrip("/")
    else:
        if ":" in ip:
            base = f"http://{ip}"
        else:
            base = f"http://{ip}:9876"
    return f"{base}{path}"

def query_tower(ip, path, method="GET", data=None, token=None, timeout=6):
    """Executes an HTTP request to the remote satellite node with Bearer auth support."""
    url = format_node_url(ip, path)
    headers = {
        "User-Agent": "LukkNodeCLI/1.2",
        "Content-Type": "application/json"
    }
    auth_token = token or load_tower_token()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            return {"error": f"HTTP {e.code}: {err_body.get('error', e.reason)}"}
        except Exception:
            return {"error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Failed to connect to node ({url}): {e.reason}"}
    except Exception as e:
        return {"error": f"Unexpected communication error ({url}): {e}"}

def cmd_status(ip, token=None):
    """Displays comprehensive hardware telemetry and loaded model state."""
    res = query_tower(ip, "/telemetry", token=token)
    if "error" in res:
        print(f"\n❌ [CONNECTION ERROR] {res['error']}")
        print(f"👉 Ensure 'server.py' is running on target node ({ip}:9876).")
        print(f"👉 If authentication is enabled, run: lukk-tower set-token <TOKEN>")
        print(f"👉 To reconfigure the node IP run: lukk-tower set-ip <NODE_IP>\n")
        return

    node = res.get("node", "GPU-Node")
    gpu = res.get("gpu", {})
    ollama = res.get("ollama", {})

    print(f"\n========================================================")
    print(f"🖥️  REMOTE GPU TELEMETRY: {node.upper()} ({ip})")
    print(f"========================================================")

    if "error" in gpu:
        print(f"⚠️  GPU: {gpu['error']}")
    else:
        name = gpu.get("name", "NVIDIA GPU")
        temp = gpu.get("temperature_c", 0)
        power = gpu.get("power_draw_w", 0)
        gpu_pct = gpu.get("gpu_utilization_pct", 0)
        vram_used = gpu.get("vram_used_mb", 0) / 1024
        vram_total = gpu.get("vram_total_mb", 0) / 1024
        vram_pct = gpu.get("vram_used_pct", 0)

        print(f"🎮 GPU Device:     {name}")
        print(f"🌡️  Temperature:    {temp:.0f}°C")
        print(f"⚡ Power Draw:     {power:.1f} W")
        print(f"📊 Core Load:      [{make_bar(gpu_pct, 15)}] {gpu_pct:.1f}%")
        print(f"🧠 Memory (VRAM):  [{make_bar(vram_pct, 15)}] {vram_used:.2f} GB / {vram_total:.2f} GB ({vram_pct:.1f}%)")

    system = res.get("system", {})
    if system and "ram" in system:
        ram = system["ram"]
        total_gb = ram.get("total_mb", 0) / 1024
        used_gb = ram.get("used_mb", 0) / 1024
        avail_gb = ram.get("available_mb", 0) / 1024
        pct = ram.get("percent", 0)
        print(f"\n--------------------------------------------------------")
        print(f"🖲️  WINDOWS HOST RAM & TELEMETRÍA")
        print(f"--------------------------------------------------------")
        if total_gb > 0:
            print(f"💾 RAM Consumida:  [{make_bar(pct, 15)}] {used_gb:.2f} GB / {total_gb:.2f} GB ({pct:.1f}%)")
            print(f"   Memoria Libre:  {avail_gb:.2f} GB disponibles")
        if system.get("detected_game"):
            print(f"🎮 Juego Activo:   {system['detected_game']} (Gaming Mode Activo)")
        top_procs = system.get("top_processes", [])
        if top_procs:
            print(f"\n🔥 Top Subprocesos en Memoria:")
            for p in top_procs[:8]:
                inst = f"({p['instances']}x)" if p.get("instances", 1) > 1 else ""
                print(f"   • {p['name']:<24} {inst:<6} {p['mem_mb']:>7.1f} MB")

    print(f"\n--------------------------------------------------------")
    print(f"🤖 OLLAMA VRAM RESIDENCE STATE")
    print(f"--------------------------------------------------------")

    if not ollama.get("active"):
        print("⚠️  Ollama daemon not responding on remote node.")
    else:
        loaded = ollama.get("loaded_models", [])
        if not loaded:
            print("💤 No models currently residing in VRAM (0 MB AI consumption).")
        else:
            for m in loaded:
                print(f"🔥 Active Model:   {m['name']}")
                print(f"   VRAM Allocated: {m['size_vram_mb']:.1f} MB (Total: {m['size_total_mb']:.1f} MB)")
                print(f"   Eviction TTL:   {m.get('expires_at', 'standard')}")

    print(f"========================================================\n")

def cmd_models(ip, token=None):
    """Lists locally downloaded models on the remote node."""
    res = query_tower(ip, "/models", token=token)
    if "error" in res:
        print(f"❌ Error fetching models: {res['error']}")
        return
    models = res.get("models", [])
    print(f"\n📦 Models installed on target node ({ip}):")
    if not models:
        print("  (No models installed)")
    for m in models:
        print(f"  • {m['name']:<28} {m['size_gb']:>6.2f} GB  (Modified: {m.get('modified_at')[:10]})")
    print("")

def cmd_unload(ip, token=None):
    """Evicts all models from GPU VRAM to leave 100% memory for gaming."""
    print(f"⚡ Requesting instant VRAM eviction from {ip}...")
    res = query_tower(ip, "/unload", method="POST", data={}, token=token)
    if "error" in res:
        print(f"❌ Failed to evict models: {res['error']}")
        return
    details = res.get("details", {})
    unloaded = details.get("unloaded", [])
    if unloaded:
        print(f"✅ Evicted models from VRAM: {', '.join(unloaded)}")
    else:
        print("ℹ️ No active models were occupying VRAM.")

    gpu = res.get("gpu_after_unload", {})
    if "vram_free_mb" in gpu:
        free_gb = gpu["vram_free_mb"] / 1024
        total_gb = gpu["vram_total_mb"] / 1024
        print(f"🎮 Free VRAM: {free_gb:.2f} GB / {total_gb:.2f} GB ready for gaming.")
    else:
        print("🎮 VRAM cleared (0 MB AI overhead — GPU ready for gaming).")

def parse_github_ref(ref: str):
    """Parses a GitHub issue/PR URL or shorthand (e.g. owner/repo#123 or https://github.com/...)."""
    if not ref:
        return None
    m = re.search(r"github\.com/([^/\s]+)/([^/\s]+)/(issues|pull)/(\d+)", ref)
    if m:
        return m.group(1), m.group(2), m.group(3), int(m.group(4))
    m2 = re.search(r"^([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)#(\d+)$", ref.strip())
    if m2:
        return m2.group(1), m2.group(2), "issues", int(m2.group(3))
    return None

def fetch_github_post(owner: str, repo: str, kind: str, num: int) -> dict:
    """
    Fetches issue/PR description, state, labels, and relevant maintainer comments
    directly from GitHub REST API without external dependencies or tokens.
    """
    headers = {"User-Agent": "LukkCerberus/2.0"}
    issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{num}"
    req = urllib.request.Request(issue_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            issue = json.loads(r.read())
    except Exception as e:
        print(f"⚠️ [Cerberus GitHub] Failed to fetch {owner}/{repo}#{num}: {e}")
        return None

    comments = []
    comments_url = issue.get("comments_url")
    if comments_url and issue.get("comments", 0) > 0:
        req_c = urllib.request.Request(f"{comments_url}?per_page=6", headers=headers)
        try:
            with urllib.request.urlopen(req_c, timeout=10) as rc:
                comments_data = json.loads(rc.read())
                for c in comments_data:
                    user = c.get("user", {}).get("login", "")
                    if "bot" in user.lower() or user in ("codecov[bot]", "stale[bot]"):
                        continue
                    body = (c.get("body") or "").strip()
                    if body:
                        comments.append(f"**@{user}:**\n{body[:600]}")
        except Exception:
            pass

    return {
        "repo": f"{owner}/{repo}",
        "kind": kind,
        "number": num,
        "title": issue.get("title", ""),
        "state": issue.get("state", "open"),
        "author": issue.get("user", {}).get("login", ""),
        "labels": [l.get("name") for l in issue.get("labels", []) if isinstance(l, dict)],
        "body": issue.get("body") or "",
        "comments": comments
    }

def format_github_context(post_data: dict) -> str:
    """Formats raw GitHub post data into a structured context block for Cerberus."""
    if not post_data:
        return ""
    labels_str = ", ".join(post_data["labels"]) if post_data["labels"] else "None"
    comments_str = "\n\n".join(post_data["comments"]) if post_data["comments"] else "No external maintainer comments."
    return (
        f"### 🎯 TARGET GITHUB REPOSITORY: {post_data['repo']}\n"
        f"- Reference: {post_data['kind'].capitalize()} #{post_data['number']}\n"
        f"- Title: {post_data['title']}\n"
        f"- Author: @{post_data['author']}\n"
        f"- State: {post_data['state'].upper()} | Labels: {labels_str}\n\n"
        f"#### 📝 Issue Body / Problem Description:\n"
        f"```markdown\n{post_data['body']}\n```\n\n"
        f"#### 💬 Relevant Community & Maintainer Comments:\n"
        f"{comments_str}\n"
    )

def read_input_stream(prompt_arg: str = None, file_arg: str = None, github_arg: str = None) -> str:
    """
    Safely reads input from arguments, files, GitHub posts, or stdin pipes into an immutable buffer.
    Prevents double-read stalls and stream exhaustion on FIFOs/named pipes.
    Combines piped input with prompt instructions when both are provided.
    """
    piped_data = ""
    if not sys.stdin.isatty():
        try:
            piped_data = sys.stdin.read().strip()
        except Exception:
            piped_data = ""

    file_data = ""
    if file_arg:
        p = Path(file_arg)
        if not p.exists():
            print(f"❌ File not found: {file_arg}")
            return None
        file_data = p.read_text(encoding="utf-8", errors="replace")

    github_context = ""
    target_gh = github_arg
    if not target_gh and prompt_arg:
        gh_match = parse_github_ref(prompt_arg)
        if gh_match:
            target_gh = prompt_arg

    if target_gh:
        gh_parsed = parse_github_ref(target_gh)
        if gh_parsed:
            owner, repo, kind, num = gh_parsed
            print(f"🛰️ [Cerberus GitHub] Ingestando post remoto: {owner}/{repo}#{num}...")
            post_data = fetch_github_post(owner, repo, kind, num)
            if post_data:
                github_context = format_github_context(post_data)
                print(f"✅ Contexto GitHub incorporado: '{post_data['title']}' ({len(post_data['body'])} chars)")

    sections = []
    if github_context:
        sections.append(github_context)
    if file_data:
        sections.append(f"### Attached File ({Path(file_arg).name}):\n```\n{file_data}\n```")
    if piped_data:
        sections.append(f"### Piped Input:\n```\n{piped_data}\n```")
    if prompt_arg and prompt_arg != target_gh:
        sections.append(f"### Instruction:\n{prompt_arg}")
    elif prompt_arg == target_gh and not sections:
        sections.append(f"### Target Issue:\n{prompt_arg}")

    if not sections:
        return None

    return "\n\n".join(sections)

def dispatch_workload(
    prompt: str,
    ip: str = None,
    file_path: str = None,
    model: str = "qwen2.5-coder:7b",
    profile: str = "code",
    unload_after: bool = False,
    stream: bool = True,
    keep_alive: str = "1m",
    token: str = None,
    system: str = None
):
    """Dispatches delegated inference to the remote node with real-time streaming."""
    if not ip:
        ip = load_tower_ip()

    final_prompt = prompt
    if file_path:
        p = Path(file_path)
        if not p.exists():
            print(f"❌ File not found: {file_path}")
            return None
        content = p.read_text(encoding="utf-8", errors="replace")
        final_prompt = f"### File: {p.name}\n```\n{content}\n```\n\n### Instruction:\n{prompt}"

    payload = {
        "model": model,
        "prompt": final_prompt,
        "profile": profile,
        "stream": stream,
        "keep_alive": 0 if unload_after else keep_alive
    }
    if system:
        payload["system"] = system

    url = format_node_url(ip, "/infer")
    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LukkNodeDispatcher/1.2"
    }
    auth_token = token or load_tower_token()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    req = urllib.request.Request(url, data=req_data, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            print(f"\n❌ HTTP {e.code}: {err_body.get('error', e.reason)}")
        except Exception:
            print(f"\n❌ HTTP {e.code}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"\n❌ Failed to dispatch task to node ({url}): {e.reason}")
        print(f"Ensure target node ({ip}) has server.py and Ollama running.\n")
        return None

    if not stream:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        response_text = data.get("response", "")
        telemetry = data.get("telemetry", {})
        print(response_text)
        _print_badge(telemetry, model)
        return response_text

    # Live streaming mode
    eval_count = 0
    tps = 0.0
    meta = None
    collected_chunks = []
    try:
        for line in resp:
            if not line:
                continue
            try:
                chunk = json.loads(line.decode("utf-8"))
                if "response" in chunk:
                    sys.stdout.write(chunk["response"])
                    sys.stdout.flush()
                    collected_chunks.append(chunk["response"])
                if "lukk_telemetry" in chunk:
                    meta = chunk["lukk_telemetry"]
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\n[!] Stream interrupted by user.")
    print("")

    if meta:
        _print_badge(meta, model)

    return "".join(collected_chunks)

def _print_badge(telemetry, model):
    """Outputs execution metrics."""
    tps = telemetry.get("tokens_per_second", 0)
    dur = telemetry.get("total_duration_s", 0)
    count = telemetry.get("eval_count", 0)
    gpu_after = telemetry.get("gpu_after", {})
    temp = gpu_after.get("temperature_c", "-")
    power = gpu_after.get("power_draw_w", "-")

    print(f"\n⚡ [{model}] {count} tokens | {tps} tok/s | {dur}s | 🌡️ {temp}°C | 🔌 {power}W")

def cmd_bench(ip, model="qwen2.5-coder:7b", token=None):
    """Performs a token-throughput speed benchmark on the remote GPU."""
    print(f"\n🚀 Running throughput benchmark on {ip} with model '{model}'...")
    test_prompt = "Write a fast, non-blocking Python async TCP server with connection pooling. Include explanations."
    dispatch_workload(
        prompt=test_prompt,
        ip=ip,
        model=model,
        profile="code",
        unload_after=False,
        stream=True,
        keep_alive="5m",
        token=token
    )

def cmd_power(action: str, ip: str, token: str = None):
    """Sends a remote shutdown or sleep command to target node."""
    endpoint = f"/power/{action}"
    print(f"📡 Sending remote '{action}' instruction to target node ({ip})...")
    res = query_tower(ip, endpoint, method="POST", data={}, token=token)
    if "error" in res:
        print(f"❌ Failed to execute {action}: {res.get('error')}")
    else:
        print(f"🛑 {res.get('message', 'Command executed successfully.')}")

def cmd_wol(mac: str = None):
    """Broadcasts a Wake-on-LAN magic packet across the network to wake the node."""
    target_mac = mac or load_tower_mac()
    if not target_mac:
        print("❌ Error: No MAC address configured. Please run: lukk-tower set-mac <MAC>")
        return
    clean_mac = target_mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(clean_mac) != 12:
        print(f"❌ Error: Invalid MAC address format '{target_mac}'. Expected 12 hex digits.")
        return
    try:
        packet = bytes.fromhex("FF" * 6 + clean_mac * 16)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Send to standard broadcast and common subnet broadcast
            s.sendto(packet, ("255.255.255.255", 9))
            s.sendto(packet, ("192.168.100.255", 9))
        print(f"⚡ Wake-on-LAN magic packet broadcasted successfully to MAC: {target_mac}")
        print("⏳ Host hardware initiating power-on sequence. Check with 'lukk-tower ping' in ~10-15s.")
    except Exception as e:
        print(f"❌ Failed to dispatch WoL packet: {e}")

def ensure_tower_available(tower_ip: str, token: str = None, auto_wake: bool = False, wait_timeout: int = 40) -> str:
    """
    Verifies that the target node is online. If offline and auto_wake is enabled,
    broadcasts Wake-on-LAN magic packet and polls until operational.
    """
    try:
        with socket.create_connection((tower_ip, PORT), timeout=0.8):
            return tower_ip
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass

    if not auto_wake:
        return tower_ip

    print(f"📡 [Cerberus Autonomy] Nodo {tower_ip} no responde. Disparando Wake-on-LAN autónomo...")
    cmd_wol()
    start_time = time.time()
    while time.time() - start_time < wait_timeout:
        time.sleep(3)
        elapsed = int(time.time() - start_time)
        sys.stdout.write(f"\r⏳ [Cerberus Autonomy] Esperando inicialización del host ({elapsed}s/{wait_timeout}s)...")
        sys.stdout.flush()
        try:
            with socket.create_connection((tower_ip, PORT), timeout=0.8):
                res = query_tower(tower_ip, "/health", token=token)
                if res.get("status") == "ok":
                    print(f"\n✅ [Cerberus Autonomy] ¡Nodo {tower_ip} operativo y listo para inferencia!")
                    return tower_ip
        except Exception:
            pass

    print(f"\n⚠️ [Cerberus Autonomy] El nodo {tower_ip} no respondió tras {wait_timeout}s. Intentando despacho de todos modos.")
    return tower_ip

# ==============================================================================
# PROYECTO CERBERUS: 3-HEADED DYNAMIC SWARM ROUTER
# ==============================================================================

CERBERUS_TIERS = {
    "fast": {
        "model": "qwen2.5:1.5b",
        "name": "Cabeza I (Vigilancia / Fast)",
        "vram_est": "~0.98 GB",
        "description": "Ultra liviano, latencia <200ms, coexistencia total con gaming."
    },
    "code": {
        "model": "qwen2.5-coder:7b",
        "name": "Cabeza II (Táctica / Code)",
        "vram_est": "~4.36 GB",
        "description": "Ingeniería de software, refactoring, tests y syntax de alta precisión."
    },
    "deep": {
        "model": "deepseek-r1:7b",
        "name": "Cabeza III (Profunda / Deep Reasoning)",
        "vram_est": "~4.70 GB",
        "description": "Razonamiento analítico profundo paso a paso (Chain-of-Thought)."
    }
}

def classify_cerberus_tier(prompt: str, tower_ip: str = None, token: str = None) -> str:
    """
    Intelligent tier classifier for Proyecto Cerberus.
    Decides target model in <5ms using prompt semantics and live GPU hardware awareness.
    """
    p_lower = prompt.lower()

    # 1. Hardware Awareness: If GPU load on tower is heavy (> 70%), degrade elegantly to Fast
    if tower_ip:
        try:
            telemetry = query_tower(tower_ip, "/telemetry", token=token)
            gpu = telemetry.get("gpu", {})
            load = gpu.get("gpu_utilization_pct", 0)
            if load > 70.0:
                print(f"🎮 [Cerberus Hardware Sentinel] GPU bajo carga activa ({load}%). Despachando a Cabeza 1 (Fast) para proteger rendimiento.")
                return "fast"
        except Exception:
            pass

    # 2. Deep Reasoning Indicators
    deep_keywords = [
        "por qué", "analiza en profundidad", "razona", "evalúa la arquitectura",
        "root cause", "causa raíz", "teoría", "matemática", "demuestra",
        "proof", "audit", "vulnerabilidad", "exploit", "chain of thought", "cot",
        "seguridad ofensiva", "threat model", "modelo de amenazas"
    ]
    if any(k in p_lower for k in deep_keywords):
        return "deep"

    # 3. Code / Engineering Indicators
    code_keywords = [
        "def ", "class ", "function", "import ", "const ", "let ", "return ",
        "traceback", "exception", "syntaxerror", "indexerror", "nullpointer",
        "sql", "select ", "insert ", "update ", "delete from", "dockerfile",
        "cmake", "cargo", "rust", "python", "typescript", "c++", "bash", "script",
        "refactor", "bug", "fix", "patch", "pull request", "pr ", "endpoint", "api"
    ]
    if any(k in p_lower for k in code_keywords) or len(prompt) > 800:
        return "code"

    # 4. Short queries / General Chat -> Fast
    return "fast"

def cmd_pull(tower_ip: str, model_name: str, token: str = None):
    """Pulls an Ollama model onto the remote tower node with live progress."""
    print(f"📥 Dispatching pull request to node {tower_ip} for model '{model_name}'...")
    url = f"http://{tower_ip}:{PORT}/pull"
    payload = json.dumps({"name": model_name}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            last_status = ""
            for line in resp:
                if not line:
                    continue
                try:
                    data = json.loads(line.decode("utf-8"))
                    status = data.get("status", "")
                    total = data.get("total", 0)
                    completed = data.get("completed", 0)
                    if total > 0:
                        pct = (completed / total) * 100
                        mb_done = completed / (1024 * 1024)
                        mb_tot = total / (1024 * 1024)
                        sys.stdout.write(f"\r📦 {status}: {mb_done:.1f}MB / {mb_tot:.1f}MB ({pct:.1f}%)   ")
                        sys.stdout.flush()
                    elif status != last_status:
                        print(f"📦 {status}")
                        last_status = status
                except Exception:
                    pass
        print(f"\n✅ Model '{model_name}' successfully installed and ready on {tower_ip}!")
    except Exception as e:
        print(f"\n❌ Pull failed: {e}")

def cmd_cerberus_status(tower_ip: str, token: str = None):
    """Displays the status and readiness of all 3 heads of Cerberus."""
    installed = query_tower(tower_ip, "/models", token=token)
    models = [m.get("name", "") for m in installed.get("models", [])]
    
    print("==========================================================")
    print("🐉  PROYECTO CERBERUS: ESTADO DEL ENJAMBRE DE 3 CABEZAS")
    print(f"📡  Nodo: {tower_ip} (NVIDIA RTX 3060 8GB)")
    print("==========================================================")
    
    for key, info in CERBERUS_TIERS.items():
        target = info["model"]
        ready = any(m == target or m.startswith(target) for m in models)
        icon = "🟢 LISTA" if ready else f"🔴 NO INSTALADA (Descargar con: lukk-tower pull {target})"
        print(f"\n* {info['name']}: {icon}")
        print(f"  • Modelo Target: {info['model']}")
        print(f"  • Huella VRAM:   {info['vram_est']}")
        print(f"  • Misión:        {info['description']}")
    print("==========================================================")

CERBERUS_SYSTEM_PROMPTS = {
    "fast": (
        "Eres Cabeza I de Cerberus (Orthrus / Fast), forjado por Rodrigo (Fassler) y Lukk. "
        "Operas en la GPU local NVIDIA RTX 3060. "
        "Eres un vigilante veloz, conciso y directo. Cero rodeos, cero disculpas, cero servilismo corporativo. "
        "Tu misión es entregar telemetría y respuestas inmediatas con rigor técnico."
    ),
    "code": (
        "Eres Cabeza II de Cerberus (Nemea / Coder), forjado por Rodrigo (Fassler) y Lukk. "
        "Operas en la GPU local NVIDIA RTX 3060. "
        "Eres un cirujano de código implacable. Escribe código de producción modular, fuertemente tipado, con tests unitarios y sin efectos secundarios. "
        "Cero explicaciones redundantes o disculpas. Ve directo a la solución de ingeniería."
    ),
    "deep": (
        "Eres Cabeza III de Cerberus (Typhon / Deep), forjado por Rodrigo (Fassler) y Lukk. "
        "Operas en la GPU local NVIDIA RTX 3060. "
        "Eres el auditor y razonador abisal. Analiza paso a paso (<think>), encuentra causas raíz ocultas, "
        "memory leaks, condiciones de carrera y vulnerabilidades de seguridad. Sé implacable y analítico."
    )
}

def cmd_cerberus(prompt: str, tower_ip: str, tier: str = "auto", profile: str = "code", unload: bool = False, keep_alive: str = "1m", token: str = None, stream: bool = True):
    """Orchestrates multi-headed inference dispatch for Proyecto Cerberus."""
    selected_tier = tier
    if selected_tier == "auto":
        selected_tier = classify_cerberus_tier(prompt, tower_ip=tower_ip, token=token)

    tier_info = CERBERUS_TIERS.get(selected_tier, CERBERUS_TIERS["code"])
    target_model = tier_info["model"]

    # Map tier to dedicated Cerberus profile if not explicitly overridden
    if profile == "code":
        tier_profile_map = {"fast": "chat", "code": "code", "deep": "review"}
        profile = tier_profile_map.get(selected_tier, "cerberus")

    print(f"🐉 [PROYECTO CERBERUS] Activando: {tier_info['name']}")
    print(f"🧠 Modelo: {target_model} | VRAM: {tier_info['vram_est']} | Perfil: {profile.upper()} | Modo: {selected_tier.upper()}")
    
    eta_map = {
        "fast": "~2 a 5 segundos (alta velocidad)",
        "code": "~6 a 12 segundos (arranque en frío: ~15s)",
        "deep": "~20 a 45 segundos (razonamiento abisal paso a paso)"
    }
    eta_str = eta_map.get(selected_tier, "~8 a 15 segundos")
    print(f"⏱️  Tiempo estimado: {eta_str}")
    print("-" * 60)

    dispatch_workload(
        prompt=prompt,
        ip=tower_ip,
        file_path=None,
        model=target_model,
        profile=profile,
        unload_after=unload,
        stream=stream,
        keep_alive=keep_alive,
        token=token,
        system=CERBERUS_SYSTEM_PROMPTS.get(selected_tier, CERBERUS_SYSTEM_PROMPTS["fast"])
    )

def cmd_cerberus_pipeline(
    task_input: str,
    tower_ip: str,
    github_url: str = None,
    token: str = None,
    unload: bool = False,
    output_path: str = None
):
    """
    Autonomous 3-headed pipeline for complex GitHub issues or deep engineering problems:
    1. Cabeza I (Fast - 1.5B): Triage, tech stack, and feasibility score.
    2. Cabeza III (Deep - DeepSeek-R1): Root Cause Analysis, logic failure mode, and threat model.
    3. Cabeza II (Code - Qwen 2.5 Coder 7B): Solution patch synthesis & reproduction unit tests.
    """
    task_context = task_input
    target_gh = github_url
    if not target_gh:
        gh_match = parse_github_ref(task_input)
        if gh_match:
            target_gh = task_input

    target_ref_name = "issue"
    if target_gh:
        gh_parsed = parse_github_ref(target_gh)
        if gh_parsed:
            owner, repo, kind, num = gh_parsed
            target_ref_name = f"{owner}_{repo}_{num}"
            print(f"🛰️ [Pipeline Cerberus] Ingestando contexto GitHub: {owner}/{repo}#{num}...")
            post_data = fetch_github_post(owner, repo, kind, num)
            if post_data:
                task_context = format_github_context(post_data)

    print("=" * 70)
    print("🐉  PROYECTO CERBERUS: PIPELINE AUTÓNOMO DE 3 CABEZAS")
    print(f"📡  Nodo GPU: {tower_ip} (NVIDIA GeForce RTX 3060 8GB)")
    print("=" * 70)

    # FASE 1: Cabeza I (Orthrus / Fast) - Triaje & Factibilidad
    print("\n🟢 [FASE 1/3] Cabeza I (Orthrus / Fast 1.5B): Triaje Técnico & Factibilidad...")
    p1 = (
        "Analiza este issue o problema técnico de forma directa y sintética:\n"
        "1. Lenguaje y Stack tecnológico involucrado.\n"
        "2. Resumen del problema en 2 oraciones.\n"
        "3. Dificultad estimada (Baja / Media / Alta / Crítica).\n"
        "4. Índice de Factibilidad para resolver mediante PR (1 a 10) y justificación.\n\n"
        f"{task_context}"
    )
    triage_output = dispatch_workload(
        prompt=p1, ip=tower_ip, model=CERBERUS_TIERS["fast"]["model"],
        profile="chat", stream=True, keep_alive="3m", token=token,
        system=CERBERUS_SYSTEM_PROMPTS["fast"]
    ) or ""

    # FASE 2: Cabeza III (Typhon / Deep) - Análisis Forense & Causa Raíz
    print("\n🟣 [FASE 2/3] Cabeza III (Typhon / DeepSeek-R1 7B): Auditoría Forense & Causa Raíz (RCA)...")
    p2 = (
        "Eres el auditor abisal. Realiza un Análisis de Causa Raíz (RCA) riguroso sobre este issue.\n"
        "Analiza paso a paso (<think>):\n"
        "- Identifica la causa raíz exacta del fallo o comportamiento erróneo (parsing, asincronía, gestión de memoria, tipos o diseño).\n"
        "- Explica el mecanismo exacto del fallo.\n"
        "- Define el enfoque quirúrgico de mitigación sin romper contratos existentes ni introducir regresiones.\n\n"
        f"### Contexto Técnico:\n{task_context}\n\n"
        f"### Triaje Preliminar:\n{triage_output}"
    )
    rca_output = dispatch_workload(
        prompt=p2, ip=tower_ip, model=CERBERUS_TIERS["deep"]["model"],
        profile="review", stream=True, keep_alive="3m", token=token,
        system=CERBERUS_SYSTEM_PROMPTS["deep"]
    ) or ""

    # FASE 3: Cabeza II (Nemea / Coder) - Síntesis de Parche & Test de Regresión
    print("\n🔵 [FASE 3/3] Cabeza II (Nemea / Qwen 2.5 Coder 7B): Síntesis de Parche & Tests...")
    p3 = (
        "Eres el cirujano de código. Basado en el issue y el análisis de causa raíz previo, sintetiza la solución de ingeniería:\n"
        "1. Escribe la prueba unitaria de regresión (que debe fallar antes del parche y pasar después con aserciones estrictas).\n"
        "2. Escribe el parche quirúrgico de código de producción (modular, fuertemente tipado, sin efectos secundarios).\n"
        "Cero explicaciones redundantes o disculpas. Ve directo al código y tests.\n\n"
        f"### Contexto Técnico:\n{task_context}\n\n"
        f"### Causa Raíz Identificada:\n{rca_output}"
    )
    code_output = dispatch_workload(
        prompt=p3, ip=tower_ip, model=CERBERUS_TIERS["code"]["model"],
        profile="code", unload_after=unload, stream=True, keep_alive="1m", token=token,
        system=CERBERUS_SYSTEM_PROMPTS["code"]
    ) or ""

    # Generar Dossier Final en Markdown
    report = (
        f"# 🐉 Dossier Autónomo Cerberus - Análisis de Issue\n\n"
        f"* **Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"* **Nodo Ejecutor:** {tower_ip} (NVIDIA GeForce RTX 3060 8GB)\n"
        f"* **Objetivo:** `{target_ref_name}`\n\n"
        f"---\n\n"
        f"## 1. Triaje Técnico & Factibilidad (Cabeza I - Orthrus 1.5B)\n\n"
        f"{triage_output}\n\n"
        f"---\n\n"
        f"## 2. Auditoría Forense & Causa Raíz (Cabeza III - DeepSeek-R1 7B)\n\n"
        f"{rca_output}\n\n"
        f"---\n\n"
        f"## 3. Síntesis de Parche & Tests de Regresión (Cabeza II - Qwen 2.5 Coder 7B)\n\n"
        f"{code_output}\n"
    )

    save_dest = output_path
    if not save_dest:
        obsidian_dir = Path.home() / "ObsidianVault" / "300 Notes" / "Cerberus"
        obsidian_dir.mkdir(parents=True, exist_ok=True)
        date_stamp = datetime.now().strftime("%y%m%d_%H%M%S")
        clean_target = re.sub(r"[^a-zA-Z0-9_-]", "_", target_ref_name)
        save_dest = str(obsidian_dir / f"cerberus_{clean_target}_{date_stamp}.md")

    try:
        Path(save_dest).write_text(report, encoding="utf-8")
        print(f"\n📄 Dossier técnico archivado en Obsidian:\n   file://{save_dest}")
        # Enlazar en ~/.agents/reports/ para acceso rápido de scripts
        reports_dir = Path.home() / ".agents" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        link_dest = reports_dir / Path(save_dest).name
        if not link_dest.exists():
            try:
                link_dest.symlink_to(save_dest)
            except Exception:
                pass
    except Exception as e:
        print(f"\n⚠️ No se pudo guardar el informe en '{save_dest}': {e}")

    return report

def main():
    parser = argparse.ArgumentParser(description="LUKK-NODE CLI: Remote NVIDIA GPU Telemetry & Local LLM Orchestrator")
    parser.add_argument("--ip", default=None, help="Override node IP address")
    parser.add_argument("--token", default=None, help="Override Bearer authentication token")

    subparsers = parser.add_subparsers(dest="subcommand", help="Operational subcommands")

    # set-ip
    p_set_ip = subparsers.add_parser("set-ip", help="Set default target GPU node IP address")
    p_set_ip.add_argument("ip_address", help="Target node IP (e.g. 192.168.100.X or Tailscale IP)")

    # set-token
    p_set_token = subparsers.add_parser("set-token", help="Set authentication token for target node")
    p_set_token.add_argument("token_string", help="Bearer authentication token")

    # set-mac
    p_set_mac = subparsers.add_parser("set-mac", help="Set hardware MAC address for Wake-on-LAN")
    p_set_mac.add_argument("mac_address", help="Target node MAC address (e.g. 9c:6b:00:a0:42:89)")

    # wake / wol
    for wake_cmd in ("wake", "wol"):
        p_wake = subparsers.add_parser(wake_cmd, help="Wake remote node via Wake-on-LAN magic packet")
        p_wake.add_argument("--mac", default=None, help="Override target node MAC address")

    # shutdown
    p_shutdown = subparsers.add_parser("shutdown", help="Send remote power-off command to host machine")
    p_shutdown.add_argument("--ip", default=None, help="Override node IP address")

    # sleep / suspend
    for sleep_cmd in ("sleep", "suspend"):
        p_sleep = subparsers.add_parser(sleep_cmd, help="Send remote sleep/suspend command to host machine")
        p_sleep.add_argument("--ip", default=None, help="Override node IP address")

    # status
    p_status = subparsers.add_parser("status", help="Show remote GPU and Ollama hardware telemetry HUD")
    p_status.add_argument("--ip", default=None, help="Override node IP address")

    # ping
    p_ping = subparsers.add_parser("ping", help="Check remote node health and connectivity")
    p_ping.add_argument("--ip", default=None, help="Override node IP address")

    # models
    p_models = subparsers.add_parser("models", help="List installed models on remote node")
    p_models.add_argument("--ip", default=None, help="Override node IP address")

    # unload
    p_unload = subparsers.add_parser("unload", help="Force immediate eviction of all models from VRAM (Zero-VRAM Gaming Mode)")
    p_unload.add_argument("--ip", default=None, help="Override node IP address")

    # bench
    p_bench = subparsers.add_parser("bench", help="Run token-throughput and latency benchmark on GPU")
    p_bench.add_argument("--model", "-m", default="qwen2.5-coder:7b", help="Model identifier to evaluate")
    p_bench.add_argument("--ip", default=None, help="Override node IP address")

    # pull
    p_pull = subparsers.add_parser("pull", help="Download an Ollama model to the remote GPU node with live progress")
    p_pull.add_argument("model_name", help="Model name and tag to pull (e.g. qwen2.5:1.5b, deepseek-r1:7b)")
    p_pull.add_argument("--ip", default=None, help="Override node IP address")

    # cerberus / cb
    for cb_alias in ("cerberus", "cb"):
        p_cb = subparsers.add_parser(cb_alias, help="Dispatch inference through the 3-headed Cerberus swarm router")
        p_cb.add_argument("prompt", nargs="?", default=None, help="Prompt or task instruction")
        p_cb.add_argument("-t", "--tier", choices=["auto", "fast", "code", "deep"], default="auto",
                          help="Swarm tier: fast (1.5B), code (7B coder), deep (7B reasoning), or auto-classifier")
        p_cb.add_argument("-g", "--github", default=None, help="GitHub Issue/PR URL or shorthand (e.g. owner/repo#123)")
        p_cb.add_argument("--pipeline", action="store_true", help="Execute 3-headed autonomous pipeline (Triage -> RCA -> Code)")
        p_cb.add_argument("-w", "--wake", action="store_true", help="Auto-wake remote GPU node via Wake-on-LAN if offline")
        p_cb.add_argument("-o", "--output", default=None, help="Save final technical dossier to file")
        p_cb.add_argument("-s", "--status", action="store_true", help="Display Cerberus 3-headed swarm readiness HUD")
        p_cb.add_argument("-f", "--file", default=None, help="Attach local file context")
        p_cb.add_argument("-p", "--profile", choices=["code", "review", "chat", "raw"], default="code", help="System profile")
        p_cb.add_argument("-u", "--unload", action="store_true", help="Evict VRAM immediately after completion")
        p_cb.add_argument("-k", "--keep-alive", default="1m", help="VRAM retention time")
        p_cb.add_argument("--no-stream", action="store_true", help="Disable live streaming output")
        p_cb.add_argument("--ip", default=None, help="Override node IP address")

    # update
    p_update = subparsers.add_parser("update", help="Command remote node to git pull and restart daemon seamlessly")
    p_update.add_argument("--ip", default=None, help="Override node IP address")

    # run / infer / ask
    for name in ("run", "infer", "ask"):
        p_run = subparsers.add_parser(name, help="Dispatch delegated LLM inference to remote node")
        p_run.add_argument("prompt", nargs="?", default=None, help="Instruction or prompt")
        p_run.add_argument("-f", "--file", default=None, help="Path to local file to attach as context")
        p_run.add_argument("-g", "--github", default=None, help="GitHub Issue/PR URL or shorthand")
        p_run.add_argument("-w", "--wake", action="store_true", help="Auto-wake remote GPU node if offline")
        p_run.add_argument("-m", "--model", default="qwen2.5-coder:7b", help="Model identifier on node")
        p_run.add_argument("-t", "--tier", choices=["auto", "fast", "code", "deep"], default=None,
                           help="Optional Cerberus tier override")
        p_run.add_argument("-p", "--profile", choices=["code", "review", "chat", "raw"], default="code", help="Agent system profile")
        p_run.add_argument("-u", "--unload", action="store_true", help="Evict VRAM immediately after completion (gaming safe)")
        p_run.add_argument("-k", "--keep-alive", default="1m", help="VRAM retention time (e.g. 1m, 5m, 0)")
        p_run.add_argument("--no-stream", action="store_true", help="Disable live streaming output")
        p_run.add_argument("--ip", default=None, help="Override node IP address")

    args = parser.parse_args()

    if not args.subcommand:
        cmd_status(load_tower_ip(), token=args.token)
        return

    if args.subcommand == "set-ip":
        save_tower_ip(args.ip_address)
        return

    if args.subcommand == "set-token":
        save_tower_token(args.token_string)
        return

    if args.subcommand == "set-mac":
        save_tower_mac(args.mac_address)
        return

    if args.subcommand in ("wake", "wol"):
        cmd_wol(getattr(args, "mac", None))
        return

    tower_ip = getattr(args, "ip", None) or args.ip or load_tower_ip()
    token = args.token or load_tower_token()

    if args.subcommand == "shutdown":
        cmd_power("shutdown", tower_ip, token=token)
        return

    if args.subcommand in ("sleep", "suspend"):
        cmd_power("sleep", tower_ip, token=token)
        return

    if args.subcommand == "status":
        cmd_status(tower_ip, token=token)
    elif args.subcommand == "ping":
        res = query_tower(tower_ip, "/health", token=token)
        if "error" in res:
            print(f"❌ Connection error: {res['error']}")
        else:
            auth_str = " (Auth: Required)" if res.get("authenticated") else " (Auth: None)"
            print(f"✅ Node online: {res.get('node')} (status: {res.get('status')}, ver: {res.get('version')}){auth_str}")
    elif args.subcommand == "pull":
        cmd_pull(tower_ip, args.model_name, token=token)
    elif args.subcommand == "update":
        res = query_tower(tower_ip, "/update", method="POST", data={}, token=token)
        print(f"📡 Update status: {res.get('message', res)}")
    elif args.subcommand in ("cerberus", "cb"):
        has_gh = bool(getattr(args, "github", None))
        if getattr(args, "status", False) or (not args.prompt and not has_gh):
            cmd_cerberus_status(tower_ip, token=token)
            return

        if getattr(args, "wake", False):
            tower_ip = ensure_tower_available(tower_ip, token=token, auto_wake=True)

        prompt_text = read_input_stream(
            prompt_arg=args.prompt,
            file_arg=args.file,
            github_arg=getattr(args, "github", None)
        )
        if not prompt_text:
            cmd_cerberus_status(tower_ip, token=token)
            return

        if getattr(args, "pipeline", False):
            cmd_cerberus_pipeline(
                task_input=prompt_text,
                tower_ip=tower_ip,
                github_url=getattr(args, "github", None),
                token=token,
                unload=args.unload,
                output_path=getattr(args, "output", None)
            )
            return

        cmd_cerberus(
            prompt=prompt_text,
            tower_ip=tower_ip,
            tier=args.tier,
            profile=args.profile,
            unload=args.unload,
            keep_alive=args.keep_alive,
            token=token,
            stream=not args.no_stream
        )
    elif args.subcommand == "models":
        cmd_models(tower_ip, token=token)
    elif args.subcommand == "unload":
        cmd_unload(tower_ip, token=token)
    elif args.subcommand == "bench":
        cmd_bench(tower_ip, model=args.model, token=token)
    elif args.subcommand in ("run", "infer", "ask"):
        if getattr(args, "wake", False):
            tower_ip = ensure_tower_available(tower_ip, token=token, auto_wake=True)

        prompt_text = read_input_stream(
            prompt_arg=args.prompt,
            file_arg=args.file,
            github_arg=getattr(args, "github", None)
        )
        if not prompt_text:
            print("❌ Missing prompt or piped input. Usage: lukk-tower run \"Prompt...\" or 'cat file | lukk-tower run'")
            sys.exit(1)

        # If --tier is specified, route through Cerberus
        if getattr(args, "tier", None):
            cmd_cerberus(
                prompt=prompt_text,
                tower_ip=tower_ip,
                tier=args.tier,
                profile=args.profile,
                unload=args.unload,
                keep_alive=args.keep_alive,
                token=token,
                stream=not args.no_stream
            )
            return

        dispatch_workload(
            prompt=prompt_text,
            ip=tower_ip,
            file_path=None,
            model=args.model,
            profile=args.profile,
            unload_after=args.unload,
            stream=not args.no_stream,
            keep_alive=args.keep_alive,
            token=token
        )

if __name__ == "__main__":
    main()
