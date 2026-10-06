#!/usr/bin/env python3
"""
CTF Container Launcher Service
Легковесный автономный менеджер запуска заданий для школьных CTF-соревнований.
Не требует внешних pip-библиотек (работает на стандартной библиотеке Python 3).
"""

import http.server
import socketserver
import json
import os
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

# Импорт конфигурации
try:
    from config import (
        HOST_IP,
        LAUNCHER_PORT,
        CONTAINER_TTL_MINUTES,
        PORT_RANGE_START,
        PORT_RANGE_END,
        PORTS_PER_INSTANCE,
        DOCKER_NETWORK,
    )
except ImportError:
    from launcher.config import (
        HOST_IP,
        LAUNCHER_PORT,
        CONTAINER_TTL_MINUTES,
        PORT_RANGE_START,
        PORT_RANGE_END,
        PORTS_PER_INSTANCE,
        DOCKER_NETWORK,
    )

BASE_DIR = Path(__file__).resolve().parent.parent
TASKS_DIR = BASE_DIR / "tasks"
TEMPLATES_DIR = BASE_DIR / "templates"

# Хранилище активных инстансов: { instance_key: dict }
# instance_key = f"{task_id}_{session_id}"
ACTIVE_INSTANCES = {}
INSTANCES_LOCK = threading.Lock()

# Множество занятых базовых портов
ALLOCATED_BASE_PORTS = set()


