#!/usr/bin/env node
"use strict";
/**
 * Paimon — lanzador único de los aplicativos del repo.
 *
 * Each app is a `docker compose` stack in its own folder, so this launcher
 * delegates to Compose (no venvs, no PIDs: Docker gestiona los contenedores).
 *
 *   node dev.js                 # levanta todo: audio + image + processing + swagger
 *   node dev.js --audio         # solo audio_processing
 *   node dev.js --image         # solo image_generator
 *   node dev.js --processing    # solo image_processing (alias: --removebg)
 *   node dev.js --swagger       # portal Swagger global (alias: --docs, --gateway)
 *   node dev.js --all           # explícito: los tres
 *   node dev.js --build         # (re)construye las imágenes al levantar
 *   node dev.js --logs [flags]  # sigue los logs de los seleccionados (Ctrl+C sale)
 *   node dev.js --stop [flags]  # detiene los seleccionados (o todos)
 *   node dev.js --help
 *
 * PUERTOS
 *   Cada API escucha internamente en :8000. Al levantar varias, se publican en
 *   puertos distintos del host: audio :8100, imagen :8101 y procesamiento :8102
 *   (el siguiente libre si alguno está ocupado). Se fijan con AUDIO_HOST_PORT /
 *   IMAGE_API_HOST_PORT / IMAGE_PROCESSING_HOST_PORT. Si un contenedor ya está
 *   en marcha, se conserva su puerto (re-ejecutar no mueve las URLs). Los demás
 *   puertos no cambian: ComfyUI :8188 (COMFYUI_HOST_PORT), métricas :9101
 *   (IMAGE_METRICS_HOST_PORT). Redis NO se publica en el host.
 *
 * Logs: logs/<app>.log (salida de `docker compose`).
 */
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const ROOT = __dirname;
const LOGS_DIR = path.join(ROOT, "logs");
const RESET = "\x1b[0m";

// Tiempo máximo de espera al puerto de la API (ComfyUI tarda en arrancar:
// la API de image_generator no publica hasta que ComfyUI pasa su healthcheck).
const UP_TIMEOUT_MS = 180000;

// ── Catálogo de aplicativos ─────────────────────────────────
// `port` = puerto del host que publica la API; se reasigna si hay conflicto.
// `portEnv` = variable que el docker-compose.yml del app lee para ese puerto.
// `container` = contenedor de la API; si ya corre, se conserva su puerto actual.
const PROJECTS = [
  {
    name: "audio",
    label: "audio_processing",
    dir: "audio_processing",
    container: "paimon-audio-processing",
    portEnv: "AUDIO_HOST_PORT",
    port: 8100,
    color: "\x1b[36m",
    endpoints: (p) => [
      ["API", `http://localhost:${p}`],
      ["Swagger", `http://localhost:${p}/docs`],
      ["OpenAPI", `http://localhost:${p}/openapi.json`],
      ["transcribe", `http://localhost:${p}/transcribe`],
    ],
  },
  {
    name: "image",
    label: "image_generator",
    dir: "image_generator",
    container: "paimon-image-api",
    portEnv: "IMAGE_API_HOST_PORT",
    port: 8101,
    color: "\x1b[32m",
    endpoints: (p) => [
      ["API", `http://localhost:${p}`],
      ["docs", `http://localhost:${p}/docs`],
      ["ComfyUI", `http://localhost:${process.env.COMFYUI_HOST_PORT || 8188}`],
    ],
  },
  {
    name: "processing",
    label: "image_processing",
    dir: "image_processing",
    container: "paimon-image-processing",
    portEnv: "IMAGE_PROCESSING_HOST_PORT",
    port: 8102,
    color: "\x1b[35m",
    endpoints: (p) => [
      ["API", `http://localhost:${p}`],
      ["docs", `http://localhost:${p}/docs`],
      ["remove-bg", `POST http://localhost:${p}/remove-bg`],
    ],
  },
  {
    name: "swagger",
    label: "swagger global",
    dir: "gateway",
    container: "paimon-swagger",
    portEnv: "SWAGGER_HOST_PORT",
    port: 8080,
    // `network_mode: host`: no publica puertos; escucha en el loopback del host
    // y desde ahí proxya las APIs publicadas en 127.0.0.1.
    hostNetwork: true,
    color: "\x1b[33m",
    endpoints: (p) => [
      ["Swagger", `http://localhost:${p}`],
      ["APIs", `http://localhost:${p}/  (audio, image, processing)`],
    ],
  },
];

