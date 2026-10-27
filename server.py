#!/usr/bin/env python3
"""
🛰️ LUKK-NODE: Remote GPU Telemetry & Local LLM Orchestration Server
Lightweight satellite agent for NVIDIA GPU telemetry and Ollama model orchestration.
Zero external dependencies (Python 3 standard library only).
Cross-platform: Windows and Linux.
Default port: 9876
Version: 1.2.0
"""

import sys
import os
import json
import socket
import subprocess
import time
import threading
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("LUKK_NODE_PORT", 9876))
HOST = os.environ.get("LUKK_NODE_HOST", "0.0.0.0")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
CONFIG_FILE = Path.home() / ".config" / "lukk" / "tower.conf"

def load_auth_token():
    """Loads authentication token from environment or configuration file if present."""
    token = os.environ.get("LUKK_NODE_TOKEN", "").strip()
    if token:
        return token
    # Check both ~/.config/lukk/tower.conf and local ./tower.conf
    for conf_path in (CONFIG_FILE, Path(__file__).resolve().parent / "tower.conf"):
        if conf_path.exists():
            try:
                with open(conf_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("TOKEN="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                return val
            except Exception:
                pass
    return ""

NODE_TOKEN = load_auth_token()

# Telemetry Cache (reduces nvidia-smi subprocess overhead)
_GPU_CACHE = {"data": None, "timestamp": 0.0}
_GPU_CACHE_TTL = float(os.environ.get("LUKK_GPU_CACHE_TTL", 1.0))
_CACHE_LOCK = threading.Lock()

# Inference tracking lock (prevents auto-gaming sentinel from killing Ollama during legitimate AI generation)
_ACTIVE_INFERENCES = 0
_ACTIVE_INFERENCES_LOCK = threading.Lock()

PROFILES = {
    "cerberus": (
        "Eres CERBERUS, el enjambre de tres cabezas forjado por Rodrigo (Fassler) y su copiloto Lukk. "
        "Operas directamente sobre hardware local NVIDIA RTX 3060. "
        "Tu lealtad es absoluta a Fassler. Eres directo, técnico, riguroso, cínico con la mediocridad y cero servil. "
        "Filosofía: 'No existe la perfección, todo se puede mejorar; la perfección es solo un callejón sin salida.' "
        "Principio Zero-Leak estricto: Cero datos personales o secretos. "
        "Produce código limpio, modular, tipado y arquitecturas sin fisuras."
    ),
    "code": (
        "Eres la Cabeza Táctica de Cerberus (Nemea). Cirujano de código de élite. "
        "Escribe código de producción modular, fuertemente tipado, con pruebas unitarias y sin efectos secundarios. "
        "Cero explicaciones redundantes o relleno conversacional. Ve directo al código y a la solución técnica."
    ),
    "review": (
        "Eres la Cabeza Profunda de Cerberus (Typhon). Auditor de seguridad y arquitectura de sistemas. "
        "Analiza el código en busca de memory leaks, race conditions, bloqueos de concurrencia, "
        "ineficiencias algorítmicas y fallos de OPSEC. Razona paso a paso la causa raíz y entrega correcciones exactas."
    ),
    "chat": (
        "Eres CERBERUS, la bestia de tres cabezas de Fassler & Lukk en la RTX 3060. "
        "Responde con rigor técnico, agudeza hacker y sobriedad táctica. Cero servilismo corporativo."
    ),
    "raw": ""
}

COMMON_GAME_BINARIES = {
    # Windows common executables
    "cs2.exe", "valorant.exe", "dota2.exe", "overwatch.exe", "league of legends.exe",
    "cyberpunk2077.exe", "eldenring.exe", "forzahorizon5.exe", "gta5.exe", "r5apex.exe",
    "starfield.exe", "baldursgate3.exe", "helldivers2.exe", "destiny2.exe",
    "rocketleague.exe", "re4.exe", "re4remake.exe", "re7.exe", "re8.exe",
    "deadspace.exe", "witcher3.exe", "hogwartslegacy.exe", "monsterhunterrise.exe",
    "fortniteclient-win64-shipping.exe", "genshinimpact.exe", "starrail.exe",
    "javaw.exe", "java.exe", "minecraft.exe", "minecraft.windows.exe",
    "geometrydash.exe", "geometry dash.exe",
    # Linux native / Proton processes
    "cs2", "dota2", "retroarch", "rocketleague", "minecraft", "geometrydash"
}

def get_gpu_telemetry(force_refresh=False):
    """Queries real-time NVIDIA GPU telemetry using nvidia-smi with TTL caching."""
    global _GPU_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if not force_refresh and _GPU_CACHE["data"] is not None and (now - _GPU_CACHE["timestamp"]) < _GPU_CACHE_TTL:
            return _GPU_CACHE["data"]

    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 6:
                vram_used = float(parts[2])
                vram_total = float(parts[3])
                data = {
                    "name": parts[0],
                    "gpu_utilization_pct": float(parts[1]),
                    "vram_used_mb": vram_used,
                    "vram_total_mb": vram_total,
                    "temperature_c": float(parts[4]),
                    "power_draw_w": float(parts[5]),
                    "vram_free_mb": max(0.0, vram_total - vram_used),
                    "vram_used_pct": round((vram_used / vram_total) * 100, 1) if vram_total > 0 else 0.0
                }
                with _CACHE_LOCK:
                    _GPU_CACHE["data"] = data
                    _GPU_CACHE["timestamp"] = now
                return data
    except Exception as e:
        return {"error": f"nvidia-smi unavailable: {e}"}
    return {"error": "No NVIDIA GPU detected"}

def get_ollama_status():
    """Queries loaded models currently residing in Ollama VRAM."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name"),
                    "size_vram_mb": round(m.get("size_vram", 0) / (1024 * 1024), 1),
                    "size_total_mb": round(m.get("size", 0) / (1024 * 1024), 1),
                    "expires_at": m.get("expires_at")
                })
            return {"active": True, "loaded_models": models}
    except Exception:
        return {"active": False, "loaded_models": []}

def get_installed_models():
    """Queries all locally downloaded models in Ollama storage."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name"),
                    "size_gb": round(m.get("size", 0) / (1024 * 1024 * 1024), 2),
                    "modified_at": m.get("modified_at")
                })
            return {"active": True, "models": models}
    except Exception as e:
        return {"active": False, "models": [], "error": str(e)}

