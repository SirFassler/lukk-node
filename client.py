#!/usr/bin/env python3
"""
🛰️ LUKK-NODE CLI & WORKLOAD DISPATCHER
Remote control, hardware telemetry monitor, and delegated LLM inference dispatcher
for local GPU nodes running Ollama and NVIDIA GPUs.
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
import time
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "lukk" / "tower.conf"

def load_tower_ip():
    """Loads the configured IP address of the target GPU node."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TOWER_IP="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        except Exception:
            pass
    return os.environ.get("LUKK_NODE_HOST", "127.0.0.1")

def save_tower_ip(ip: str):
    """Saves the target GPU node IP to local configuration."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(f"TOWER_IP={ip}\n")
    print(f"✅ Target node IP configured: {ip}")

def make_bar(percent, length=20):
    """Generates an ASCII progress bar."""
    percent = max(0.0, min(100.0, percent))
    filled = int(length * (percent / 100))
    bar = "█" * filled + "░" * (length - filled)
    return bar

def query_tower(ip, path, method="GET", data=None, timeout=6):
    """Executes an HTTP request to the remote satellite node."""
    url = f"http://{ip}:9876{path}"
    headers = {"User-Agent": "LukkNodeCLI/1.1", "Content-Type": "application/json"}
    req_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"error": f"Failed to connect to node ({url}): {e.reason}"}
    except Exception as e:
        return {"error": f"Unexpected communication error ({url}): {e}"}

def cmd_status(ip):
    """Displays comprehensive hardware telemetry and loaded model state."""
    res = query_tower(ip, "/telemetry")
    if "error" in res:
        print(f"\n❌ [CONNECTION ERROR] {res['error']}")
        print(f"👉 Ensure 'server.py' is running on target node ({ip}:9876).")
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

    print(f"\n--------------------------------------------------------")
    print(f"🤖 OLLAMA VRAM RESIDENCE STATE")
    print(f"--------------------------------------------------------")

    if not ollama.get("active"):
        print("⚪ Ollama Runtime: Offline or unreachable on node.")
    else:
        loaded = ollama.get("loaded_models", [])
        if not loaded:
            print("🟢 100% VRAM FREE (Gaming Mode Active — 0 models resident in VRAM).")
        else:
            for m in loaded:
                print(f"🟣 Active Model in VRAM: {m['name']} (Allocated: {m['size_vram_mb']} MB VRAM)")
    print(f"========================================================\n")

def cmd_models(ip):
    """Lists locally downloaded models in the node's storage."""
    res = query_tower(ip, "/models")
    if "error" in res:
        print(f"❌ Error querying models: {res['error']}")
        return

    models = res.get("models", [])
    print(f"\n📦 AVAILABLE MODELS ON NODE ({ip}):")
    print("-" * 55)
    if not models:
        print("⚪ No downloaded models found in Ollama storage.")
        print("💡 Download recommended model by running on the node:")
        print("   ollama pull qwen2.5-coder:7b")
    else:
        for m in models:
            print(f"  • {m['name']:<28} | {m.get('size_gb', 0):>5.2f} GB")
    print("-" * 55 + "\n")

def cmd_unload(ip):
    """Immediately evicts all resident models from VRAM for gaming."""
    print(f"⚡ Requesting immediate VRAM purge on node ({ip})...")
    res = query_tower(ip, "/unload", method="POST")
    if "error" in res:
        print(f"❌ Error: {res['error']}")
    else:
        print("✅ Models evicted successfully:")
        for u in res.get("details", {}).get("unloaded", []):
            print(f"   - {u}")
        print("🎮 VRAM cleared (0 MB AI overhead — GPU ready for gaming).")

def read_input_stream(prompt_arg: str = None, file_arg: str = None) -> str:
    """
    Safely reads input from arguments, files, or stdin pipes into an immutable buffer.
    Prevents double-read stalls and stream exhaustion on FIFOs/named pipes.
    Combines piped input with prompt instructions when both are provided.
    """
    piped_data = ""
    # Check if data is being piped into stdin without blocking if terminal is interactive
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

    # Combine sources intelligently
    sections = []
    if file_data:
        sections.append(f"### Attached File ({Path(file_arg).name}):\n```\n{file_data}\n```")
    if piped_data:
        sections.append(f"### Piped Input:\n```\n{piped_data}\n```")
    if prompt_arg:
        sections.append(f"### Instruction:\n{prompt_arg}")

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
    keep_alive: str = "1m"
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

    url = f"http://{ip}:9876/infer"
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json", "User-Agent": "LukkNodeDispatcher/1.1"}
    )

    try:
        resp = urllib.request.urlopen(req, timeout=180)
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

    # Real-time streaming
    eval_count = 0
    meta = {}

    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue

            if "response" in chunk:
                sys.stdout.write(chunk["response"])
                sys.stdout.flush()

            if "lukk_telemetry" in chunk:
                meta = chunk["lukk_telemetry"]
    except KeyboardInterrupt:
        print("\n\n[!] Inference interrupted by operator.")
        return None

    print("\n")
    if meta:
        _print_badge(meta, model)
    elif unload_after:
        cmd_unload(ip)