const PROJECT_NAMES = new Set(PROJECTS.map((p) => p.name));

// Alias de selección: nombres alternativos que resuelven a un app del catálogo.
// Sirven para que el flag sea evidente por funcionalidad y no solo por carpeta.
const PROJECT_ALIASES = {
  removebg: "processing",
  "remove-bg": "processing",
  remove_bg: "processing",
  "image-processing": "processing",
  image_processing: "processing",
  docs: "swagger",
  gateway: "swagger",
  portal: "swagger",
  apidocs: "swagger",
  "api-docs": "swagger",
};

// Puertos fijos que no deben asignarse por reasignación automática.
// 8188 = ComfyUI, 9101 = métricas del worker.
const RESERVED_PORTS = [8188, 9101];

const VALID_FLAGS = new Set([
  "--all",
  "--build",
  "--logs",
  "--stop",
  "--help",
  ...PROJECTS.map((p) => `--${p.name}`),
  ...Object.keys(PROJECT_ALIASES).map((a) => `--${a}`),
]);

function color(project) {
  return `${project.color}[${project.label}]${RESET}`;
}

/**
 * Apps elegidas por los flags. `null` ⇒ todas (sin flags de selección).
 *   --all / sin flags   → los tres
 *   --audio --image     → esos (combinables)
 *   --removebg          → alias de --processing
 * Los flags de modo (--build, --stop, ...) y desconocidos se ignoran aquí.
 */
function selectProjects(argv) {
  const flags = argv.filter((a) => a.startsWith("--")).map((a) => a.slice(2).toLowerCase());
  const chosen = new Set();
  let any = false;
  for (const f of flags) {
    if (f === "all") {
      PROJECTS.forEach((p) => chosen.add(p.name));
      any = true;
    } else if (PROJECT_NAMES.has(f) || PROJECT_ALIASES[f]) {
      chosen.add(PROJECT_ALIASES[f] ?? f);
      any = true;
    }
  }
  return any ? PROJECTS.filter((p) => chosen.has(p.name)) : null;
}

/** Flags `--x` no reconocidos. Si hay alguno, el launcher no ejecuta nada. */
function unknownFlags(argv) {
  return argv.filter((a) => a.startsWith("--") && !VALID_FLAGS.has(a.toLowerCase()));
}

/**
 * Puerto de partida de una app. Si el usuario fijó `AUDIO_HOST_PORT` /
 * `IMAGE_API_HOST_PORT` en el entorno, manda ese valor (`pinned`); si no, el
 * del catálogo y se reasigna al siguiente libre.
 */
function preferredPort(project) {
  const raw = Number.parseInt(process.env[project.portEnv] ?? "", 10);
  if (Number.isInteger(raw) && raw > 0) return { port: raw, pinned: true };
  return { port: project.port, pinned: false };
}

/**
 * Asigna a cada app un puerto de host único: evita choques entre las APIs,
 * respeta los `RESERVED_PORTS` y salta los puertos ya ocupados en el host.
 */
async function assignPorts(projects) {
  // Los puertos fijados por el usuario se reservan antes de repartir el resto.
  const pinned = projects.map(preferredPort).filter((p) => p.pinned).map((p) => p.port);
  const used = new Set([...RESERVED_PORTS, ...pinned]);
  const ports = {};
  for (const project of projects) {
    const start = preferredPort(project);
    // Si el contenedor ya está en marcha, conservamos su puerto del host:
    // re-ejecutar dev.js no debe mover las URLs.
    // Con `network_mode: host` no hay puertos publicados que consultar, así que
    // se mantiene el puerto de partida si el contenedor está vivo.
    const live = project.hostNetwork
      ? isContainerRunning(project.container)
        ? start.port
        : null
      : project.container
        ? runningHostPort(project.container, 8000)
        : null;
    let port = start.pinned ? start.port : (live ?? start.port);
    if (!start.pinned && live === null) {
      while (used.has(port) || !(await isPortFree(port))) port += 1;
    }
    used.add(port);
    ports[project.name] = port;
  }
  return ports;
}