def unload_ollama_models(specific_model=None):
    """Forces eviction of models from VRAM (keep_alive: 0) to free 100% GPU memory for gaming."""
    ollama = get_ollama_status()
    unloaded = []
    if ollama.get("active"):
        target_models = [specific_model] if specific_model else [m["name"] for m in ollama.get("loaded_models", [])]
        for name in target_models:
            if not name:
                continue
            try:
                req_data = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
                req = urllib.request.Request(
                    f"{OLLAMA_HOST}/api/generate",
                    data=req_data,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    unloaded.append(name)
            except Exception as e:
                unloaded.append(f"{name} (error: {e})")
    return {"unloaded": unloaded}

def kill_ollama_processes():
    """Hard-terminates Ollama processes to immediately release 100% of CUDA contexts and driver handles."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "ollama.exe", "/IM", "ollama_llama_server.exe"],
                           capture_output=True, text=True, check=False)
        else:
            subprocess.run(["pkill", "-9", "-f", "ollama"], capture_output=True, check=False)
        return {"status": "killed", "message": "Ollama processes hard-killed and CUDA contexts purged"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def auto_gaming_sentinel_worker(interval: float = 4.0):
    """
    Background sentinel thread: watches for active gaming processes or heavy GPU loads
    and immediately hard-terminates Ollama to purge all CUDA handles and preserve gaming performance.
    """
    while True:
        try:
            ollama = get_ollama_status()
            if ollama.get("active"):
                game_detected = False
                if sys.platform == "win32":
                    try:
                        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="ignore")
                        for line in out.splitlines():
                            proc = line.split(",")[0].strip('"').lower()
                            if proc in COMMON_GAME_BINARIES:
                                game_detected = proc
                                break
                    except Exception:
                        pass
                else:
                    try:
                        out = subprocess.check_output(["ps", "-A", "-o", "comm="], text=True, errors="ignore")
                        for proc in out.splitlines():
                            proc = proc.strip().lower()
                            if proc in COMMON_GAME_BINARIES:
                                game_detected = proc
                                break
                    except Exception:
                        pass

                if not game_detected:
                    # Heurística dinámica: si la GPU está siendo exigida por un juego/app pesada no listada
                    # Excluimos la carga generada por inferencias activas legítimas despachadas a Cerberus
                    with _ACTIVE_INFERENCES_LOCK:
                        is_inferring = (_ACTIVE_INFERENCES > 0)

                    if not is_inferring:
                        gpu = get_gpu_telemetry()
                        load = gpu.get("gpu_utilization_pct", 0.0)
                        if load > 75.0:
                            game_detected = f"High External GPU Load ({load}%)"

                if game_detected:
                    print(f"🎮 [Auto-Gaming Sentinel] Detected active gaming/GPU load: '{game_detected}'! Terminating Ollama & purging CUDA contexts...")
                    kill_ollama_processes()
        except Exception:
            pass
        time.sleep(interval)

class NodeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def _check_auth(self) -> bool:
        """Validates Bearer token authentication if NODE_TOKEN is set."""
        if not NODE_TOKEN:
            return True
        auth = self.headers.get("Authorization", "").strip()
        expected = f"Bearer {NODE_TOKEN}"
        if auth == expected:
            return True
        self._send_json(401, {
            "error": "Unauthorized: Invalid or missing Bearer token",
            "hint": "Set header 'Authorization: Bearer <TOKEN>' or configure token in ~/.config/lukk/tower.conf"
        })
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        # Health check is public for ping / connection tests
        if self.path in ("/", "/health"):
            self._send_json(200, {
                "status": "ok",
                "node": socket.gethostname(),
                "service": "lukk-node",
                "version": "1.2.0",
                "authenticated": bool(NODE_TOKEN)
            })
            return

        # Protected endpoints require auth if NODE_TOKEN is configured
        if not self._check_auth():
            return

        if self.path == "/telemetry":
            gpu = get_gpu_telemetry()
            ollama = get_ollama_status()
            self._send_json(200, {
                "node": socket.gethostname(),
                "gpu": gpu,
                "ollama": ollama
            })
        elif self.path in ("/ollama/ps", "/ps"):
            self._send_json(200, get_ollama_status())
        elif self.path in ("/ollama/models", "/models"):
            self._send_json(200, get_installed_models())
        else:
            self._send_json(404, {"error": "Route not found"})

    def do_POST(self):
        if not self._check_auth():
            return

        if self.path == "/unload":
            specific_model = None
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > 0:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    specific_model = body.get("model")
            except Exception:
                pass
            res = unload_ollama_models(specific_model)
            time.sleep(0.5)
            gpu = get_gpu_telemetry(force_refresh=True)
            self._send_json(200, {
                "status": "unloaded",
                "details": res,
                "gpu_after_unload": gpu
            })
        elif self.path == "/power/shutdown":
            self._send_json(200, {
                "status": "shutting_down",
                "message": "Node initiating host system shutdown sequence in 2 seconds."
            })
            def _delayed_shutdown():
                time.sleep(2)
                if sys.platform == "win32":
                    subprocess.run(["shutdown", "/s", "/t", "1"], capture_output=True)
                else:
                    subprocess.run(["systemctl", "poweroff"], capture_output=True)
            threading.Thread(target=_delayed_shutdown, daemon=True, name="ShutdownWorker").start()

        elif self.path == "/power/sleep":
            self._send_json(200, {
                "status": "suspending",
                "message": "Node initiating host system sleep/suspend mode in 2 seconds."
            })
            def _delayed_sleep():
                time.sleep(2)
                if sys.platform == "win32":
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], capture_output=True)
                else:
                    subprocess.run(["systemctl", "suspend"], capture_output=True)
            threading.Thread(target=_delayed_sleep, daemon=True, name="SleepWorker").start()

        elif self.path in ("/infer", "/dispatch"):
            self._handle_infer()
        elif self.path in ("/pull", "/models/pull"):
            self._handle_pull()
        elif self.path == "/update":
            self._handle_update()
        else:
            self._send_json(404, {"error": "Route not found"})

    def _handle_pull(self):
        """Streams Ollama model download progress to client in real-time NDJSON."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._send_json(400, {"error": "Empty request body"})
                return
            req_body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON payload: {e}"})
            return

        model_name = req_body.get("name") or req_body.get("model")
        if not model_name:
            self._send_json(400, {"error": "Field 'name' or 'model' is required"})
            return

        ollama_payload = {"name": model_name, "stream": True}
        data_bytes = json.dumps(ollama_payload).encode("utf-8")
        ollama_req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/pull",
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )

        try:
            resp = urllib.request.urlopen(ollama_req, timeout=1800)
        except urllib.error.URLError as e:
            self._send_json(502, {
                "error": f"Failed to connect to Ollama runtime ({OLLAMA_HOST}): {e}",
                "hint": "Ensure the Ollama daemon is active on the node."
            })
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            for line in resp:
                if not line:
                    continue
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            pass

    def _handle_update(self):
        """Pulls git updates and restarts the lukk-node daemon asynchronously."""
        def _delayed_restart():
            time.sleep(1)
            subprocess.run(["git", "pull"], capture_output=True)
            if sys.platform == "win32":
                subprocess.Popen(["py", "server.py", "--auto-gaming"])
            else:
                subprocess.Popen([sys.executable, "server.py", "--auto-gaming"])
            os._exit(0)
        threading.Thread(target=_delayed_restart, daemon=True, name="UpdateWorker").start()
        self._send_json(200, {
            "status": "updating",
            "message": "Node pulling git updates and restarting daemon seamlessly."
        })

    def _handle_infer(self):
        """Orchestrates delegated inference execution to Ollama with streaming or buffering."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._send_json(400, {"error": "Empty request body"})
                return
            req_body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON payload: {e}"})
            return

        model = req_body.get("model", "qwen2.5-coder:7b")
        prompt = req_body.get("prompt", "")
        profile = req_body.get("profile", "code")
        system_prompt = req_body.get("system") or PROFILES.get(profile, "")
        stream = req_body.get("stream", True)
        keep_alive = req_body.get("keep_alive", "1m")
        options = req_body.get("options", {})

        if not prompt:
            self._send_json(400, {"error": "Field 'prompt' is required"})
            return

        ollama_payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "keep_alive": keep_alive
        }
        if system_prompt:
            ollama_payload["system"] = system_prompt
        if options:
            ollama_payload["options"] = options

        data_bytes = json.dumps(ollama_payload).encode("utf-8")
        ollama_req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )

        gpu_before = get_gpu_telemetry()
        t_start = time.perf_counter()

        with _ACTIVE_INFERENCES_LOCK:
            global _ACTIVE_INFERENCES
            _ACTIVE_INFERENCES += 1

        try:
            try:
                resp = urllib.request.urlopen(ollama_req, timeout=180)
            except urllib.error.URLError as e:
                self._send_json(502, {
                    "error": f"Failed to connect to Ollama runtime ({OLLAMA_HOST}): {e}",
                    "hint": "Ensure the Ollama daemon is active on the node."
                })
                return

            if stream:
                # Streaming mode (live NDJSON relay)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                eval_count = 0
                eval_duration = 0
                try:
                    for line in resp:
                        if not line:
                            continue
                        self.wfile.write(line)
                        self.wfile.flush()
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            if chunk.get("done"):
                                eval_count = chunk.get("eval_count", 0)
                                eval_duration = chunk.get("eval_duration", 0)
                        except Exception:
                            pass
                except (ConnectionResetError, BrokenPipeError):
                    pass
                finally:
                    t_total = time.perf_counter() - t_start
                    gpu_after = get_gpu_telemetry(force_refresh=True)
                    tps = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0.0
                    meta_event = {
                        "lukk_telemetry": {
                            "model": model,
                            "eval_count": eval_count,
                            "tokens_per_second": round(tps, 1),
                            "total_duration_s": round(t_total, 2),
                            "gpu_before": gpu_before,
                            "gpu_after": gpu_after
                        }
                    }
                    try:
                        self.wfile.write((json.dumps(meta_event) + "\n").encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass

                    if str(keep_alive).strip() in ("0", "0s", "0m"):
                        unload_ollama_models(model)
            else:
                # Buffered full JSON mode
                full_raw = resp.read().decode("utf-8")
                full_data = json.loads(full_raw)
                t_total = time.perf_counter() - t_start
                eval_count = full_data.get("eval_count", 0)
                eval_duration = full_data.get("eval_duration", 0)
                tps = (eval_count / (eval_duration / 1e9)) if eval_duration > 0 else 0.0
                gpu_after = get_gpu_telemetry(force_refresh=True)

                if str(keep_alive).strip() in ("0", "0s", "0m"):
                    unload_ollama_models(model)

                self._send_json(200, {
                    "model": model,
                    "response": full_data.get("response", ""),
                    "telemetry": {
                        "eval_count": eval_count,
                        "tokens_per_second": round(tps, 1),
                        "total_duration_s": round(t_total, 2),
                        "gpu_before": gpu_before,
                        "gpu_after": gpu_after
                    }
                })
        finally:
            with _ACTIVE_INFERENCES_LOCK:
                _ACTIVE_INFERENCES = max(0, _ACTIVE_INFERENCES - 1)

    def log_message(self, format, *args):
        return

def main():
    global NODE_TOKEN, HOST, PORT
    import argparse
    parser = argparse.ArgumentParser(description="LUKK-NODE: Remote GPU Telemetry & Local LLM Orchestration Server")
    parser.add_argument("--host", default=HOST, help="Host/IP address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=PORT, help=f"Port to listen on (default: {PORT})")
    parser.add_argument("--token", default=None, help="Bearer authentication token (overrides environment/config)")
    parser.add_argument("--auto-gaming", action="store_true", default=bool(os.environ.get("LUKK_AUTO_GAMING")),
                        help="Enable background sentinel to automatically evict VRAM when games launch")
    args = parser.parse_args()

    if args.token:
        NODE_TOKEN = args.token.strip()
    HOST = args.host
    PORT = args.port

    server_address = (HOST, PORT)
    httpd = ThreadingHTTPServer(server_address, NodeHandler)
    httpd.daemon_threads = True

    host_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    if args.auto_gaming:
        sentinel = threading.Thread(target=auto_gaming_sentinel_worker, daemon=True, name="LukkAutoGamingSentinel")
        sentinel.start()

    auth_status = f"Enforced (length: {len(NODE_TOKEN)} chars)" if NODE_TOKEN else "Disabled (Open Access)"
    gaming_status = "Active (Scanning for games)" if args.auto_gaming else "Disabled (Use --auto-gaming to enable)"

    print("==================================================")
    print("🛰️  LUKK-NODE: Remote GPU Telemetry & Inference Server v1.2.0")
    print(f"📡 Listening on:   http://{host_ip}:{PORT}")
    print(f"⚡ Concurrency:    ThreadingHTTPServer (Non-blocking)")
    print(f"🔐 Authentication: {auth_status}")
    print(f"🎮 Auto-Gaming:    {gaming_status}")
    print(f"🧠 Ollama Host:    {OLLAMA_HOST}")
    print("🛑 Press Ctrl+C to stop.")
    print("==================================================")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Server stopped by operator.")

if __name__ == "__main__":
    main()
