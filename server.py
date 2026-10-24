#!/usr/bin/env python3
"""
🛰️ LUKK-NODE: Remote GPU Telemetry & Local LLM Orchestration Server
Lightweight satellite agent for NVIDIA GPU telemetry and Ollama model orchestration.
Zero external dependencies (Python 3 standard library only).
Cross-platform: Windows and Linux.
Default port: 9876
"""

import sys
import os
import json
import socket
import subprocess
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("LUKK_NODE_PORT", 9876))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

PROFILES = {
    "code": (
        "You are an expert software engineering assistant. "
        "Write modular, clean, well-typed, and production-ready code. "
        "Be concise, direct, and provide high-quality technical implementations."
    ),
    "review": (
        "You are a rigorous code quality and security auditor. "
        "Analyze the provided code thoroughly for memory leaks, race conditions, "
        "algorithmic inefficiencies, and security flaws. Provide exact, actionable fixes."
    ),
    "chat": (
        "You are an AI assistant running on a dedicated local GPU node. "
        "Respond with technical rigor, precision, and pragmatic insights."
    ),
    "raw": ""
}

def get_gpu_telemetry():
    """Queries real-time NVIDIA GPU telemetry using nvidia-smi."""
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
                return {
                    "name": parts[0],
                    "gpu_utilization_pct": float(parts[1]),
                    "vram_used_mb": vram_used,
                    "vram_total_mb": vram_total,
                    "temperature_c": float(parts[4]),
                    "power_draw_w": float(parts[5]),
                    "vram_free_mb": max(0.0, vram_total - vram_used),
                    "vram_used_pct": round((vram_used / vram_total) * 100, 1) if vram_total > 0 else 0.0
                }
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

class NodeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_json(200, {
                "status": "ok",
                "node": socket.gethostname(),
                "service": "lukk-node",
                "version": "1.1.0"
            })
        elif self.path == "/telemetry":
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
            gpu = get_gpu_telemetry()
            self._send_json(200, {
                "status": "unloaded",
                "details": res,
                "gpu_after_unload": gpu
            })
        elif self.path in ("/infer", "/dispatch"):
            self._handle_infer()
        else:
            self._send_json(404, {"error": "Route not found"})

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
                gpu_after = get_gpu_telemetry()
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
            gpu_after = get_gpu_telemetry()

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

    def log_message(self, format, *args):
        return

def main():
    server_address = ("0.0.0.0", PORT)
    httpd = HTTPServer(server_address, NodeHandler)
    host_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print("==================================================")
    print("🛰️  LUKK-NODE: Remote GPU Telemetry & Inference Server v1.1.0")
    print(f"📡 Listening on:   http://{host_ip}:{PORT}")
    print(f"🎮 GPU Backend:    nvidia-smi")
    print(f"🧠 Ollama Host:    {OLLAMA_HOST}")
    print("⚡ Endpoints:      /telemetry, /infer, /unload, /models")
    print("🛑 Press Ctrl+C to stop.")
    print("==================================================")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Server stopped by operator.")

if __name__ == "__main__":
    main()