// ── Utilidades de red ───────────────────────────────────────

function waitForPort(port, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const attempt = () => {
      const sock = net.connect({ host: "127.0.0.1", port });
      const done = (ok) => {
        try {
          sock.destroy();
        } catch {
          /* noop */
        }
        resolve(ok);
      };
      sock.once("connect", () => done(true));
      sock.once("error", () => {
        try {
          sock.destroy();
        } catch {
          /* noop */
        }
        if (Date.now() > deadline) done(false);
        else setTimeout(attempt, 1000);
      });
    };
    attempt();
  });
}

/** True si el puerto está libre en 127.0.0.1 (prueba con un servidor efímero). */
function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, "127.0.0.1");
  });
}

// ── Logs ────────────────────────────────────────────────────

function openLog(name) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const logPath = path.join(LOGS_DIR, `${name}.log`);
  const fd = fs.openSync(logPath, "a");
  fs.writeSync(fd, `\n===== [${name}] ${new Date().toISOString()} =====\n`);
  return fd;
}

// ── Docker ──────────────────────────────────────────────────

/** Comprueba que `docker compose` (v2) está disponible. */
function checkDocker() {
  const r = spawnSync("docker", ["compose", "version"], { stdio: "ignore" });
  if (r.error || r.status !== 0) {
    console.error("✘ No encuentro `docker compose` (Docker Compose v2). Arranca Docker e inténtalo de nuevo.");
    return false;
  }
  return true;
}

/** Puerto del host que un contenedor ya en marcha publica para `containerPort`. */
function runningHostPort(container, containerPort) {
  const r = spawnSync("docker", ["port", container, `${containerPort}/tcp`], {
    encoding: "utf8",
  });
  if (r.status !== 0 || !r.stdout) return null;
  // Salida tipo "127.0.0.1:8003"; si hay varias líneas (IPv4/IPv6), tomamos la 1ª.
  const match = r.stdout.trim().split("\n")[0].match(/:(\d+)$/);
  return match ? Number.parseInt(match[1], 10) : null;
}

/** True si el contenedor existe y está en marcha. */
function isContainerRunning(container) {
  if (!container) return false;
  const r = spawnSync("docker", ["inspect", "-f", "{{.State.Running}}", container], {
    encoding: "utf8",
  });
  return r.status === 0 && r.stdout.trim() === "true";
}

// Variable de entorno que el gateway usa para cada API proxeada.
const GATEWAY_TARGETS = {
  audio: "AUDIO_PORT",
  image: "IMAGE_PORT",
  processing: "PROCESSING_PORT",
};

/**
 * Puertos que el portal Swagger debe proxear. Si una app no se levanta en esta
 * ejecución, se usa el de un contenedor ya en marcha; si no está, 1 (no
 * disponible) para que el portal la omita.
 */
function gatewayTargets(ports) {
  const env = {};
  for (const project of PROJECTS) {
    const key = GATEWAY_TARGETS[project.name];
    if (!key) continue;
    env[key] = String(
      ports[project.name] ?? runningHostPort(project.container, 8000) ?? 1,
    );
  }
  return env;
}

/**
 * Primera clave de `API_KEYS` en el `.env` de la raíz. El portal la inyecta en
 * las peticiones proxeadas para que "Try it out" no pida token.
 */