def _print_badge(meta, model):
    """Prints a clean performance summary badge upon generation completion."""
    tps = meta.get("tokens_per_second", 0)
    tokens = meta.get("eval_count", 0)
    duration = meta.get("total_duration_s", 0)
    gpu = meta.get("gpu_after", {})
    vram_used = (gpu.get("vram_used_mb", 0) / 1024) if "vram_used_mb" in gpu else 0
    vram_tot = (gpu.get("vram_total_mb", 0) / 1024) if "vram_total_mb" in gpu else 8.0
    temp = gpu.get("temperature_c", 0) if "temperature_c" in gpu else 0

    badge = (
        f"⚡ [{tps:.1f} tok/s | {tokens} tokens | {duration:.1f}s | "
        f"VRAM: {vram_used:.1f}GB/{vram_tot:.1f}GB | {temp:.0f}°C | {model}]"
    )
    print(badge)

def cmd_bench(ip, model="qwen2.5-coder:7b"):
    """Runs a throughput and latency benchmark on the target GPU node."""
    print(f"\n🚀 EXECUTING THROUGHPUT BENCHMARK ON NODE ({ip}) WITH {model}...")
    bench_prompt = (
        "Implement an optimized binary search algorithm and a quicksort routine "
        "in Python with full type annotations and concise docstrings."
    )
    dispatch_workload(
        prompt=bench_prompt,
        ip=ip,
        model=model,
        profile="code",
        unload_after=False,
        stream=True
    )
    print("\n✅ Benchmark completed.\n")

def main():
    parser = argparse.ArgumentParser(description="Lukk-Node CLI & Remote LLM Workload Dispatcher")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # status
    p_status = subparsers.add_parser("status", help="Display real-time hardware telemetry of target node")
    p_status.add_argument("--ip", default=None, help="Override node IP address")

    # ping
    p_ping = subparsers.add_parser("ping", help="Verify network reachability of target node")
    p_ping.add_argument("--ip", default=None, help="Override node IP address")

    # set-ip
    p_setip = subparsers.add_parser("set-ip", help="Configure target node IP address")
    p_setip.add_argument("ip_address", help="Target node IP address (e.g., 192.168.1.50)")

    # models
    p_models = subparsers.add_parser("models", help="List downloaded models in Ollama storage")
    p_models.add_argument("--ip", default=None, help="Override node IP address")

    # unload
    p_unload = subparsers.add_parser("unload", help="Evict resident models from VRAM for gaming")
    p_unload.add_argument("--ip", default=None, help="Override node IP address")

    # bench
    p_bench = subparsers.add_parser("bench", help="Run token-throughput and latency benchmark on GPU")
    p_bench.add_argument("--model", "-m", default="qwen2.5-coder:7b", help="Model identifier to evaluate")
    p_bench.add_argument("--ip", default=None, help="Override node IP address")

    # run / infer / ask
    for name in ("run", "infer", "ask"):
        p_run = subparsers.add_parser(name, help="Dispatch delegated LLM inference to remote node")
        p_run.add_argument("prompt", nargs="?", default=None, help="Instruction or prompt")
        p_run.add_argument("-f", "--file", default=None, help="Path to local file to attach as context")
        p_run.add_argument("-m", "--model", default="qwen2.5-coder:7b", help="Model identifier on node")
        p_run.add_argument("-p", "--profile", choices=["code", "review", "chat", "raw"], default="code", help="Agent system profile")
        p_run.add_argument("-u", "--unload", action="store_true", help="Evict VRAM immediately after completion (gaming safe)")
        p_run.add_argument("-k", "--keep-alive", default="1m", help="VRAM retention time (e.g. 1m, 5m, 0)")
        p_run.add_argument("--no-stream", action="store_true", help="Disable live streaming output")
        p_run.add_argument("--ip", default=None, help="Override node IP address")

    args = parser.parse_args()

    if not args.subcommand:
        cmd_status(load_tower_ip())
        return

    if args.subcommand == "set-ip":
        save_tower_ip(args.ip_address)
        return

    tower_ip = getattr(args, "ip", None) or load_tower_ip()

    if args.subcommand == "status":
        cmd_status(tower_ip)
    elif args.subcommand == "ping":
        res = query_tower(tower_ip, "/health")
        if "error" in res:
            print(f"❌ Connection error: {res['error']}")
        else:
            print(f"✅ Node online: {res.get('node')} (status: {res.get('status')}, ver: {res.get('version')})")
    elif args.subcommand == "models":
        cmd_models(tower_ip)
    elif args.subcommand == "unload":
        cmd_unload(tower_ip)
    elif args.subcommand == "bench":
        cmd_bench(tower_ip, model=args.model)
    elif args.subcommand in ("run", "infer", "ask"):
        prompt_text = read_input_stream(prompt_arg=args.prompt, file_arg=args.file)
        if not prompt_text:
            print("❌ Missing prompt or piped input. Usage: lukk-tower run \"Prompt...\" or 'cat file | lukk-tower run'")
            sys.exit(1)

        dispatch_workload(
            prompt=prompt_text,
            ip=tower_ip,
            file_path=None,  # Already integrated into immutable prompt_text
            model=args.model,
            profile=args.profile,
            unload_after=args.unload,
            stream=not args.no_stream,
            keep_alive=args.keep_alive
        )

if __name__ == "__main__":
    main()