def ensure_docker_network():
    """Создает изолированную сеть Docker без блокировки проброса портов."""
    try:
        check = subprocess.run(
            ["docker", "network", "inspect", DOCKER_NETWORK],
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            # Если сеть была ошибочно создана с флагом --internal (он полностью блокирует проброс портов -p),
            # удаляем ее и создаем заново без --internal
            if '"Internal": true' in check.stdout:
                print(f"[LAUNCHER] Сеть {DOCKER_NETWORK} была создана с флагом --internal (он блокирует проброс портов). Пересоздаем...")
                subprocess.run(["docker", "network", "rm", DOCKER_NETWORK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["docker", "network", "create", DOCKER_NETWORK], check=True)
        else:
            print(f"[LAUNCHER] Создание сети {DOCKER_NETWORK}...")
            subprocess.run(
                ["docker", "network", "create", DOCKER_NETWORK],
                check=True,
            )
    except Exception as e:
        print(f"[LAUNCHER] Внимание: не удалось настроить сеть {DOCKER_NETWORK}: {e}")


def load_task(task_id):
    """Загружает конфигурацию задания из tasks/<task_id>/task.json."""
    for folder in TASKS_DIR.iterdir():
        if folder.is_dir():
            conf_file = folder / "task.json"
            if conf_file.exists():
                try:
                    with open(conf_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("id") == task_id or folder.name == task_id:
                            data["_folder"] = str(folder)
                            return data
                except Exception as e:
                    print(f"Ошибка чтения {conf_file}: {e}")
    return None


def get_all_tasks():
    """Возвращает список всех доступных заданий."""
    tasks = []
    if not TASKS_DIR.exists():
        return tasks
    for folder in sorted(TASKS_DIR.iterdir()):
        if folder.is_dir():
            conf_file = folder / "task.json"
            if conf_file.exists():
                try:
                    with open(conf_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["_folder"] = str(folder)
                        tasks.append(data)
                except Exception as e:
                    print(f"Ошибка чтения {conf_file}: {e}")
    return tasks


def allocate_port_block(size=PORTS_PER_INSTANCE):
    """Выделяет свободный блок портов."""
    with INSTANCES_LOCK:
        for base_port in range(PORT_RANGE_START, PORT_RANGE_END - size, size):
            if base_port not in ALLOCATED_BASE_PORTS:
                ALLOCATED_BASE_PORTS.add(base_port)
                return base_port
    raise RuntimeError("Нет свободных портов в пуле для запуска нового задания!")


def release_port_block(base_port):
    """Освобождает блок портов."""
    with INSTANCES_LOCK:
        ALLOCATED_BASE_PORTS.discard(base_port)


def stop_container_by_name(container_name):
    """Принудительно останавливает и удаляет Docker-контейнер."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"Ошибка остановки контейнера {container_name}: {e}")


def janitor_thread():
    """Фоновый сборщик мусора: удаляет просроченные контейнеры по TTL."""
    while True:
        time.sleep(5)
        now = time.time()
        to_remove = []
        with INSTANCES_LOCK:
            for key, inst in list(ACTIVE_INSTANCES.items()):
                if now >= inst["expires_at"]:
                    to_remove.append((key, inst))

        for key, inst in to_remove:
            print(f"[JANITOR] Истекло время жизни инстанса: {inst['container_name']}. Удаление...")
            stop_container_by_name(inst["container_name"])
            release_port_block(inst["base_port"])
            with INSTANCES_LOCK:
                ACTIVE_INSTANCES.pop(key, None)


class CTFRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Отключаем кеширование
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/tasks":
            self.render_index_page()
            return
        elif path.startswith("/task/"):
            task_id = path.split("/task/")[1].strip("/")
            self.render_task_page(task_id)
            return
        elif path == "/api/status":
            self.handle_api_status(parsed.query)
            return
        else:
            self.send_error(404, "Страница не найдена")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")

        try:
            body = json.loads(post_data) if post_data else {}
        except Exception:
            body = urllib.parse.parse_qs(post_data)
            body = {k: v[0] for k, v in body.items()}

        if parsed.path == "/api/start":
            self.handle_api_start(body)
        elif parsed.path == "/api/stop":
            self.handle_api_stop(body)
        else:
            self.send_error(404, "API endpoint not found")

    def send_json(self, data, status_code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_status(self, query_str):
        qs = urllib.parse.parse_qs(query_str)
        task_id = qs.get("task_id", [""])[0]
        session_id = qs.get("session_id", [""])[0]

        if not task_id or not session_id:
            self.send_json({"error": "task_id and session_id required"}, 400)
            return

        key = f"{task_id}_{session_id}"
        with INSTANCES_LOCK:
            inst = ACTIVE_INSTANCES.get(key)

        if not inst:
            self.send_json({"running": False})
            return

        remaining = max(0, int(inst["expires_at"] - time.time()))
        self.send_json({
            "running": True,
            "host": HOST_IP,
            "base_port": inst["base_port"],
            "port_range": f"{inst['base_port']} - {inst['base_port'] + inst['port_range_size'] - 1}",
            "service_port": inst["active_service_port"],
            "mode": inst["mode"],
            "remaining_seconds": remaining,
        })

    def handle_api_stop(self, body):
        task_id = body.get("task_id")
        session_id = body.get("session_id")
        if not task_id or not session_id:
            self.send_json({"error": "task_id and session_id required"}, 400)
            return

        key = f"{task_id}_{session_id}"
        with INSTANCES_LOCK:
            inst = ACTIVE_INSTANCES.pop(key, None)

        if inst:
            print(f"[LAUNCHER] Остановка инстанса по запросу пользователя: {inst['container_name']}")
            stop_container_by_name(inst["container_name"])
            release_port_block(inst["base_port"])
            self.send_json({"success": True, "message": "Инстанс остановлен"})
        else:
            self.send_json({"success": True, "message": "Инстанс не был запущен"})

    def handle_api_start(self, body):
        task_id = body.get("task_id")
        session_id = body.get("session_id")
        if not task_id or not session_id:
            self.send_json({"error": "task_id and session_id required"}, 400)
            return

        key = f"{task_id}_{session_id}"

        # Если уже запущен, возвращаем существующий
        with INSTANCES_LOCK:
            if key in ACTIVE_INSTANCES:
                inst = ACTIVE_INSTANCES[key]
                remaining = max(0, int(inst["expires_at"] - time.time()))
                self.send_json({
                    "running": True,
                    "host": HOST_IP,
                    "base_port": inst["base_port"],
                    "port_range": f"{inst['base_port']} - {inst['base_port'] + inst['port_range_size'] - 1}",
                    "service_port": inst["active_service_port"],
                    "mode": inst["mode"],
                    "remaining_seconds": remaining,
                })
                return

        task = load_task(task_id)
        if not task:
            self.send_json({"error": f"Задание '{task_id}' не найдено"}, 404)
            return

        port_range_size = task.get("port_range_size", PORTS_PER_INSTANCE)
        mode = task.get("mode", "direct")
        service_offset = task.get("service_offset", 0)

        try:
            base_port = allocate_port_block(port_range_size)
        except RuntimeError as e:
            self.send_json({"error": str(e)}, 503)
            return

        target_service_host_port = base_port + service_offset
        container_name = f"ctf_{task['id']}_{session_id[:6]}_{base_port}"

        # Подготовка путей
        content_path = Path(task["_folder"]) / "content"
        mount_path = task.get("mount_path", "/var/www/html")

        # Формирование аргументов docker run
        docker_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
        ]

        # Монтирование содержимого строго Read-Only (:ro)
        if content_path.exists():
            docker_cmd.extend(["-v", f"{content_path.resolve()}:{mount_path}:ro"])

        # Проброс портов в зависимости от шаблона
        template = task.get("template", "web")
        env_vars = task.get("env", {}).copy()

        if template == "ftp":
            pasv_offset = task.get("pasv_offset", 1)
            target_pasv_host_port = base_port + pasv_offset
            docker_cmd.extend([
                "-p", f"{target_service_host_port}:21",
                "-p", f"{target_pasv_host_port}:{target_pasv_host_port}",
            ])
            env_vars["HOST_IP"] = HOST_IP
            env_vars["FTP_PORT"] = "21"
            env_vars["FTP_PASV_PORT"] = str(target_pasv_host_port)
        elif template == "web":
            container_internal_port = task.get("service_port", 80)
            docker_cmd.extend([
                "-p", f"{target_service_host_port}:{container_internal_port}",
            ])
            env_vars["WEB_PORT"] = str(container_internal_port)
        elif template == "os":
            container_internal_port = task.get("service_port", 22)
            docker_cmd.extend([
                "-p", f"{target_service_host_port}:{container_internal_port}",
            ])
            env_vars["SSH_PORT"] = str(container_internal_port)

        for k, v in env_vars.items():
            docker_cmd.extend(["-e", f"{k}={v}"])

        # Образ шаблона
        image_name = f"ctf-template-{template}:latest"
        docker_cmd.append(image_name)

        print(f"[LAUNCHER] Запуск: {' '.join(docker_cmd)}")
        res = subprocess.run(docker_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            release_port_block(base_port)
            print(f"[LAUNCHER] Ошибка запуска: {res.stderr}")
            self.send_json({"error": f"Ошибка Docker: {res.stderr.strip()}"}, 500)
            return

        expires_at = time.time() + (CONTAINER_TTL_MINUTES * 60)
        inst_info = {
            "container_name": container_name,
            "base_port": base_port,
            "port_range_size": port_range_size,
            "active_service_port": target_service_host_port,
            "mode": mode,
            "expires_at": expires_at,
        }

        with INSTANCES_LOCK:
            ACTIVE_INSTANCES[key] = inst_info

        self.send_json({
            "running": True,
            "host": HOST_IP,
            "base_port": base_port,
            "port_range": f"{base_port} - {base_port + port_range_size - 1}",
            "service_port": target_service_host_port,
            "mode": mode,
            "remaining_seconds": int(CONTAINER_TTL_MINUTES * 60),
        })

    def render_index_page(self):
        tasks = get_all_tasks()
        items_html = ""
        for t in tasks:
            tid = t.get("id")
            title = t.get("title", tid)
            desc = t.get("description", "")
            tmpl = t.get("template", "web")
            items_html += f"""
            <div class="task-card">
                <div class="task-badge">{tmpl.upper()}</div>
                <h2>{title}</h2>
                <p>{desc}</p>
                <a class="btn-link" href="/task/{tid}">Перейти к запуску стенда &rarr;</a>
            </div>
            """

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Школьный CTF — Стенды заданий</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px 20px; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        h1 {{ font-size: 28px; margin-bottom: 8px; color: #38bdf8; }}
        p.subtitle {{ color: #94a3b8; margin-top: 0; margin-bottom: 30px; }}
        .task-card {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 20px; border: 1px solid #334155; position: relative; }}
        .task-badge {{ position: absolute; top: 24px; right: 24px; background: #0284c7; color: white; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
        .task-card h2 {{ margin-top: 0; font-size: 20px; color: #f1f5f9; }}
        .task-card p {{ color: #cbd5e1; line-height: 1.5; }}
        .btn-link {{ display: inline-block; background: #0284c7; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-top: 10px; }}
        .btn-link:hover {{ background: #0369a1; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚩 Школьные соревнования CTF</h1>
        <p class="subtitle">Портал автономного запуска практических заданий</p>
        {items_html}
    </div>
</body>
</html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_task_page(self, task_id):
        task = load_task(task_id)
        if not task:
            self.send_error(404, f"Задание '{task_id}' не найдено")
            return

        title = task.get("title", task_id)
        desc = task.get("description", "")
        template = task.get("template", "web")
        mode = task.get("mode", "direct")

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{title} — Запуск стенда</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f3f4f6; margin: 0; padding: 40px 20px; }}
        .container {{ max-width: 680px; margin: 0 auto; background: #111827; border: 1px solid #1f2937; border-radius: 16px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h1 {{ font-size: 24px; margin-top: 0; color: #38bdf8; }}
        .desc {{ color: #9ca3af; line-height: 1.6; margin-bottom: 24px; }}
        .card-box {{ background: #1f2937; border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
        .btn {{ border: none; padding: 12px 24px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: 0.2s; }}
        .btn-start {{ background: #10b981; color: white; }}
        .btn-start:hover {{ background: #059669; }}
        .btn-stop {{ background: #ef4444; color: white; display: none; }}
        .btn-stop:hover {{ background: #dc2626; }}
        .timer-box {{ font-size: 28px; font-weight: bold; color: #fbbf24; font-family: monospace; margin: 15px 0; }}
        .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: bold; }}
        .status-off {{ background: #374151; color: #9ca3af; }}
        .status-on {{ background: #065f46; color: #34d399; }}
        .info-row {{ margin-top: 10px; font-size: 15px; color: #e5e7eb; }}
        .code {{ background: #374151; padding: 3px 8px; border-radius: 4px; font-family: monospace; color: #38bdf8; font-weight: bold; }}
        .link-back {{ display: inline-block; margin-top: 24px; color: #60a5fa; text-decoration: none; font-size: 14px; }}
        .link-back:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <span id="status-badge" class="status-badge status-off">ОСТАНОВЛЕН</span>
        <h1 style="margin-top: 12px;">{title}</h1>
        <p class="desc">{desc}</p>

        <div class="card-box">
            <div id="controls">
                <button id="btn-start" class="btn btn-start" onclick="startContainer()">▶ Запустить задание</button>
                <button id="btn-stop" class="btn btn-stop" onclick="stopContainer()">⏹ Остановить задание</button>
            </div>

            <div id="active-panel" style="display: none; margin-top: 20px;">
                <div style="font-size: 14px; color: #9ca3af;">Оставшееся время работы:</div>
                <div id="timer" class="timer-box">--:--</div>

                <div class="info-row" id="conn-info"></div>
            </div>
        </div>

        <a class="link-back" href="/">&larr; Вернуться к списку заданий</a>
    </div>

    <script>
        const taskId = "{task_id}";
        let sessionId = localStorage.getItem("ctf_session_id");
        if (!sessionId) {{
            sessionId = "s_" + Math.random().toString(36).substring(2, 10);
            localStorage.setItem("ctf_session_id", sessionId);
        }}

        let timerInterval = null;
        let secondsRemaining = 0;

        function updateUI(running, data) {{
            const badge = document.getElementById("status-badge");
            const btnStart = document.getElementById("btn-start");
            const btnStop = document.getElementById("btn-stop");
            const activePanel = document.getElementById("active-panel");
            const connInfo = document.getElementById("conn-info");

            if (running) {{
                badge.className = "status-badge status-on";
                badge.innerText = "АКТИВЕН";
                btnStart.style.display = "none";
                btnStop.style.display = "inline-block";
                activePanel.style.display = "block";

                secondsRemaining = data.remaining_seconds || 0;
                startTimerCountdown();

                const targetHost = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") ? window.location.hostname : data.host;
                if (data.mode === "scan") {{
                    connInfo.innerHTML = `
                        <div>🌐 <b>Целевой хост:</b> <span class="code">${{targetHost}}</span></div>
                        <div style="margin-top: 8px;">🔍 <b>Диапазон для сканирования:</b> <span class="code">порты ${{data.port_range}}</span></div>
                        <div style="margin-top: 8px; font-size: 13px; color: #9ca3af;">Пример: <code>nmap -p ${{data.port_range}} ${{targetHost}}</code></div>
                    `;
                }} else {{
                    const url = "http://" + targetHost + ":" + data.service_port;
                    connInfo.innerHTML = `
                        <div>🌐 <b>Адрес сервиса:</b> <a href="${{url}}" target="_blank" class="code" style="text-decoration: underline;">${{url}}</a></div>
                    `;
                }}
            }} else {{
                badge.className = "status-badge status-off";
                badge.innerText = "ОСТАНОВЛЕН";
                btnStart.style.display = "inline-block";
                btnStop.style.display = "none";
                activePanel.style.display = "none";
                if (timerInterval) clearInterval(timerInterval);
            }}
        }}

        function formatTime(sec) {{
            const m = Math.floor(sec / 60).toString().padStart(2, '0');
            const s = (sec % 60).toString().padStart(2, '0');
            return m + ":" + s;
        }}

        function startTimerCountdown() {{
            if (timerInterval) clearInterval(timerInterval);
            document.getElementById("timer").innerText = formatTime(secondsRemaining);
            timerInterval = setInterval(() => {{
                secondsRemaining--;
                if (secondsRemaining <= 0) {{
                    clearInterval(timerInterval);
                    checkStatus();
                }} else {{
                    document.getElementById("timer").innerText = formatTime(secondsRemaining);
                }}
            }}, 1000);
        }}

        async function checkStatus() {{
            try {{
                const res = await fetch(`/api/status?task_id=${{taskId}}&session_id=${{sessionId}}`);
                const data = await res.json();
                updateUI(data.running, data);
            }} catch (e) {{
                console.error("Ошибка проверки статуса:", e);
            }}
        }}

        async function startContainer() {{
            const btn = document.getElementById("btn-start");
            btn.disabled = true;
            btn.innerText = "Запуск...";
            try {{
                const res = await fetch('/api/start', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ task_id: taskId, session_id: sessionId }})
                }});
                const data = await res.json();
                if (data.error) {{
                    alert("Ошибка: " + data.error);
                }} else {{
                    updateUI(true, data);
                }}
            }} catch (e) {{
                alert("Ошибка сети при запуске: " + e);
            }} finally {{
                btn.disabled = false;
                btn.innerText = "▶ Запустить задание";
            }}
        }}

        async function stopContainer() {{
            const btn = document.getElementById("btn-stop");
            btn.disabled = true;
            btn.innerText = "Остановка...";
            try {{
                const res = await fetch('/api/stop', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ task_id: taskId, session_id: sessionId }})
                }});
                const data = await res.json();
                updateUI(false);
            }} catch (e) {{
                alert("Ошибка при остановке: " + e);
            }} finally {{
                btn.disabled = false;
                btn.innerText = "⏹ Остановить задание";
            }}
        }}

        // Начальная проверка
        checkStatus();
    </script>
</body>
</html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ensure_docker_network()

    # Запуск потока фоновой очистки (TTL janitor)
    t = threading.Thread(target=janitor_thread, daemon=True)
    t.start()

    server_address = ("0.0.0.0", LAUNCHER_PORT)
    print(f"==================================================")
    print(f"  CTF Task Launcher запущен!")
    print(f"  Веб-интерфейс: http://0.0.0.0:{LAUNCHER_PORT}")
    print(f"  Внешний IP: {HOST_IP}")
    print(f"  TTL заданий: {CONTAINER_TTL_MINUTES} минут")
    print(f"  Пул портов: {PORT_RANGE_START} - {PORT_RANGE_END}")
    print(f"==================================================")

    with socketserver.ThreadingTCPServer(server_address, CTFRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[LAUNCHER] Завершение работы...")


if __name__ == "__main__":
    main()
