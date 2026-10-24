# Acceptance checklist — iasim-qul.6

- Generated: 2026-10-24 02:08:53
- Environment: Windows-11-10.0.26200-SP0 · Python 3.12.11
- Seed: 42 · 160x45 · LAN bind 0.0.0.0 with ephemeral ports
- Result: **28 PASS · 0 FAIL · 3 SKIP**

| Check | Description | Result | Evidence |
|---|---|---|---|
| `gui.base` | Base 160x45 layout with map, panel, tabs and bottom bar | **PASS** | 160x45 render with ('AGENTES', 'EVENTOS', '[F1] Ayuda') |
| `gui.help` | F1 help and glyph/status legend | **PASS** | 160x45 render with ('AYUDA Y LEYENDA', 'ESPACIO', 'F8') |
| `gui.agent_sheet` | F2 full-screen agent sheet | **PASS** | 160x45 render with ('F2', 'Nia', 'MENTE') |
| `gui.world` | F3 full-screen world summary | **PASS** | 160x45 render with ('F3', 'MUNDO', 'AGENTES') |
| `gui.events` | F4 event log with filters and search | **PASS** | 160x45 render with ('F4', 'EVENTOS', 'TICK', 'Buscar') |
| `gui.replay` | F5 replay layout with REPLAY banner and tick | **PASS** | 160x45 render with ('REPLAY', 'TICK', 'PAUSA') |
| `gui.map` | F6 enlarged map with legend and layer help | **PASS** | 160x45 render with ('F6', 'LEYENDA', 'Cerrar mapa') |
| `gui.metrics` | F7 metrics from the exported snapshot | **PASS** | 160x45 render with ('F7', 'MÉTRICAS', 'SESIÓN') |
| `gui.settings` | F8 display settings | **PASS** | 160x45 render with ('F8', 'Paleta', 'Pantalla completa') |
| `gui.ascii` | ASCII fallback base layout | **PASS** | 160x45 render with ('AGENTES', '[F1] Ayuda') |
| `gui.inspection` | Inspection cursor details on the base layout | **PASS** | 160x45 render with ('INSPECCIÓN', 'Nia') |
| `gui.fullscreen_flag` | F11 toggles the fullscreen presentation flag | **PASS** | fullscreen=True |
| `gui.keys` | Key guide covers every full-screen view and inspection | **PASS** | 26 documented keys |
| `loopback.health` | Health endpoint answers without secrets | **PASS** | http://127.0.0.1:59903/mcp on 59903 returned /healthz |
| `loopback.waiting` | Waiting state before any agent connects | **PASS** | phase=waiting reason=no_agents |
| `loopback.unauth` | Unauthenticated join is rejected | **PASS** | transport rejected the request |
| `loopback.join` | Authenticated MCP join assigns a slot | **PASS** | agent_id=ag_01 spawn=[40, 20] |
| `loopback.disconnect` | Transport close removes the agent without a ghost | **PASS** | joined agents after close: 0 |
| `loopback.slot_reuse` | The freed slot is reusable by the same token | **PASS** | agent_id=ag_01 |
| `loopback.artifacts` | Run directory contains session artifacts | **PASS** | actions.jsonl, agents.json, events.jsonl, session.json |
| `loopback.tokens` | Tokens never appear in session logs | **PASS** | scanned events/actions/thoughts JSONL |
| `loopback.shutdown` | Server stops cleanly | **PASS** | background thread joined |
| `lan.warning` | LAN binding advertises a reachable URL and warning | **PASS** | url=http://172.30.112.1:59929/mcp warning='MCP is exposed beyond loopback over plaintext HTTP. Use bearer tokens only on a trusted LAN; use a VPN or tunnel for untrusted networks.' |
| `lan.health` | LAN-bound health endpoint answers | **PASS** | status=ok |
| `lan.auth_join` | Authenticated join through the LAN-bound server | **PASS** | agent_id=ag_01 |
| `cli.startup` | iasim serve --headless starts the world and MCP server | **PASS** | health={'status': 'ok', 'schema_version': '1.0', 'protocol_version': 'iasim-mcp/1.0', 'tick': 0, 'agents': 0, 'phase': 'waiting', 'max_agents': 2, 'joined_agents': 0, 'alive_agents': 0, 'waiting_reason': 'no_agents'} command=C:\Users\Benabhi\Documents\Code\iasim\.venv\Scripts\python.exe -m iasim serve --headless --seed 42 --max-agents 2 --host 127.0.0.1 --port 59939 --log-dir C:\Users\Benabhi\Documents\Code\iasim\tmp4n0s8hod |
| `cli.agent` | CLI server accepts an authenticated agent | **PASS** | agent_id=ag_01 |
| `cli.output` | CLI prints endpoint and warnings but no agent tokens | **PASS** | exit=1 |
| `manual.window` | Visual window: real tcod window, layout and colours on a desktop | **SKIP** | The renderer is verified at 160x45 for every view; opening the OS window needs an interactive desktop session. |
| `manual.fullscreen` | Visual F11 fullscreen switch | **SKIP** | F11 toggles the presentation flag and the terminal hook exists; the actual windowing-system switch needs a desktop session. |
| `manual.second_host` | Join from a second physical LAN host | **SKIP** | The server binds 0.0.0.0, prints LAN_WARNING and accepts an authenticated HTTP join through the loopback address; a second machine is not available in CI. |

## Residual manual items

These require an interactive desktop or a second physical host. The automated checks above cover the same server and renderer paths; confirm them visually if a desktop is available.

- **manual.window**: Visual window: real tcod window, layout and colours on a desktop — The renderer is verified at 160x45 for every view; opening the OS window needs an interactive desktop session.
- **manual.fullscreen**: Visual F11 fullscreen switch — F11 toggles the presentation flag and the terminal hook exists; the actual windowing-system switch needs a desktop session.
- **manual.second_host**: Join from a second physical LAN host — The server binds 0.0.0.0, prints LAN_WARNING and accepts an authenticated HTTP join through the loopback address; a second machine is not available in CI.