function sharedApiKey() {
  try {
    const text = fs.readFileSync(path.join(ROOT, ".env"), "utf8");
    for (const line of text.split("\n")) {
      const match = line.match(/^\s*API_KEYS\s*=\s*(.*)$/);
      if (!match) continue;
      const value = match[1].trim().replace(/^["']|["']$/g, "");
      return value.split(",")[0].trim();
    }
  } catch {
    /* sin .env: el portal funciona sin clave */
  }
  return "";
}

function startProject(project, port, { build, extraEnv = {} }) {
  const tag = color(project);
  const args = ["up", "-d"];
  if (build) args.push("--build");

  console.log(`${tag} ▶ \`docker compose ${args.join(" ")}\` → http://localhost:${port}  (log: logs/${project.name}.log)`);
  if (build) console.log(`${tag} ⏳ construyendo imágenes (puede tardar)...`);

  const fd = openLog(project.name);
  const r = spawnSync("docker", ["compose", ...args], {
    cwd: path.join(ROOT, project.dir),
    stdio: ["ignore", fd, fd],
    env: { ...process.env, [project.portEnv]: String(port), ...extraEnv },
  });
  fs.closeSync(fd);

  if (r.error) {
    console.error(`${tag} ✘ no se pudo ejecutar docker: ${r.error.message}`);
    return false;
  }
  if (r.status !== 0) {
    console.error(`${tag} ✘ falló \`docker compose ${args.join(" ")}\` — revisa logs/${project.name}.log`);
    return false;
  }
  return true;
}

function stopProject(project) {
  const tag = color(project);
  const r = spawnSync("docker", ["compose", "down"], {
    cwd: path.join(ROOT, project.dir),
    stdio: ["ignore", "pipe", "ignore"],
    encoding: "utf8",
  });
  if (r.error) {
    console.error(`${tag} ✘ ${r.error.message}`);
    return;
  }
  if (r.status === 0) console.log(`⏹  ${project.label}`);
  else console.log(`   ${project.label}: nada que detener (o falló el down)`);
}

/** Sigue los logs de las apps seleccionadas (foreground hasta Ctrl+C). */
function followLogs(projects) {
  console.log(`📜 siguiendo logs de ${projects.map((p) => p.label).join(" + ")} (Ctrl+C para salir)`);
  const children = projects.map((p) =>
    spawn("docker", ["compose", "logs", "-f", "--tail=100"], {
      cwd: path.join(ROOT, p.dir),
      stdio: "inherit",
      env: process.env,
    }),
  );
  const stop = () => {
    for (const c of children) {
      try {
        c.kill("SIGINT");
      } catch {
        /* ya terminó */
      }
    }
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

// ── Resúmenes ───────────────────────────────────────────────

function printUrls(projects, ports) {
  console.log("\n━━━━━━━━━━━━━ Paimon — URLs ━━━━━━━━━━━━━");
  for (const p of projects) {
    console.log(`  ${p.label}`);
    for (const [name, url] of p.endpoints(ports[p.name])) {
      console.log(`    ${name.padEnd(11)} → ${url}`);
    }
  }
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("Swagger → abre el enlace 'Swagger' de cada API para probarla en el navegador.");
  console.log("Logs de compose: logs/*.log");
}

function printCommands() {
  const rows = [
    ["node dev.js", "levanta todo (apps + Swagger global)"],
    ["node dev.js --audio", "solo audio_processing"],
    ["node dev.js --image", "solo image_generator"],
    ["node dev.js --processing", "solo image_processing (quita-fondo)"],
    ["node dev.js --removebg", "alias de --processing"],
    ["node dev.js --swagger", "portal Swagger global (alias --docs, --gateway)"],
    ["node dev.js --all", "todo (apps + Swagger)"],
    ["node dev.js --build", "reconstruye las imágenes al levantar"],
    ["node dev.js --logs [flags]", "sigue los logs de los seleccionados"],
    ["node dev.js --stop [flags]", "detiene los seleccionados (o todos)"],
    ["node dev.js --help", "esta ayuda"],
  ];
  const w = Math.max(...rows.map((r) => r[0].length));
  console.log("\nComandos útiles:");
  for (const [cmd, desc] of rows) console.log(`  ${cmd.padEnd(w)}  → ${desc}`);
}

function printHelp() {
  const out = [];
  out.push("Paimon — lanzador de aplicativos (Docker Compose)");
  out.push("");
  out.push("USO");
  out.push("  node dev.js [flags]");
  out.push("");
  out.push("SELECCIÓN (sin flags levanta todo)");
  out.push("  --audio            solo audio_processing   (API :8100)");
  out.push("  --image            solo image_generator    (API :8101 + ComfyUI :8188)");
  out.push("  --processing       solo image_processing   (API :8102, POST /remove-bg)");
  out.push("                       alias: --removebg, --remove-bg, --image-processing");
  out.push("  --swagger          portal Swagger global   (UI :8080, todas las APIs)");
  out.push("                       alias: --docs, --gateway, --portal");
  out.push("  --all              todo (apps + Swagger)");
  out.push("");
  out.push("MODOS");
  out.push("  --build            (re)construye las imágenes al levantar");
  out.push("  --logs [flags]     sigue los logs de los seleccionados");
  out.push("  --stop [flags]     detiene los seleccionados (o todos)");
  out.push("  --help             esta ayuda");
  out.push("");
  out.push("PUERTOS");
  out.push("  Cada API usa :8000 internamente. En el host se publican en 8100/8101/8102");
  out.push("  (o el siguiente libre), saltando los ya ocupados.");
  out.push("  Fijar con AUDIO_HOST_PORT, IMAGE_API_HOST_PORT e IMAGE_PROCESSING_HOST_PORT.");
  out.push("");
  out.push("EJEMPLOS");
  out.push("  node dev.js                    → audio + image + processing + swagger");
  out.push("  node dev.js --audio --build    → solo audio, reconstruyendo la imagen");
  out.push("  node dev.js --processing --swagger → quita-fondo + portal Swagger");
  out.push("  node dev.js --logs --image     → sigue los logs de image_generator");
  out.push("  node dev.js --stop             → detiene todo");
  out.push("");
  out.push("Logs: logs/<app>.log");
  out.push("Un flag desconocido no ejecuta nada (aborta; usa --help para ver las opciones).");
  console.log(out.join("\n"));
}

// ── Main ────────────────────────────────────────────────────

async function main() {
  const argv = process.argv.slice(2);
  const HELP = argv.includes("--help");
  const STOP = argv.includes("--stop");
  const LOGS = argv.includes("--logs");
  const BUILD = argv.includes("--build");

  if (HELP) return printHelp();

  // Flag desconocido ⇒ no se ejecuta nada (antes se interpretaba como "todos").
  const unknown = unknownFlags(argv);
  if (unknown.length) {
    console.error(`✘ Flag(s) desconocido(s): ${unknown.join(", ")} — no se levanta nada.`);
    console.error("  Usa `node dev.js --help` para ver las opciones.");
    process.exit(1);
  }

  const selected = selectProjects(argv);
  const projects = selected ?? PROJECTS;
  const label = selected ? selected.map((p) => p.label).join(" + ") : "todo";

  if (!checkDocker()) process.exit(1);

  if (STOP) {
    console.log(`🛑 Paimon — deteniendo: ${label}`);
    for (const p of projects) stopProject(p);
    return;
  }

  if (LOGS) return followLogs(projects);

  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const ports = await assignPorts(projects);
  console.log(`🧠 Paimon — aplicativos: ${label}  (logs → logs/*.log)`);
  console.log("");

  const started = [];
  for (const p of projects) {
    const extraEnv =
      p.name === "swagger"
        ? { ...gatewayTargets(ports), API_KEY: sharedApiKey() }
        : {};
    if (startProject(p, ports[p.name], { build: BUILD, extraEnv })) started.push(p);
  }

  for (const p of started) {
    const port = ports[p.name];
    process.stdout.write(`${color(p)} ⏳ esperando :${port}...`);
    const up = await waitForPort(port, UP_TIMEOUT_MS);
    console.log(up ? " ✅ listo" : ` ⚠️  no respondió en :${port} — revisa logs/${p.name}.log`);
  }

  if (started.length) printUrls(started, ports);
  console.log("\n✅ Listo. Esta terminal queda libre — los contenedores siguen en Docker.");
  printCommands();
  process.exit(0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
