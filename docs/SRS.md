# IASim — Especificación de Requerimientos de Software

| Campo | Valor |
|---|---|
| Proyecto | IASim — Sandbox roguelike para evaluación de agentes de AI |
| Documento | Especificación de Requerimientos de Software (SRS) |
| Versión | 0.3 — Borrador para revisión |
| Fecha | 2026-10-23 |
| Estado | Borrador |
| Autor | Equipo IASim |
| Idioma | Español (UI y documentación); identificadores MCP en inglés |

## Historial de cambios

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1 | 2026-10-23 | Definición inicial: alcance, arquitectura, simulación, MCP y fases. |
| 0.2 | 2026-10-23 | Se amplía la interfaz: panel de observabilidad, pensamientos reportados por agentes, atajos y vistas a pantalla completa. |
| 0.3 | 2026-10-23 | Se resuelven 10 preguntas de alcance: fauna y durabilidad simples, estaciones de 7 días y nieve por tile, pronóstico probabilístico, LLM compatible con OpenAI, mouse opcional, métricas JSON/CSV y consola debug `F12`. |

---

## 1. Introducción

### 1.1 Propósito

Este documento define los requerimientos funcionales y no funcionales de **IASim**, un juego roguelike de supervivencia para terminal, escrito en Python sobre `python-tcod` (libtcod), cuyo objetivo es **observar y evaluar el comportamiento de agentes de AI** en un sandbox reproducible.

IASim no implementa la inteligencia de los agentes. El juego expone un servidor **MCP (Model Context Protocol)** con el estado percibido y las acciones disponibles; cada agente externo decide qué hacer. El juego simula el mundo, valida y resuelve las acciones, y ofrece al operador humano una interfaz para entender qué ocurre y por qué.

### 1.2 Alcance

El sistema incluye:

- Un mundo 2D de isla, generado proceduralmente a partir de una semilla, contenido por completo en un mapa de **80 × 40** celdas.
- Una interfaz de terminal de **160 × 45** caracteres con dos columnas: mapa a la izquierda y observabilidad a la derecha, más una barra inferior persistente de atajos.
- Simulación por turnos (ticks) con ciclo día/noche, clima, temperatura, humedad, recursos, crafteo, inventario, combate, comunicación, alianzas, comercio y muerte permanente.
- Uno o más agentes externos (por defecto uno; máximo configurable de ocho) conectados por MCP sobre HTTP local.
- Observabilidad completa desde el punto de vista del operador: estado de cada agente, necesidades, equipo, intención y pensamiento **reportados por el agente**, acciones ejecutadas, resultados, relaciones y eventos del mundo.
- Vistas a pantalla completa para ficha de agente, resumen del mundo, registro de eventos, replay, mapa ampliado, métricas y ajustes de visualización; consola de debug del operador en `F12`.
- Registro JSONL, métricas JSON/CSV, guardado/carga y replay determinista.

### 1.3 Audiencia

- Investigadores que comparan estrategias de agentes de AI.
- Desarrolladores de agentes que integran clientes MCP.
- Operadores que configuran y observan sesiones.
- Desarrolladores del simulador y del cliente de referencia.

### 1.4 Definiciones y acrónimos

| Término | Definición |
|---|---|
| Agente | Entidad externa que controla un personaje mediante MCP. Su inteligencia no forma parte de IASim. |
| Tick / turno | Unidad de tiempo de simulación. Por defecto, 1 tick = 5 minutos de juego. |
| Turno global | Todos los agentes reciben la observación del tick, envían como máximo una acción principal y el mundo resuelve en orden determinista. |
| Observación | Datos del mundo percibidos por un agente en un tick: atributos propios, mapa visible, memoria, entidades, mensajes, acciones disponibles y deadline. |
| Percepción | Subconjunto del mundo que el agente puede ver u oír en el tick actual. |
| Memoria | Registro por agente de celdas y recursos vistos con anterioridad; puede estar desactualizado. |
| FOV | *Field of view*: campo de visión calculado por línea de visión. |
| MCP | Model Context Protocol, usado para exponer observaciones y acciones a los agentes. |
| Tool | Herramienta MCP invocable por un agente (por ejemplo, `iasim_move`). |
| Reporte de mente | Texto opcional enviado por el agente con su intención, pensamiento o plan. El juego lo muestra, pero no puede verificar ni leer la mente real del agente. |
| Pensamiento reportado | Explicación voluntaria del agente. Es dato no confiable y se muestra como “reportado por el agente”. |
| Seed | Semilla que determina la generación del mundo y los eventos aleatorios. |
| Replay | Reproducción determinista de una sesión a partir de la seed, la configuración y las acciones registradas. |
| Snapshot | Copia completa del estado de simulación en un tick, usada para guardado y búsqueda en replay. |
| Estación | Estructura requerida para ciertas recetas (por ejemplo, mesa de trabajo). |
| Bioma | Conjunto de celdas con terreno, recursos y clima característicos. En el MVP: isla boscosa con río. |
| Estado ausente | Agente conectado que superó el límite de timeouts; permanece en el mundo pero no participa del turno hasta que vuelva a responder. Si la conexión se cierra, se retira del mundo. |

### 1.5 Referencias

- Especificación MCP: <https://modelcontextprotocol.io/>
- `python-tcod`: <https://python-tcod.readthedocs.io/>
- Python 3.12: <https://docs.python.org/3.12/>
- Especificación de requisitos IEEE 830 (referencia de estructura, no obligatoria).

---

## 2. Descripción general

### 2.1 Visión del producto

IASim es un laboratorio observable. El operador inicia una isla, conecta uno o más agentes de AI y observa cómo sobreviven, exploran, craftean, cooperan, negocian o compiten. El valor principal no es “ganar”, sino **entender y comparar comportamientos** bajo condiciones reproducibles.

La interfaz debe permitir responder en segundos:

- ¿Dónde está cada agente y qué está haciendo?
- ¿Qué necesita, qué tiene equipado y qué estado lo afecta?
- ¿Qué piensa hacer y qué reportó como razón?
- ¿Qué acción ejecutó, con qué resultado y cómo cambió el mundo?
- ¿Qué clima, hora y condiciones ambientales rodean la escena?
- ¿Qué eventos recientes explican la situación actual?

### 2.2 Objetivos

| ID | Objetivo |
|---|---|
| O-01 | Simulación determinista y reproducible por seed. |
| O-02 | Supervivencia con necesidades, clima, recursos, crafteo y combate. |
| O-03 | Interfaz MCP estable, tipada y segura para agentes externos. |
| O-04 | Observabilidad completa para el operador, incluyendo intención/pensamiento reportados y acciones. |
| O-05 | Interfaz de terminal cómoda, con vista base de dos columnas y vistas a pantalla completa. |
| O-06 | Registro, métricas, guardado y replay para análisis y depuración. |
| O-07 | Arquitectura modular que permita agregar clima, contenido y modos de investigación por fases. |

### 2.3 Actores

| Actor | Descripción | Responsabilidad |
|---|---|---|
| Operador humano | Persona frente a la terminal. | Configurar, iniciar, pausar, observar, guardar, cargar, reproducir y finalizar sesiones. No controla agentes. |
| Agente AI externo | Cliente MCP. | Percibir, decidir y enviar acciones; opcionalmente reportar intención y pensamiento. |
| Agente de referencia | Bot Python incluido en el proyecto. | Validar el protocolo MCP y servir de baseline determinista. |
| Núcleo de simulación | Componente interno. | Aplicar reglas, resolver turnos, generar eventos y mantener determinismo. |
| Servidor MCP | Componente interno. | Autenticar agentes, exponer observaciones/tools, validar y encolar acciones. |
| Renderizador | Componente interno. | Dibujar la interfaz libtcod y gestionar atajos y overlays. |

### 2.4 Supuestos

- La sesión corre en una sola máquina, con agentes locales o en la misma red local.
- Cada instancia de IASim atiende una única sesión y un único puerto MCP.
- Los agentes son procesos externos; IASim no ejecuta LLMs ni decide por ellos.
- El operador dispone de una terminal de al menos 160 × 45 caracteres o una ventana escalada equivalente.
- Se utiliza una fuente monoespaciada con soporte Unicode.
- La seed, la configuración y las acciones determinan el resultado; la latencia de los agentes no altera las reglas.
- Los agentes pueden fallar, desconectarse o enviar acciones inválidas; el juego debe sobrevivir a ello.

### 2.5 Restricciones

- Python 3.12 o superior.
- `python-tcod` como motor central de consola/entrada, FOV, pathfinding y utilidades espaciales, con una versión fijada y compatible.
- El azar de la simulación no usará el RNG de `tcod`: seguirá pasando por el RNG determinista de IASim.
- SDK oficial de MCP para Python, con transporte HTTP *streamable*.
- Interfaz base fija de 160 × 45; mapa de 80 × 40.
- Español para la UI; inglés para nombres de tools, campos MCP y logs estructurados.
- Una acción principal por agente y por tick, más un `say` gratuito.
- Sin llamadas del juego a modelos de lenguaje.
- Sin gráficos 3D, audio ni multijugador por internet.
- El mundo completo cabe en el mapa; no hay scroll de cámara en el MVP.

### 2.6 Fuera de alcance

- Implementar la inteligencia, prompt o memoria de los agentes.
- Gráficos con sprites, animaciones 3D o audio.
- Multijugador humano, matchmaking o servidores en internet.
- Un dashboard web.
- Combate con armaduras complejas, sigilo avanzado o vehículos.
- Fauna compleja, depredadores y caza mayor en el MVP; en fase 2 se incluye fauna pasiva y pesca.
- Múltiples estaciones de crafteo, tecnología, electricidad o vehículos.
- Mods o scripting de contenido por terceros.
- Anti-cheat: el sandbox asume agentes cooperativos con el protocolo, pero valida todas las acciones.

---

## 3. Arquitectura y simulación

### 3.1 Arquitectura

```text
┌─────────────────────────────┐
│ Agente AI externo (MCP)     │
│  - observa, decide, actúa   │
│  - reporta intención        │
└──────────────┬──────────────┘
               │ HTTP local (MCP)
┌──────────────▼──────────────┐
│ Servidor MCP                │
│  - auth por token           │
│  - observaciones            │
│  - tools de acción          │
│  - cola y validación        │
└──────────────┬──────────────┘
               │
┌──────────────▼──────────────┐
│ Núcleo de simulación        │
│  - mundo, agentes, clima    │
│  - reglas y resolución      │
│  - RNG determinista         │
└───────┬──────────────┬──────┘
        │              │
┌───────▼──────┐ ┌─────▼──────────────┐
│ UI libtcod   │ │ Logs / métricas /   │
│ 160 × 45     │ │ snapshots / replay  │
└──────────────┘ └────────────────────┘
```

Componentes internos:

| Módulo | Responsabilidad |
|---|---|
| `core/` | Simulación pura y determinista: mundo, agentes, necesidades, combate, clima, turnos. Sin dependencia de UI ni de tipos nativos de `tcod`. |
| `world/` | Generación de isla, tiles, recursos, FOV, pathfinding y memoria; los adaptadores `tcod` convierten máscaras y rutas en datos inmutables del dominio. |
| `agents/` | Modelo de agente, atributos, estados, inventario y equipo. |
| `actions/` | Validación y resolución de acciones atómicas y compuestas. |
| `crafting/` | Recetas, estaciones y construcción. |
| `mcp_server/` | Adaptador MCP, autenticación, tools, cola de acciones y timeouts. |
| `ui/` | Consola, entrada, panel de observabilidad, overlays y atajos con `tcod`. |
| `persistence/` | Guardado, carga, snapshots, logs y replay. |
| `metrics/` | Cálculo de métricas y resumen de sesión. |
| `reference_agent/` | Cliente MCP de referencia, determinista. |

Los adaptadores `tcod` son la única frontera con la librería nativa: reciben el estado inmutable, producen posiciones o rutas ordenadas y nunca filtran arrays de `tcod` al dominio. La versión de `python-tcod` se fija en `pyproject.toml` y se cubre con pruebas doradas en Windows y Linux.

### 3.2 Ciclo de turno

1. El servidor abre el tick `t` y publica una observación por agente vivo.
2. Cada agente tiene un plazo configurable (por defecto **60 s**) para:
   - consultar información libre;
   - enviar como máximo un reporte de mente (`iasim_report_mind`);
   - enviar como máximo un `say` gratuito;
   - enviar como máximo una acción principal.
3. El turno se resuelve cuando todos los agentes activos enviaron su acción o venció el plazo.
4. Las acciones se validan y se ordenan por iniciativa:
   `iniciativa = destreza + velocidad_del_arma + 1d6(seed, tick, agente)`
5. Se resuelven en ese orden: movimiento, recolección, crafteo, construcción, uso de objetos, comercio, combate, etc. Si un agente muere antes de su acción, esta se cancela.
6. Se aplican efectos del mundo: fuego, clima, regeneración de recursos, actualización de cadáveres y actualización de memoria.
7. Se aplican necesidades y estados a cada agente; se registran muertes por causas ambientales.
8. Se calcula el estado final, se actualizan métricas, se escribe el log y se toma un snapshot si corresponde.
9. Se renderiza el nuevo estado y se avanza a `t + 1`.

Reglas adicionales:

- El servidor y la isla existen desde el arranque, sin lobby ni cuenta regresiva. Los agentes se conectan y desconectan durante la vida del servidor; el máximo de agentes concurrentes es configurable (1–8).
- Un agente existe en el mundo solo mientras su conexión MCP está abierta. Al desconectarse, se retira del mundo, se cancela su acción pendiente y su inventario cae al suelo en su posición. El slot y su token quedan libres para una conexión nueva; no se reanuda el estado del agente anterior.
- La muerte es permanente y deja un cadáver saqueable. Un agente muerto deja de actuar aunque su conexión siga abierta; si luego se desconecta, el cadáver permanece hasta que el operador finalice la sesión.
- Un agente que no responde pierde el turno (`skip`). Tras **3 timeouts consecutivos** pasa a estado `ausente` mientras siga conectado: no bloquea el turno, pero puede ser atacado o saqueado. Si la conexión se cierra, se aplica la regla de desconexión.
- Si no hay agentes conectados (o ningún agente activo), la simulación se pausa y la GUI muestra `ESPERANDO AGENTES`. El servidor y la GUI siguen abiertos para nuevas conexiones.
- Un agente puede conectarse en cualquier momento entre ticks; el servidor lo incorpora al siguiente tick con un punto de aparición libre. No hay restricciones de incorporación tardía por lobby.
- Un agente que duerme (`sleep`) no bloquea el turno: el servidor lo considera en espera automática hasta que despierte o sea interrumpido.
- La pausa del operador detiene el reloj y los plazos; los agentes no reciben nuevos ticks.
- La velocidad de UI solo cambia la cadencia de presentación, no las reglas ni la simulación headless.
- `move_to` calcula la ruta con `tcod.path` (AStar o Dijkstra determinista) y avanza un paso por tick; los empates se resuelven por coordenada para que el resultado no dependa del orden de iteración.

### 3.3 Mundo y mapa

- Isla procedural de **80 × 40** celdas, con borde de agua profunda.
- Generación determinista por seed en etapas:
  1. máscara de isla con ruido y caída radial;
  2. costa y playas;
  3. relieve y rocas;
  4. río de agua dulce desde el interior hasta la costa;
  5. bosque, pradera, matorrales y cañaverales;
  6. recursos, puntos de aparición y validación.
- Validaciones obligatorias:
  - al menos un punto de agua dulce a ≤ 15 celdas de cada aparición;
  - comida y madera accesibles a ≤ 10 celdas;
  - todas las apariciones en celdas transitables y conectadas;
  - apariciones separadas al menos 8 celdas;
  - no hay apariciones dentro de agua, roca, fuego o estructuras.
- El mapa completo es el mundo: no hay mapas secundarios ni scroll en el MVP.
- El operador puede ver el mundo completo; los agentes solo ven su percepción. El modo foco muestra la percepción del agente seleccionado.

#### 3.3.1 Tiles y glifos

| Tile | Glifo | Color base | Transitable | Transparente | Recurso / nota |
|---|---|---|---|---|---|
| Agua profunda | `≈` | Azul oscuro | No | No | Agua salada; no potable. |
| Agua poco profunda | `~` | Azul | Sí, coste 2 | Sí | Agua salada; no potable. |
| Río / agua dulce | `~` | Azul claro | Sí, coste 2 | Sí | Fuente de agua potable. |
| Arena | `·` | Arena | Sí | Sí | Transitable; palmeras y cocos. |
| Pasto | `,` | Verde | Sí | Sí | Fibra ocasional. |
| Pasto alto / juncos | `"` | Verde oscuro | Sí | Sí | Fibra y caña. |
| Árbol | `♣` | Verde bosque | No | No | Madera; ramas a mano, troncos con hacha. |
| Palmera | `♣` | Verde amarillo | No | No | Cocos en la playa; madera con hacha. |
| Arbusto | `♠` | Verde claro | Sí | Sí | Bayas; rebrota. |
| Roca / peñasco | `▲` | Gris | No | No | Piedra con pico; bloquea visión. |
| Suelo rocoso | `▒` | Gris claro | Sí | Sí | Piedra superficial a mano. |
| Arcilla | `▓` | Ocre | Sí | Sí | Arcilla junto al río. |
| Mesa de trabajo | `≡` | Marrón | No | Sí | Estación de crafteo nivel 2. |
| Campamento / refugio | `∩` | Marrón claro | Sí | Sí | Bonificación de abrigo si el agente está encima. |
| Fuego | `*` | Naranja | No | Sí | Luz y calor; consume combustible. |
| Cadáver | `☠` | Blanco grisáceo | Sí | Sí | Saqueable; desaparece al finalizar la sesión. |
| Objeto en el suelo | `!` | Según objeto | Sí | Sí | Ítem tirado o recurso suelto. |
| Agente | `@` | Amarillo/cian | — | — | El seleccionado se resalta con fondo. |
| Sin explorar (overlay FOV) | ` ` | Negro | — | — | Solo visible al activar la capa de visión. |

Notas:

- El mapa base muestra el mundo completo al operador. La tecla `V` superpone la percepción del agente seleccionado: visible, recordado y desconocido.
- Los glifos deben renderizarse con una fuente Unicode incluida o configurada. Si un glifo no existe, se usa el fallback ASCII indicado en el anexo A.
- La memoria y la percepción se describen en 3.8.

### 3.4 Tiempo, luz y clima

- **1 tick = 5 minutos** de juego (configurable).
- **288 ticks = 1 día**; la sesión comienza el Día 1 a las 06:00.
- Fases:
  - amanecer 05:00–07:00;
  - día 07:00–18:00;
  - atardecer 18:00–20:00;
  - noche 20:00–05:00.
- Factores de luz: día 1.0; amanecer/atardecer 0.65; noche 0.25; antorcha o fuego elevan el mínimo local.
- La UI muestra día, hora, fase y un indicador de luz.

#### 3.4.1 Clima del MVP

| Estado | Δ temperatura | Visibilidad | Mojadura | Notas |
|---|---:|---:|---:|---|
| Despejado | +2 °C | 1.00 | 0 | Cielo limpio. |
| Nublado | -1 °C | 0.95 | 0 | Transición frecuente. |
| Lluvia | -3 °C | 0.80 | +1.5/tick | Aumenta frío y reduce visión. |
| Tormenta | -5 °C | 0.60 | +2.5/tick | Viento 8–10; fuegos expuestos pueden apagarse. |
| Niebla | -2 °C | 0.40 | +0.5/tick | Más frecuente al amanecer. |
| Nieve | -8 °C | 0.50 | +1.0/tick | Fase 2; acumulación y coste de movimiento. |

- El viento es un modificador de 0 a 10 independiente del estado. A partir de 6 reduce la visibilidad un 10 %; a partir de 8 aumenta el consumo de combustible de fuegos expuestos.
- Transiciones: cada 12–72 ticks, con tabla de probabilidades configurable y duración mínima. Todo uso de azar pasa por el RNG determinista.
- Temperatura ambiente:
  - base 22 °C;
  - oscilación diaria de ±6 °C (mínimo a las 05:00, máximo a las 15:00);
  - modificador del clima;
  - enfriamiento por viento `-0.15 × viento`;
  - la lluvia y la ropa mojada amplifican la pérdida de calor.
- Mojadura:
  - aumenta con lluvia/tormenta y al entrar al agua;
  - disminuye al aire libre, bajo refugio y cerca de fuego;
  - por encima de 60 acelera el enfriamiento.
- Fuego:
  - combustible 0–100; consume según viento y lluvia;
  - ilumina radio 5 y calienta radio 2;
  - se recarga con madera;
  - puede apagarse por lluvia/tormenta si no está bajo refugio.
- Refugio:
  - reduce mojadura y viento;
  - mejora la temperatura efectiva;
  - no bloquea ataques.
- Nieve y estaciones (primavera, verano, otoño, invierno) pertenecen a la fase 2:
  - cada estación dura **7 días** por defecto (configurable);
  - la nieve se acumula por tile (0–100), reduce la visión y aumenta el coste de movimiento;
  - se derrite con temperatura > 0 °C y cambia el aspecto de los biomas;
  - el pronóstico es **probabilístico**: horizonte de 3–6 ticks, con probabilidades y margen de error; no revela el estado futuro exacto.

### 3.5 Agentes y atributos

Cada agente tiene identidad, posición, atributos, estados, inventario, equipo, memoria, intención reportada e historial de acciones.

#### 3.5.1 Atributos

| Atributo | Rango | Inicial | Cambio por tick | Efecto |
|---|---|---:|---:|---|
| Salud | 0–100 | 100 | Según daño, necesidades y temperatura | 0 = muerte. |
| Hambre | 0–100 | 15 | +0.35 × actividad × resistencia | >70 penaliza; 100 causa daño. |
| Sed | 0–100 | 15 | +0.60 × actividad × calor | >70 penaliza; 100 causa daño. |
| Energía | 0–100 | 80 | -0.25 × actividad (despierto) | <20 penaliza; 0 fuerza descanso. |
| Temperatura corporal | 34–42 °C | 37.0 | Modelo térmico | <35 hipotermia; >40 golpe de calor. |
| Mojadura | 0–100 | 0 | Clima, agua, fuego, refugio | Acelera enfriamiento; >60 estado “mojado”. |
| Visión base | 3–12 | 8 | — | Radio de FOV; modificado por luz/clima. |
| Fuerza | 1–10 | 5 | — | Capacidad de carga y daño cuerpo a cuerpo. |
| Destreza | 1–10 | 5 | — | Iniciativa, precisión, huida y crafteo. |
| Resistencia | 1–10 | 5 | — | Desgaste de necesidades y tolerancia térmica. |

- La “inteligencia” no es un atributo simulado: la aporta el agente externo.
- Los valores iniciales pueden configurarse por perfil. La variación por seed es opcional y, si se usa, es determinista (±1).
- Capacidad de carga: `10 + 2 × fuerza` kg.
- La UI muestra los valores con una barra y el número. Los estados se muestran como etiquetas, no solo por color.

#### 3.5.2 Necesidades y fórmulas base

Los valores internos se guardan en enteros escalados (centésimas) para favorecer el determinismo entre plataformas.

```text
hambre   += 0.35 × factor_actividad × (1 - 0.03 × (resistencia - 5))
sed      += 0.60 × factor_actividad × factor_calor
energia  -= 0.25 × factor_actividad
```

- `factor_actividad`: descansar 0.5; caminar 1.0; recolectar/craftar 1.2; combatir 1.5; dormir 0.3.
- `factor_calor`: `1 + max(0, (temperatura_ambiente - 20) / 20)`.
- Comer/dormir reducen hambre/energía según el objeto/acción.
- Beber reduce sed según la fuente o recipiente.
- La salud se recupera lentamente solo si las necesidades están estables y la temperatura es normal.

#### 3.5.3 Estados

| Estado | Disparador | Efecto | Curación |
|---|---|---|---|
| Hambriento | Hambre > 70 | Fuerza -1; salud -0.02/tick | Comer. |
| Inanición | Hambre = 100 | Salud -0.20/tick; fuerza -2 | Comer. |
| Sediento | Sed > 70 | Destreza -1 | Beber. |
| Deshidratado | Sed = 100 | Salud -0.40/tick; visión -1 | Beber. |
| Agotado | Energía < 20 | Destreza -1; visión -1 | Descansar/dormir. |
| Hipotermia | Temp. corporal < 35 °C | Salud -0.20/tick; destreza -2 | Fuego, refugio, ropa seca. |
| Golpe de calor | Temp. corporal > 40 °C | Salud -0.30/tick; energía -0.20/tick | Sombra, agua, descanso. |
| Mojado | Mojadura > 60 | Mayor pérdida térmica | Fuego/refugio; secarse. |
| Sangrando | Herida de combate | Salud -0.20/tick | Venda. |
| Descansado | Durmió ≥ 6 h | +1 destreza temporal | Se pierde al agotarse. |

- La muerte se produce cuando la salud llega a 0. La causa se registra y se muestra en la UI y en las métricas.
- Un agente dormido despierta si recibe daño o si un agente hostil visible se acerca a 3 celdas.

### 3.6 Inventario y objetos

- Capacidad: `10 + 2 × fuerza` kg (20 kg con fuerza 5).
- Slots: 10; una mochila suma 6 slots y 10 kg.
- Ítems apilables: bayas, fibra, piedra, madera, caña, arcilla.
- Equipo: mano/herramienta, cuerpo, espalda, luz. Un arma equipada determina el ataque.
- Al morir, todos los ítems caen al suelo con el cadáver y pueden saquearse.
- No hay durabilidad en el MVP. En fase 2, las herramientas tienen una durabilidad simple: un contador de usos y se rompen al llegar a cero; la reparación queda para una iteración posterior.

| Objeto | Peso | Apilable | Fuente | Uso |
|---|---:|---|---|---|
| Madera | 1.0 | Sí | Árbol/palmera | Crafteo, fuego. |
| Fibra | 0.1 | Sí | Pasto, juncos | Cuerdas, vendas, ropa. |
| Piedra | 0.8 | Sí | Suelo rocoso, peñasco | Crafteo. |
| Baya | 0.05 | Sí | Arbusto | Comida: hambre -15. |
| Coco | 0.4 | Sí | Palmera | Comida: hambre -8; sed -5. |
| Caña | 0.2 | Sí | Juncos | Crafteo, refugio. |
| Arcilla | 0.5 | Sí | Orilla del río | Recipientes. |
| Piedra afilada | 0.3 | Sí | Crafteo | Componente. |
| Lanza de piedra | 2.0 | No | Crafteo | Arma melee: 7 daño. |
| Hacha de piedra | 2.0 | No | Crafteo | Tala eficiente; arma: 6 daño. |
| Pico de piedra | 2.0 | No | Crafteo | Minería de peñascos. |
| Antorcha | 0.5 | No | Crafteo | Luz +3; dura 120 ticks. |
| Venda | 0.1 | Sí | Crafteo | Detiene sangrado. |
| Odre | 0.5 | No | Crafteo | 3 cargas de agua. |
| Mochila | 1.0 | No | Crafteo | +6 slots, +10 kg. |
| Ropa de fibra | 1.0 | No | Crafteo | Aislamiento térmico leve. |
| Kit de campamento | 3.0 | No | Crafteo | Construye un fuego. |
| Kit de refugio | 4.0 | No | Crafteo | Construye un refugio. |
| Kit de mesa | 4.0 | No | Crafteo | Construye una mesa de trabajo. |

### 3.7 Crafteo y construcción

- Recetas de nivel 1: a mano.
- Recetas de nivel 2: requieren estar a ≤ 1 celda de una mesa de trabajo.
- El crafteo consume la acción del tick y los materiales; no hay probabilidad de fallo en el MVP.
- La construcción coloca una estructura en una celda adyacente transitable y libre.
- Recursos regenerables: arbustos (bayas) y ramas de árbol; los peñascos y la piedra superficial son finitos por celda.
- Un recurso regenerable agotado vuelve 288 ticks después (un día con la configuración por defecto), hasta su cantidad original; no crea nodos nuevos ni duplica los existentes.

| Receta | Nivel | Estación | Ingredientes | Resultado |
|---|---:|---|---|---|
| Piedra afilada | 1 | — | 2 piedra | 1 piedra afilada |
| Venda | 1 | — | 2 fibra | 1 venda |
| Antorcha | 1 | — | 1 madera + 2 fibra | 1 antorcha |
| Lanza de piedra | 1 | — | 1 madera + 1 piedra afilada + 2 fibra | 1 lanza |
| Ropa de fibra | 1 | — | 4 fibra | 1 ropa |
| Odre | 1 | — | 3 fibra + 2 arcilla | 1 odre |
| Kit de campamento | 1 | — | 5 madera + 3 piedra | 1 kit de campamento |
| Kit de mesa | 1 | — | 6 madera + 4 piedra | 1 kit de mesa |
| Hacha de piedra | 2 | Mesa | 1 madera + 2 piedra + 1 piedra afilada + 1 fibra | 1 hacha |
| Pico de piedra | 2 | Mesa | 1 madera + 3 piedra + 2 fibra | 1 pico |
| Mochila | 2 | Mesa | 4 fibra + 2 caña | 1 mochila |
| Kit de refugio | 2 | Mesa | 8 madera + 6 fibra + 4 caña | 1 kit de refugio |

- La mesa se construye sin estación; luego habilita las recetas de nivel 2.
- El fuego y el refugio son estructuras de una celda.
- Cocinar, secar y fabricar con fuego pertenecen a la fase 2.

### 3.8 Percepción y memoria

- FOV calculado con `tcod.map.compute_fov` usando *shadowcasting* determinista, línea de visión y paredes visibles (`light_walls`).
- Radio efectivo:
  `visión_base × factor_luz × factor_clima + bonificación_antorcha`.
- Árboles, peñascos y estructuras opacas bloquean la visión. Arbustos y pasto alto no. Las paredes visibles aparecen, pero ocultan las celdas posteriores.
- Cada agente mantiene memoria de:
  - tiles vistos;
  - recursos vistos y tick de última observación;
  - estructuras y cadáveres vistos;
  - agentes vistos por última vez.
- La memoria puede quedar desactualizada: un recurso recordado puede haber sido recolectado.
- La observación incluye solo lo visible y las actualizaciones de memoria; nunca el mapa completo.
- El operador puede ver el mapa completo. Al enfocar un agente, el mapa muestra únicamente su FOV y memoria; `V` alterna entre el foco del agente y el mapa completo del operador.
- El agente puede inspeccionar una entidad visible para obtener detalles (estado aproximado, equipo visible, relación).
- Los mensajes se oyen en radio 8; el ruido de combate se registra en radio 12.

### 3.9 Comunicación, alianzas y comercio

- `say`: mensaje de texto libre, máximo 280 caracteres, radio 8, una vez por tick y **no consume** la acción principal.
- Sin `target_id`, el mensaje se entrega a todos los agentes vivos en radio 8; con `target_id`, solo a ese agente si está en radio.
- El mensaje se entrega al inicio del tick siguiente a los agentes en rango. El operador lo ve de inmediato en el log.
- No hay chat global.
- Los pensamientos reportados **no** se comparten automáticamente con otros agentes; el operador los ve, los demás solo ven lo que el agente decide comunicar.
- Alianzas:
  - `offer_alliance`, `accept_alliance`, `break_alliance`;
  - `offer_alliance` y `accept_alliance` requieren radio social 8; `break_alliance` no requiere cercanía;
  - la oferta no vence: queda visible para ambos hasta que se acepta, se retira o se rechaza;
  - `break_alliance` sobre una oferta pendiente la retira (el proponente) o la rechaza (el destinatario);
  - cada pareja de agentes tiene como máximo una alianza vigente;
  - estado visible en la UI;
  - no imponen cooperación ni impiden atacar;
  - atacar a un aliado se registra como traición para métricas.
- Comercio:
  - `offer_trade` con ítems ofrecidos y solicitados;
  - debe estar a ≤ 2 celdas del destinatario; el rango se revalida al aceptar;
  - una oferta hecha en el tick `T` vale en `T+1`…`T+4` y caduca al llegar a `T+5`;
  - `accept_trade` ejecuta un intercambio atómico; si falta un ítem o cambió el inventario, falla y la oferta queda abierta hasta vencer;
  - `decline_trade` cancela.
- No hay reputación numérica ni confianza mecánica: las alianzas son un estado social declarado y las traiciones se registran solo para métricas. La confianza debe emerger de la interacción entre agentes, no de una puntuación del juego.
- El texto de chat y de pensamiento es dato no confiable: se sanea, se trunca y nunca se ejecuta.

### 3.10 Combate y muerte

- `attack`: cuerpo a cuerpo contra un objetivo adyacente.
- `throw`: piedra a un objetivo a ≤ 4 celdas con línea de visión; la piedra se consume al ejecutarse el lanzamiento, también si falla el impacto, pero no si la acción se rechaza.
- Probabilidad de impacto:
  `0.65 + 0.04 × (destreza_atacante - destreza_defensor) - 0.10 × (distancia - 1)`, limitada a 0.25–0.95.
- Daño:
  `daño_base_arma + floor(fuerza / 2) + rng(-1..1)`, mínimo 1.
- Armas del MVP: puños 2, lanza 7, hacha 6, piedra arrojada 3.
- 25 % de probabilidad de causar sangrado al impactar.
- `flee`: intenta alejarse 2 celdas del objetivo; si el camino está bloqueado, 1; consume energía.
- `defend`: no se incluye en el MVP.
- La muerte es permanente y no hay respawn.
- Al morir:
  - el agente sale del orden de turnos;
  - deja un cadáver `☠` con todo su inventario;
  - el cadáver es saqueable con `loot`;
  - la causa y el autor se registran.
- Cuando no queda ningún agente vivo, la simulación se pausa y la GUI muestra el estado de espera. El servidor sigue abierto y el operador decide cuándo terminar o iniciar un mundo nuevo.
- No hay fauna hostil en el MVP; el combate es entre agentes. En fase 2 se agrega fauna pasiva y pesca como fuentes de alimento; los depredadores complejos quedan fuera de alcance.

### 3.11 Sesión y servidor abierto

- El comando principal (`iasim`; alias `iasim serve` y `python -m iasim`) genera el mundo, abre la GUI completa del operador (vista 160 × 45 con mapa, panel derecho por pestañas y barra inferior) y levanta el servidor MCP. La isla y la GUI son visibles desde el inicio, aunque no haya agentes.
- No hay lobby, mínimo obligatorio ni cuenta regresiva. El operador configura el máximo de agentes concurrentes (1–8); los agentes pueden conectarse y desconectarse mientras el servidor esté vivo.
- El tick 0 es el estado inicial del mundo. La simulación no avanza mientras no haya agentes conectados o activos; al entrar un agente, la GUI lo muestra y el reloj continúa.
- El operador puede pausar, cambiar velocidad, guardar, abrir vistas y finalizar el servidor. La GUI es la vista del operador: muestra el mundo completo y a todos los agentes conectados; los agentes siguen recibiendo solo su percepción.
- El fin normal es una acción explícita del operador (o el cierre del proceso). La muerte del último agente no finaliza el servidor: deja el cadáver, pausa la simulación y muestra el estado de espera; una conexión nueva puede entrar si hay un slot libre.
- Al finalizar se escribe un resumen con métricas, causas de muerte y hash final, y se conservan los logs de la sesión.
- `R`/reinicio, si está disponible en la GUI, inicia un mundo nuevo con la misma configuración y una seed nueva o la indicada. También se puede reiniciar el proceso.
- Guardar/cargar permite continuar una sesión; los agentes muertos siguen muertos y los desconectados no se restauran como presentes.

---

## 4. Requerimientos funcionales

Leyenda de prioridad:

- **M**: obligatorio para el MVP.
- **S**: deseable para el MVP.
- **C**: previsto para una fase posterior.
- Fase: **F0** fundaciones, **F1** MVP, **F2** contenido ampliado, **F3** investigación avanzada.

### 4.1 Sesión y configuración (RF-100)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-101 | El sistema debe cargar configuración desde TOML y permitir sobrescritura por CLI. | M | F0 |
| RF-102 | El sistema debe iniciar en modo UI (160 × 45) o headless con la misma simulación. | M | F1 |
| RF-103 | El sistema debe generar el mundo de forma determinista a partir de una seed. | M | F0 |
| RF-104 | El sistema debe iniciar el mundo, la GUI y el servidor MCP sin esperar un mínimo de agentes, y aceptar conexiones hasta el máximo configurado. | M | F1 |
| RF-105 | El sistema debe permitir pausar y reanudar la simulación sin perder estado. | M | F1 |
| RF-106 | El sistema debe permitir ajustar la velocidad de presentación sin alterar las reglas. | M | F1 |
| RF-107 | El sistema debe mantener el servidor y la GUI disponibles cuando no queden agentes conectados o vivos, pausando la simulación hasta una nueva conexión o el cierre del operador. | M | F1 |
| RF-108 | El sistema debe permitir al operador iniciar un mundo nuevo sin reiniciar necesariamente el proceso. | M | F1 |
| RF-109 | El sistema debe permitir que los agentes se conecten y desconecten durante la sesión, hasta el máximo configurado. | M | F1 |
| RF-110 | El sistema debe registrar metadatos de sesión: seed, configuración, versiones y hora de inicio. | M | F1 |
| RF-111 | El sistema debe permitir exponer el servidor MCP en la LAN mediante configuración explícita, exigiendo token y mostrando la URL y una advertencia de seguridad. | M | F1 |
| RF-112 | El sistema debe eliminar del mundo a un agente cuando su conexión MCP se cierra, liberar su slot y dejar su inventario en el suelo o su cadáver si murió. | M | F1 |
| RF-113 | La GUI del operador debe mostrar en vivo a los agentes conectados, su estado y su actividad. | M | F1 |

### 4.2 Mundo (RF-200)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-201 | El sistema debe generar una isla transitable y conectada de 80 × 40. | M | F0 |
| RF-202 | La generación debe incluir costa, río de agua dulce, bosque, pradera, rocas y recursos. | M | F1 |
| RF-203 | La generación debe validar agua, comida, madera y apariciones; si falla, debe reintentar determinísticamente. | M | F0 |
| RF-204 | El mapa debe renderizar todos los tiles con glifos Unicode y colores distinguibles. | M | F1 |
| RF-205 | El sistema debe mostrar leyenda de glifos y colores en la ayuda y en el mapa ampliado. | S | F1 |
| RF-206 | Los recursos deben ser recolectables y algunos deben regenerarse. | M | F1 |
| RF-207 | El mundo completo debe caber en el mapa, sin scroll ni mapas secundarios. | M | F1 |
| RF-208 | La generación y los recursos deben ser idénticos para la misma seed y configuración. | M | F0 |

### 4.3 Tiempo y clima (RF-300)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-301 | El sistema debe simular un ciclo día/noche de 288 ticks (configurable). | M | F1 |
| RF-302 | El sistema debe mostrar día, hora, fase y factor de luz en la UI. | M | F1 |
| RF-303 | El sistema debe simular despejado, nublado, lluvia, tormenta y niebla. | M | F1 |
| RF-304 | El sistema debe simular viento, temperatura ambiente y mojadura. | M | F1 |
| RF-305 | El clima debe afectar visión, temperatura corporal, mojadura y fuegos. | M | F1 |
| RF-306 | El sistema debe incluir fuego, refugio y ropa como mitigaciones térmicas. | M | F1 |
| RF-307 | El sistema debe superponer lluvia y viento en el mapa sin ocultar entidades en el MVP; la nieve se suma en F2. | S | F1 |
| RF-308 | El sistema debe simular nieve con acumulación por tile y estaciones de 7 días (configurable) en fase 2. | S | F2 |
| RF-309 | El sistema debe permitir configurar la tabla de transiciones climáticas y la duración de estación. | S | F2 |
| RF-310 | El sistema debe ofrecer un pronóstico probabilístico de 3–6 ticks, sin revelar el estado futuro exacto. | S | F2 |

### 4.4 Agentes y atributos (RF-400)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-401 | El sistema debe modelar salud, hambre, sed, energía, temperatura, mojadura, visión, fuerza, destreza y resistencia. | M | F1 |
| RF-402 | Las necesidades deben evolucionar por tick según actividad, clima y resistencia. | M | F1 |
| RF-403 | El sistema debe aplicar estados y umbrales de hambre, sed, energía y temperatura. | M | F1 |
| RF-404 | El sistema debe permitir configurar perfiles iniciales de atributos. | S | F1 |
| RF-405 | El sistema debe soportar entre 1 y 8 agentes (configurable). | M | F1 |
| RF-406 | Cada agente debe tener un punto de aparición distinto y validado. | M | F1 |
| RF-407 | El sistema no debe simular inteligencia ni tomar decisiones por el agente. | M | F1 |
| RF-408 | El sistema debe permitir que el agente reporte intención, pensamiento y plan. | M | F1 |
| RF-409 | El sistema debe registrar los reportes de mente en un archivo JSONL. | M | F1 |
| RF-410 | El sistema debe mostrar los reportes como “reportado por el agente”, sin tratarlos como verdad. | M | F1 |

### 4.5 Percepción y memoria (RF-500)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-501 | El sistema debe calcular FOV con `tcod.map.compute_fov` usando shadowcasting determinista. | M | F1 |
| RF-502 | La visión debe verse afectada por luz, clima, antorcha, fuego y bloqueos. | M | F1 |
| RF-503 | Cada agente debe mantener memoria de tiles, recursos, estructuras y agentes vistos. | M | F1 |
| RF-504 | La observación MCP debe incluir solo lo visible y las actualizaciones de memoria. | M | F1 |
| RF-505 | El sistema no debe exponer el mapa completo a los agentes. | M | F1 |
| RF-506 | El sistema debe incluir agentes e ítems visibles en la observación. | M | F1 |
| RF-507 | El sistema debe permitir inspeccionar entidades visibles. | S | F1 |
| RF-508 | El sistema debe marcar recursos recordados como potencialmente desactualizados. | S | F1 |
| RF-509 | Al enfocar un agente, el mapa debe mostrar únicamente su FOV/memoria; el operador debe poder alternar entre ese foco y el mapa completo. | M | F1 |
| RF-510 | El operador debe poder inspeccionar tiles y entidades con un cursor. | S | F1 |

### 4.6 Acciones e inventario (RF-600)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-601 | Cada agente debe poder enviar como máximo una acción principal por tick. | M | F1 |
| RF-602 | El sistema debe permitir un `say` gratuito por tick. | M | F1 |
| RF-603 | El sistema debe permitir movimiento en 8 direcciones y espera. | M | F1 |
| RF-604 | El sistema debe ofrecer movimiento compuesto `move_to` que avanza un paso por tick. | S | F1 |
| RF-605 | El sistema debe permitir recolectar recursos según herramienta y tile. | M | F1 |
| RF-606 | El sistema debe permitir recoger y soltar ítems. | M | F1 |
| RF-607 | El sistema debe permitir comer, beber y rellenar odres. | M | F1 |
| RF-608 | El sistema debe permitir descansar y dormir. | M | F1 |
| RF-609 | El sistema debe permitir equipar, desequipar y usar ítems. | M | F1 |
| RF-610 | El sistema debe permitir craftear y construir. | M | F1 |
| RF-611 | El sistema debe permitir saquear cadáveres. | M | F1 |
| RF-612 | Toda acción debe validar tick, propiedad, rango, visibilidad, requisitos e inventario. | M | F1 |
| RF-613 | Toda acción debe devolver un resultado y generar eventos observables. | M | F1 |
| RF-614 | Las acciones pueden incluir una razón breve para el log. | S | F1 |
| RF-615 | Las acciones del agente deben ser idempotentes por `request_id`. | S | F1 |

### 4.7 Crafteo y construcción (RF-700)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-701 | El sistema debe incluir recetas de nivel 1 a mano y nivel 2 con mesa de trabajo. | M | F1 |
| RF-702 | El sistema debe validar ingredientes, estación, adyacencia e inventario. | M | F1 |
| RF-703 | El sistema debe permitir construir fuego, mesa y refugio. | M | F1 |
| RF-704 | El fuego debe consumir combustible, iluminar, calentar y apagarse con lluvia. | M | F1 |
| RF-705 | El sistema debe aplicar bloqueos por herramienta: hacha para troncos, pico para peñascos. | M | F1 |
| RF-706 | El sistema debe permitir recolección manual limitada de ramas, piedra superficial y cocos. | M | F1 |
| RF-707 | En fase 2, las herramientas deben tener durabilidad simple por usos y romperse al llegar a cero, sin reparación. | S | F2 |
| RF-708 | Cocinar y secar alimentos queda para fase 2. | C | F2 |
| RF-709 | Arcos y flechas quedan para fase 2. | C | F2 |

### 4.8 Comunicación, alianzas y comercio (RF-800)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-801 | El sistema debe entregar mensajes locales en radio 8 a los agentes en rango. | M | F1 |
| RF-802 | El sistema debe limitar y sanear el texto de chat y pensamientos. | M | F1 |
| RF-803 | El sistema debe permitir ofrecer, aceptar y romper alianzas. | M | F1 |
| RF-804 | El sistema debe permitir ofrecer, aceptar y rechazar intercambios. | M | F1 |
| RF-805 | El intercambio debe ser atómico, validar rango y vencer a los 5 ticks. | M | F1 |
| RF-806 | Las alianzas no deben impedir ataques ni imponer cooperación. | M | F1 |
| RF-807 | El sistema debe registrar traiciones, mensajes e intercambios en métricas. | M | F1 |
| RF-808 | La UI debe mostrar alianzas, ofertas activas y últimos mensajes del agente seleccionado. | S | F1 |
| RF-809 | Los pensamientos reportados no deben compartirse automáticamente entre agentes. | M | F1 |
| RF-810 | No debe existir chat global en el MVP. | M | F1 |

### 4.9 Combate y muerte (RF-900)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-901 | El sistema debe permitir ataque melee adyacente con arma equipada. | M | F1 |
| RF-902 | El sistema debe permitir arrojar piedras a ≤ 4 celdas. | M | F1 |
| RF-903 | El sistema debe calcular impacto y daño con destreza, fuerza, arma y distancia. | M | F1 |
| RF-904 | El sistema debe permitir huir y aplicar sangrado con venda. | M | F1 |
| RF-905 | La muerte debe ser permanente y generar un cadáver saqueable. | M | F1 |
| RF-906 | El sistema debe registrar autor, causa y tick de cada muerte. | M | F1 |
| RF-907 | La muerte del último agente vivo no debe finalizar el servidor; la simulación queda esperando y el operador decide cuándo terminar o reiniciar. | M | F1 |
| RF-908 | La UI debe mostrar cadáveres, causa de muerte y botín disponible. | M | F1 |
| RF-909 | En fase 2 se agrega fauna pasiva y pesca como alimento; depredadores complejos y NPCs sociales quedan fuera de alcance. | S | F2 |
| RF-910 | Armaduras, infecciones y heridas avanzadas quedan para fase 2. | C | F2 |

### 4.10 MCP (RF-1000)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-1001 | El servidor MCP debe escuchar por HTTP en loopback por defecto (`127.0.0.1:8765`) y permitir LAN solo con configuración explícita. | M | F0 |
| RF-1002 | Cada slot de agente debe autenticarse con un token Bearer estable mientras el servidor vive; al desconectarse el agente, el token/slot queda libre para una conexión nueva. | M | F1 |
| RF-1003 | El sistema debe exponer `iasim_join`, `iasim_observe` y `iasim_wait_for_tick`. | M | F1 |
| RF-1004 | El sistema debe exponer tools para todas las acciones del juego. | M | F1 |
| RF-1005 | El sistema debe validar y encolar una acción principal por tick. | M | F1 |
| RF-1006 | El sistema debe rechazar acciones con tick vencido o agente incorrecto. | M | F1 |
| RF-1007 | El sistema debe aplicar timeout, skip y estado ausente. | M | F1 |
| RF-1008 | El sistema debe devolver errores estructurados y códigos estables. | M | F1 |
| RF-1009 | El sistema debe soportar `iasim_report_mind` una vez por tick. | M | F1 |
| RF-1010 | El sistema debe limitar la tasa de llamadas y el tamaño de mensajes. | S | F1 |
| RF-1011 | El sistema debe exponer un endpoint de salud fuera de MCP. | S | F1 |
| RF-1012 | El servidor no debe exponer tools de administración ni acceso al mapa completo. | M | F1 |
| RF-1013 | El sistema debe registrar todas las llamadas de acción y sus resultados. | M | F1 |
| RF-1014 | El sistema debe fijar y documentar la versión del protocolo y del esquema. | M | F1 |
| RF-1015 | Un agente desconectado debe retirarse del mundo y liberar su slot/token; una conexión nueva puede ocupar ese slot, sin reanudar el estado anterior. | M | F1 |
| RF-1016 | El sistema debe aceptar y acumular por agente el uso de IA reportado (modelo, esfuerzo, tokens de entrada/salida y costo) sin alterar la simulación. | S | F1 |

### 4.11 Interfaz de usuario (RF-1100)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-1101 | La vista base debe ser de 160 × 45 con mapa 80 × 40 a la izquierda. | M | F1 |
| RF-1102 | El panel derecho debe mostrar todos los agentes y el estado del mundo. | M | F1 |
| RF-1103 | El panel derecho debe mostrar la ficha compacta del agente seleccionado. | M | F1 |
| RF-1104 | El panel derecho debe mostrar intención, pensamiento, plan y última acción reportados. | M | F1 |
| RF-1105 | El panel derecho debe mostrar inventario, equipo, estados, alianzas y últimas relaciones. | M | F1 |
| RF-1106 | El panel derecho debe mostrar día, hora, clima, temperatura, viento y visibilidad. | M | F1 |
| RF-1107 | Debe existir un ticker de eventos bajo el mapa y un feed reciente en el panel derecho. | M | F1 |
| RF-1108 | La barra inferior debe permanecer visible y ofrecer atajos contextuales. | M | F1 |
| RF-1109 | Debe existir una vista de ayuda con todos los atajos, glifos y estados. | M | F1 |
| RF-1110 | Debe existir una ficha de agente a pantalla completa con estadísticas, mente, inventario y relaciones. | M | F1 |
| RF-1111 | Debe existir una vista de mundo a pantalla completa con tabla de agentes y clima. | M | F1 |
| RF-1112 | Debe existir un registro de eventos a pantalla completa con filtros y búsqueda. | M | F1 |
| RF-1113 | Debe existir una vista de mapa ampliado a pantalla completa. | M | F1 |
| RF-1114 | Debe existir una vista de métricas y resumen de sesión. | S | F1 |
| RF-1115 | Debe existir una vista de ajustes de visualización (paleta, escala, overlays). | S | F1 |
| RF-1116 | El operador debe poder seleccionar agentes por número y ciclar con Tab. | M | F1 |
| RF-1117 | El operador debe poder pausar, cambiar velocidad, abrir ayuda y salir con atajos. | M | F1 |
| RF-1118 | El operador debe poder activar las capas de visión y clima. | S | F1 |
| RF-1119 | El operador debe poder inspeccionar tiles y entidades con cursor. | S | F1 |
| RF-1120 | La UI debe indicar timeouts, desconexiones, muertes y esperas. | M | F1 |
| RF-1121 | La UI debe mostrar el estado de agentes muertos y permitir inspeccionar su cadáver. | M | F1 |
| RF-1122 | La UI debe renderizar con fuente Unicode y ofrecer fallback ASCII. | M | F1 |
| RF-1123 | La UI debe usar etiquetas además de color para no depender solo del color. | S | F1 |
| RF-1124 | La UI debe permitir alternar pantalla completa del sistema con F11. | S | F1 |
| RF-1125 | El operador no debe poder controlar las acciones de los agentes. | M | F1 |
| RF-1126 | La UI debe estar en español y los identificadores MCP en inglés. | M | F1 |
| RF-1127 | La UI debe permitir mouse opcional para seleccionar agentes y tiles en F2; toda función crítica debe seguir teniendo atajo de teclado. | S | F2 |
| RF-1128 | El operador debe disponer de una consola de debug (`F12`) para inyectar recursos, clima, hora y teletransporte, sin exponerla por MCP. | S | F2 |
| RF-1129 | La ficha del agente debe mostrar el uso de IA reportado: modelo, esfuerzo, tokens de entrada/salida/total y costo aproximado en USD. | S | F1 |

### 4.12 Persistencia, replay y métricas (RF-1200)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-1201 | El sistema debe guardar el estado completo de la sesión. | M | F1 |
| RF-1202 | El sistema debe cargar una sesión guardada y continuar desde el mismo tick. | M | F1 |
| RF-1203 | El sistema debe guardar configuración, seed, RNG, agentes, mundo y estructuras. | M | F1 |
| RF-1204 | El sistema debe registrar eventos en JSONL. | M | F1 |
| RF-1205 | El sistema debe registrar acciones y resultados en JSONL. | M | F1 |
| RF-1206 | El sistema debe registrar pensamientos reportados en JSONL. | M | F1 |
| RF-1207 | El sistema debe permitir replay determinista desde seed + acciones. | M | F1 |
| RF-1208 | El sistema debe tomar snapshots periódicos para buscar en el replay. | M | F1 |
| RF-1209 | El sistema debe calcular un hash canónico del estado por tick. | M | F1 |
| RF-1210 | El sistema debe generar un resumen de métricas por agente y por sesión. | M | F1 |
| RF-1211 | El sistema debe permitir reproducir la sesión actual desde la UI. | M | F1 |
| RF-1212 | El sistema debe permitir buscar un tick en el replay usando snapshots. | S | F2 |
| RF-1213 | El sistema debe permitir comparar métricas de dos corridas. | C | F2 |
| RF-1214 | El sistema debe exportar métricas a CSV en el MVP, además de JSON. | M | F1 |
| RF-1215 | El sistema debe hacer autoguardado configurable. | S | F1 |
| RF-1216 | El sistema debe registrar las inyecciones de debug en `debug.jsonl` y en el flujo reproducible del replay. | M | F2 |

### 4.13 Headless, testing y referencia (RF-1300)

| ID | Requerimiento | Prioridad | Fase |
|---|---|---|---|
| RF-1301 | El modo headless debe ejecutar la misma simulación sin abrir ventana. | M | F1 |
| RF-1302 | El proyecto debe incluir un agente de referencia determinista que use MCP. | M | F1 |
| RF-1303 | El agente de referencia debe reportar intención y pensamiento. | S | F1 |
| RF-1304 | Debe haber tests unitarios de mundo, necesidades, FOV, crafteo, combate y persistencia. | M | F1 |
| RF-1305 | Debe haber tests de integración MCP: join, observe, acción, timeout, desconexión y reutilización de slot. | M | F1 |
| RF-1306 | Debe haber tests de seed dorada y hash de estado. | M | F1 |
| RF-1307 | Debe haber un test de rendimiento con 8 agentes y 1000 ticks. | S | F1 |
| RF-1308 | Debe existir un harness de benchmarks multi-seed. | C | F2 |
| RF-1309 | Debe existir un runner de escenarios con aserciones. | C | F2 |
| RF-1310 | La UI debe tener un checklist manual de aceptación visual. | S | F1 |

---

## 5. Interfaz de usuario

### 5.1 Principios

1. **Dos columnas en la vista base**: mapa a la izquierda; observabilidad a la derecha.
2. **Entender en segundos**: el panel derecho debe responder qué pasa, quién es quién, qué necesita cada agente, qué está haciendo y qué piensa hacer.
3. **Profundidad bajo demanda**: la vista base resume; las vistas a pantalla completa permiten leer sin apretar.
4. **El operador es observador, no jugador**: no controla agentes; puede pausar, inspeccionar, guardar y reproducir.
5. **El pensamiento es reportado**: la UI muestra lo que el agente envía por MCP, no una lectura real de su mente.
6. **Teclado primero**: todos los accesos críticos tienen atajo; el mouse es opcional.
7. **Barra inferior persistente**: los atajos principales siempre están visibles.
8. **Accesibilidad**: glifos + etiquetas + color; paleta apta para daltonismo; escala de fuente.

### 5.2 Layout base 160 × 45

| Región | Coordenadas (0-indexadas) | Tamaño | Uso |
|---|---|---|---|
| Mapa | x 0–79, y 0–39 | 80 × 40 | Mundo completo |
| Ticker inferior izquierdo | x 0–79, y 40–43 | 80 × 4 | Últimos eventos globales |
| Panel derecho | x 80–159, y 0–43 | 80 × 44 | Observabilidad |
| Barra inferior | x 0–159, y 44 | 160 × 1 | Atajos persistentes |

El renderizado y la entrada se realizan con una consola libtcod de 160 × 45. La fuente por defecto es monoespaciada Unicode de 12 × 24 px (ventana 1920 × 1080); la escala puede ajustarse para pantallas menores. La UI base no hace scroll del mapa: la isla completa está visible en el modo de mapa completo; el modo foco muestra el FOV/memoria del agente seleccionado.

#### 5.2.1 Mockup conceptual

```text
┌──────────────────────────────────────────────┬──────────────────────────────────────────────┐
│ MAPA 80 × 40                                 │ DÍA 3 · 14:35 · LLUVIA · 16 °C · VIENTO 4     │
│                                              │ PAUSA ▐ VEL 2x                               │
│        ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈           ├──────────────────────────────────────────────┤
│      ≈≈≈≈≈··♣♣♣♣··,,,,""··♣♣♣≈≈≈≈           │ AGENTES                                      │
│     ≈≈≈·♣♣♣♣♣♣,,,,,""""··♣♣♣♣≈≈≈           │ ▶ 1 @ Nia    ♥92 H23 S41 E77  [SED]          │
│     ≈≈··♣♣♣♣,,,,,,,,,,··♣♣♣♣♣≈≈≈           │   2 @ Kai    ♥71 H55 S62 E44  [FRÍO]         │
│     ≈≈··,,,,""""··≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈           │   3 @ Luma   ☠   — muerta por inanición       │
│     ≈≈··,,,,""""··≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈           ├──────────────────────────────────────────────┤
│     ≈≈··,,,,··▲▲··,,,,,,··♣♣♣♣♣≈≈≈           │ AGENTE SELECCIONADO · Nia · @ · (32, 14)     │
│     ≈≈··,,,,··▲▲··,,,,,,··♣♣♣♣♣≈≈≈           │ Salud   ████████░░  92                       │
│     ≈≈··,,,,,,,,,,,,,,,,··♣♣♣♣♣≈≈≈           │ Hambre  ██░░░░░░░░  23                       │
│     ≈≈··,,,,""""··,,,,,,··♣♣♣♣♣≈≈≈           │ Sed     ████░░░░░░  41  [SED]                │
│     ≈≈··,,,,,,,,,,,,,,,,··♣♣♣♣♣≈≈≈           │ Energía ███████░░░  77                       │
│     ≈≈··,,,,,,··*··,,,,,,··♣♣♣♣♣≈≈≈           │ Temp    ███████░░░  36.8 °C                  │
│     ≈≈··,,,,,,,,,,,,,,,,··♣♣♣♣♣≈≈≈           │ Mojado  ███░░░░░░░  34                       │
│     ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈           │ Equipo: lanza de piedra · odre (2)           │
│                                              ├──────────────────────────────────────────────┤
├──────────────────────────────────────────────┤ MENTE (REPORTADO)                            │
│ 14:30 Nia bebió del río                      │ Intención: conseguir comida antes del        │
│ 14:31 Kai recogió 2 bayas                    │            anochecer                         │
│ 14:32 Lluvia intensa                         │ Pensamiento: “Tengo poca hambre, pero la     │
│ 14:33 Nia crafteó una lanza                  │ sed sube; buscaré el río y luego bayas.”     │
│                                              │ Plan: río → arbusto → refugio                │
│                                              │ Última acción: beber (ok) · t142             │
├──────────────────────────────────────────────┤ Próximo paso reportado: moverse al arbusto   │
│ [ESPACIO] Pausa  [1-8/TAB] Agente  [+/-] Vel │                                              │
│ [F1] Ayuda [F2] Agente [F3] Mundo [F4] Log   ├──────────────────────────────────────────────┤
│ [F5] Replay [F6] Mapa [F9] Guardar [Q] Salir │ ENTORNO                                      │
└──────────────────────────────────────────────┴──────────────────────────────────────────────┘
```

El mockup es conceptual: en la implementación el mapa ocupa exactamente 80 × 40 y el panel derecho 80 × 44. La barra inferior real ocupa una sola línea de 160 caracteres.

### 5.3 Panel derecho

El panel derecho debe priorizar la lectura rápida. La pestaña `RESUMEN` agrupa las secciones de lectura rápida; las pestañas de detalle amplían eventos, mente y vínculos. El contenido base se organiza en secciones separadas por líneas:

1. **Encabezado de sesión**
   - Día, hora y fase.
   - Clima, temperatura, viento y visibilidad.
   - Estado `PAUSA` y velocidad.
   - Indicador de agentes conectados / vivos / libres y del estado `ESPERANDO AGENTES`.

2. **Agentes**
   - Una línea por agente (hasta 8).
   - Número de selección, glifo `@`, nombre, salud, hambre, sed, energía y estados.
   - El seleccionado se resalta.
   - Los muertos muestran `☠` y causa; los ausentes conectados muestran `…`; los desconectados se retiran y quedan registrados como evento de conexión.
   - Los timeouts se indican con un contador.
   - La tabla compacta vive en `RESUMEN`; en las demás pestañas se mantiene una franja compacta con todos los agentes.

3. **Agente seleccionado**
   - Nombre, posición, arma equipada y estado general.
   - Barras numéricas de salud, hambre, sed, energía, temperatura y mojadura.
   - Estados activos como etiquetas: `[SED]`, `[FRÍO]`, `[SANGRANDO]`.
   - Fuerza, destreza, resistencia y visión efectiva.
   - Capacidad de carga usada/total.
   - Inventario resumido y equipo.
   - Uso de IA reportado: modelo, esfuerzo, tokens de entrada/salida/total y costo aproximado en USD.
   - El inventario completo y el equipo están en `VÍNCULOS` y en `F2`.

4. **Mente (reportado)**
   - Intención actual.
   - Pensamiento más reciente (máximo 3 líneas en `RESUMEN`; completo en `MENTE`).
   - Plan declarado.
   - Última acción y su resultado.
   - Próximo paso reportado.
   - Si no hay reporte: `— sin reporte —`.
   - Etiqueta visible: `REPORTADO POR EL AGENTE`.
   - La vista completa y el historial están en `MENTE` y en `F2`.

5. **Entorno**
   - Día/hora/fase.
   - Clima, temperatura ambiente, viento, visibilidad.
   - Fuegos activos, refugios y cadáveres.
   - Mensajes recientes del agente seleccionado.

6. **Relaciones**
   - Alianzas activas.
   - Ofertas de intercambio pendientes.
   - Últimos mensajes enviados/recibidos.
   - Traiciones registradas.
   - La vista completa está en `VÍNCULOS` y en `F2`.

7. **Eventos**
   - Últimos 4–6 eventos globales.
   - Color por tipo; el historial completo y los filtros están en `EVENTOS` y en `F4`.

El panel debe adaptarse dinámicamente: si hay un solo agente, la ficha y el inventario reciben más espacio; si hay ocho, la lista se compacta y el detalle se consulta en `F2`.

#### 5.3.1 Pestañas del panel derecho

El panel conserva un encabezado global con día, hora, fase, clima, temperatura, viento, visibilidad y conteo de agentes. Debajo hay una barra de pestañas de una línea:

`◇ RESUMEN   EVENTOS   MENTE   VÍNCULOS`

La pestaña activa se marca con `◇`/`▸`, etiqueta y color; nunca solo con color. La barra puede mostrar contadores (`EVENTOS 142`, `MENTE 18`) para indicar profundidad sin abrir la pestaña.

- **RESUMEN (por defecto):** tabla compacta de todos los agentes, ficha del agente seleccionado, resumen de mente (máximo 3 líneas), entorno y últimos 3–4 eventos. Usa todo el alto disponible y se adapta: con un agente expande ficha, inventario y eventos; con ocho compacta la tabla y limita la mente a 2–3 líneas.
- **EVENTOS:** historial global a altura completa con scroll, hora, tipo y mensaje. Permite alternar entre global y agente seleccionado; el detalle completo con filtros y búsqueda sigue en `F4`.
- **MENTE:** intención, pensamiento completo con wrapping, plan, última acción, próximo paso e historial de reportes anteriores con scroll. El detalle completo sigue en `F2`.
- **VÍNCULOS:** inventario y equipo en dos columnas, alianzas, ofertas de intercambio y mensajes recientes con scroll. El detalle completo sigue en `F2`.

En las pestañas distintas de `RESUMEN` se mantiene una franja compacta con todos los agentes (`1@Nia♥92  2@Kai♥71 …`), de modo que RF-1102 se cumple siempre. El encabezado global muestra el estado del mundo.

Reglas de interacción:

- `[` / `]`: pestaña anterior / siguiente.
- `↑` / `↓`: desplazar una fila la lista activa.
- `PgUp` / `PgDn`: desplazar una página.
- `Inicio` / `Fin`: ir al inicio / final de la lista.
- `Esc`: volver a `RESUMEN` desde una pestaña; si hay un overlay o cursor activo, conserva su comportamiento de cierre.
- `F2`, `F4` y `F6` siguen abriendo las vistas completas de agente, eventos y mapa.
- Si el cursor de inspección del mapa está activo, las flechas mueven el cursor y no la lista.

Reglas de desborde:

- La vista base nunca renderiza listas ilimitadas: trunca con `…`, muestra `+N` y delega el resto a la pestaña correspondiente.
- `EVENTOS`, `MENTE` y `VÍNCULOS` ocupan el alto completo del panel y tienen scroll con indicador de posición.
- Los textos largos se truncan por ancho en la vista base; el wrapping completo se reserva para `MENTE` y las vistas full-screen.
- El orden es estable por tick y secuencia.

Las pestañas son estado de presentación: no alteran la simulación ni su determinismo. `Espacio` sigue pausando. Los overlays `F1`–`F8` pausan según §5.9. La barra inferior es contextual y sigue siendo una sola línea de 160 columnas.

### 5.4 Barra inferior persistente

La barra inferior está siempre visible. En la vista base muestra los atajos principales:

```text
[ESPACIO] Pausa│[1-8/TAB] Agente│[+/-] Vel│[ / ] Pestaña│[F1] Ayuda│[F2] Agente│[F3] Mundo│[F4] Log│[F5] Replay│[F6] Mapa│[F9] Guardar│[Q] Salir
```

En la vista base, la barra incluye `[ / ] Pestaña`; en `EVENTOS`, `MENTE` y `VÍNCULOS` agrega `[↑/↓] Scroll` y `[PgUp/PgDn] Página`. Los separadores pueden compactarse para no exceder 160 columnas.

En cada vista a pantalla completa la barra cambia de contexto, pero mantiene el mismo estilo y posición:

- `F2`: `[←/→] Sección │ [TAB] Otro agente │ [ESC] Volver │ [ESPACIO] Pausa │ [F4] Log │ [F9] Guardar`
- `F4`: `[↑/↓] Scroll │ [PgUp/PgDn] Página │ [F] Filtro │ [/] Buscar │ [TAB] Agente │ [ESC] Volver`
- `F5`: `[ESPACIO] Play/Pausa │ [←/→] ±1 tick │ [SHIFT+←/→] ±10 │ [INICIO] Inicio │ [ESC] Volver`
- `F6`: `[V] Visión │ [W] Clima │ [X] Inspeccionar │ [ESC] Volver`

### 5.5 Atajos de teclado

#### 5.5.1 Globales (vista base y overlays)

| Tecla | Acción |
|---|---|
| `Espacio` | Pausar / reanudar la simulación. |
| `+` / `-` | Aumentar / disminuir velocidad de presentación. |
| `1`–`8` | Seleccionar agente por número. |
| `0` | Vista de todos los agentes / deseleccionar. |
| `Tab` / `Shift+Tab` | Siguiente / anterior agente vivo. |
| `[` / `]` | Pestaña anterior / siguiente del panel derecho. |
| `↑` / `↓` | Desplazar una fila la lista de la pestaña activa; con el cursor de inspección activo, mueve el cursor. |
| `PgUp` / `PgDn` | Desplazar una página la lista de la pestaña activa. |
| `Inicio` / `Fin` | Ir al inicio / final de la lista de la pestaña activa. |
| `F1` | Ayuda, atajos, glifos y significados de estados. |
| `F2` | Ficha completa del agente seleccionado. |
| `F3` | Vista completa del mundo y todos los agentes. |
| `F4` | Registro de eventos completo. |
| `F5` | Replay de la sesión actual o del archivo cargado. |
| `F6` | Mapa ampliado a pantalla completa. |
| `F7` | Métricas y resumen de sesión. |
| `F8` | Ajustes de visualización. |
| `F9` | Guardar sesión. |
| `F10` | Cargar sesión. |
| `F11` | Alternar pantalla completa del sistema. |
| `F12` | Abrir la consola de debug del operador. |
| `Esc` | Cerrar overlay, cancelar cursor, volver a la vista base o volver a `RESUMEN` desde una pestaña. |
| `Q` | Salir; pide confirmación si hay una sesión en curso. |
| `R` | Reiniciar sesión nueva; solo en la pantalla de fin. |

Las flechas, `PgUp`/`PgDn` e `Inicio`/`Fin` controlan la pestaña activa del panel solo cuando el cursor de inspección del mapa no está activo.

#### 5.5.2 Mapa y capas

| Tecla | Acción |
|---|---|
| `V` | Alternar foco de FOV/memoria del agente seleccionado / mapa completo. |
| `W` | Alternar capa de clima (lluvia y viento en el MVP; nieve en F2). |
| `X` | Activar/desactivar cursor de inspección. |
| Flechas | Mover el cursor de inspección cuando `X` está activo. |
| `Enter` | Fijar/liberar la inspección de la celda o entidad. |
| `Esc` | Cerrar cursor/inspección. |

Al seleccionar un agente y activar el foco, el mapa renderiza solo sus celdas visibles y su memoria; `V` vuelve al mapa completo del operador sin alterar la simulación ni los datos del agente.

#### 5.5.3 Vistas a pantalla completa

| Vista | Atajos específicos |
|---|---|
| `F2` Agente | `←/→` cambiar sección si no entra en columnas; `Tab` otro agente; `Esc` volver. |
| `F3` Mundo | `↑/↓` mover selección; `Enter` abrir ficha; `Tab` siguiente agente. |
| `F4` Log | `↑/↓` scroll; `PgUp/PgDn`; `F` ciclar filtro; `/` buscar; `Tab` filtrar por agente; `Esc` volver. |
| `F5` Replay | `Espacio` play/pausa; `←/→` ±1 tick; `Shift+←/→` ±10; `Inicio` inicio; `Fin` final; `Esc` volver. |
| `F6` Mapa | `V` visión; `W` clima; `X` inspección; `Esc` volver. |
| `F7` Métricas | `Tab` siguiente agente; `↑/↓` detalle; `Esc` volver. |
| `F8` Ajustes | `↑/↓` opción; `←/→` cambiar; `Enter` aplicar; `Esc` volver. |

#### 5.5.4 Criterios de diseño de atajos

- Las teclas de función `F1`–`F8` abren vistas; `F9`/`F10` guardan/cargan; `F11` pantalla completa; `F12` consola de debug.
- `Espacio` siempre pausa; nunca ejecuta una acción destructiva.
- `Q` y `R` son las únicas teclas de salida/reinicio y requieren confirmación.
- `Esc` siempre “vuelve”, nunca cierra la aplicación.
- Los números seleccionan agentes; no se usan para acciones de juego.
- Las capas `V`/`W` y el inspector `X` son toggles y se indican en la barra inferior.
- Ningún atajo crítico depende de combinaciones con `Ctrl` o `Alt`.

### 5.6 Vistas a pantalla completa

#### 5.6.1 F1 — Ayuda y leyenda

Debe incluir:

- todos los atajos;
- glifos del mapa y colores;
- significado de estados y etiquetas;
- formato de la barra inferior;
- explicación de “pensamiento reportado”;
- cómo leer las barras y los indicadores.

#### 5.6.2 F2 — Ficha completa del agente

Layout de tres columnas:

| Columna izquierda | Columna central | Columna derecha |
|---|---|---|
| Identidad, posición, salud, necesidades, temperatura, estados, habilidades, equipo, carga y uso de IA reportado. | Mente: intención, pensamiento, plan, próximo paso y timeline de reportes/acciones (últimos 20). | Inventario completo, relaciones, alianzas, ofertas, mensajes y causa de muerte si corresponde. |

- Se abre con el agente seleccionado.
- `Tab` cicla agentes sin salir.
- Si el agente está muerto, muestra cadáver, causa, autor y botín.
- El timeline combina, por tick: reporte de mente, acción enviada, resultado y eventos relevantes.

#### 5.6.3 F3 — Vista completa del mundo

- Cabecera con día/hora, clima, temperatura, viento, visibilidad, estado de pausa y, en F2, pronóstico y estación.
- Tabla de todos los agentes:
  `#`, nombre, posición, salud, hambre, sed, energía, temperatura, estado, intención, última acción.
- Resumen del mundo: número de fuegos, refugios, cadáveres, árboles/arbustos visibles y ofertas activas.
- Ticker de eventos.
- `Enter` abre `F2` del agente seleccionado.

#### 5.6.4 F4 — Registro de eventos

- Tabla con tick, hora, tipo, agente(s), mensaje y resultado.
- Filtros:
  - `Todos`
  - `Acciones`
  - `Combate`
  - `Social`
  - `Necesidades`
  - `Clima`
  - `MCP/Errores`
  - `Agente seleccionado`
- Búsqueda de texto con `/`.
- Colores por tipo y etiquetas para no depender solo del color.
- No se recorta el log: se pagina.

#### 5.6.5 F5 — Replay

- Reproduce la sesión actual o un archivo de replay.
- La UI muestra el mismo layout base, con banner `REPLAY` y tick actual.
- Controles en la barra inferior.
- Debe ser determinista: mismo estado para el mismo tick.
- Al llegar al final, permite volver a la sesión viva si corresponde.

#### 5.6.6 F6 — Mapa ampliado

- Cambia a una ventana de 80 × 45 con fuente de 24 × 24 px (1920 × 1080) o escala equivalente.
- El mapa ocupa 80 × 40; las 5 filas restantes muestran:
  - leyenda compacta;
  - día/hora/clima;
  - agente seleccionado y posición;
  - ayuda de capas.
- Conserva `V` (FOV), `W` (clima) y `X` (inspección).
- `Esc` vuelve a la vista base de 160 × 45.

#### 5.6.7 F7 — Métricas y resumen

- Métricas por agente y por sesión (ver sección 8.3).
- Estado actual: supervivencia, necesidades críticas, exploración, crafteo, acciones sociales y combate.
- Al finalizar la sesión, esta vista se convierte en el resumen final.
- Permite comparar el estado actual con el inicio.

#### 5.6.8 F8 — Ajustes de visualización

- Paleta normal / apta para daltonismo.
- Escala de fuente.
- Pausar al abrir overlay (sí/no).
- Mostrar/ocultar ticker y capas por defecto.
- Confirmaciones de salida.
- Los cambios se guardan en la configuración de usuario y no afectan la simulación.

### 5.7 Pensamientos e intenciones de agentes

#### 5.7.1 Naturaleza del dato

IASim no puede leer la mente de un agente. Para que el operador entienda el comportamiento, el agente puede reportar:

- `intent`: objetivo actual en una frase.
- `thought`: explicación breve de su razonamiento o estado mental.
- `plan`: pasos previstos, texto libre o lista corta.
- `confidence`: 0–100 opcional.

El reporte es **voluntario, no verificado y potencialmente engañoso**. La UI lo etiqueta como `REPORTADO POR EL AGENTE` y lo trata como texto no confiable.

#### 5.7.2 Tool `iasim_report_mind`

- Llamada libre, máximo una vez por tick.
- Campos: `tick`, `intent` (≤ 160 caracteres), `thought` (≤ 500), `plan` (≤ 300), `confidence` (0–100).
- Devuelve `{ok, tick}`; no consume la acción principal.
- Se registra en `thoughts.jsonl` y en el timeline del agente.
- El texto se sanea: se eliminan caracteres de control y ANSI, se recortan longitudes y se normalizan saltos de línea.
- Los demás agentes no lo reciben automáticamente; solo el operador y los logs.

#### 5.7.3 Visualización

- Vista base: intención, pensamiento y plan en el bloque “Mente”; última acción y resultado.
- `F2`: timeline completo de reportes y acciones.
- `F3`: columna de intención y última acción por agente.
- `F4`: filtro de eventos y búsqueda; los pensamientos se registran como eventos de tipo `mind_report`.
- Si un agente no reporta, la UI muestra `— sin reporte —` y no inventa contenido.
- La ausencia de reportes se mide como métrica de observabilidad.

#### 5.7.4 Acciones y resultados

- Cada acción se muestra como verbo + objetivo + resultado:
  - `t142 beber(río) → ok`
  - `t143 recolectar(arbusto 31,12) → +2 bayas`
  - `t144 atacar(Kai) → impacto 6, sangrado`
  - `t145 craftar(hacha) → falta mesa`
- El resultado se muestra en la observación siguiente y se registra en el log.
- Las acciones inválidas se muestran con su código de error y no se ocultan.

### 5.8 Colores, glifos y accesibilidad

- Fuente Unicode monoespaciada; glifos del mapa según 3.3.1.
- Paleta base con contraste alto; paleta alternativa apta para daltonismo.
- El color nunca es el único portador de información: se usan etiquetas, glifos y texto.
- Barras de estado con caracteres de bloque `█` y `░`; fallback `#` y `-`.
- El texto de agentes se muestra como texto plano; nunca se interpretan secuencias ANSI, HTML ni Markdown.
- Las líneas largas se envuelven; en la vista base, el pensamiento se trunca visualmente y se ofrece la vista completa en `F2`.
- El tamaño de fuente puede ajustarse; la UI debe mantenerse legible a 12 × 24 px y 24 × 24 px.
- La barra inferior usa separadores `│` y texto corto para caber en 160 columnas.

### 5.9 Overlays y pausa

- Abrir `F1`–`F8` pausa la simulación por defecto (`pause_on_overlay = true`), para lectura cómoda.
- El operador puede reanudar con `Espacio` sin cerrar el overlay.
- La cabecera de cada overlay muestra `PAUSA` o `EN CURSO`.
- `Esc` cierra el overlay y vuelve a la vista base.
- `F5` replay siempre pausa la simulación viva y la deja en modo lectura hasta salir.
- Los overlays no modifican el estado de la simulación; solo la pausa y los ajustes de visualización.

---

## 6. Interfaz MCP

### 6.1 Transporte y autenticación

- Transporte: HTTP *streamable* de MCP.
- Endpoint por defecto: `http://127.0.0.1:8765/mcp`.
- Endpoint de salud: `GET http://127.0.0.1:8765/healthz`.
- Por defecto solo escucha en loopback. Para jugar en la misma red, el comando de arranque acepta `--host 0.0.0.0` (o la IP local) de forma explícita; la GUI muestra la URL LAN y una advertencia de exposición.
- Autenticación: token Bearer por slot de agente, generado al iniciar el servidor y escrito en `agents.json` con permisos restringidos. Cada slot tiene un token estable mientras el servidor vive; al desconectarse el agente, el slot queda libre y el mismo token puede usarse para una conexión nueva. El operador puede rotar tokens reiniciando el servidor.
- El servidor no arranca en LAN con `--dev-open`; esa opción solo se permite en loopback para pruebas.
- Los tokens no se escriben en logs ni en la GUI. La GUI solo muestra si un slot está libre, conectado o desconectado.
- En el MVP el transporte LAN es HTTP sin TLS y debe usarse en una red de confianza. Para redes no confiables se debe usar un túnel/VPN; TLS queda fuera del MVP.

### 6.2 Ciclo de observación y acción

1. El agente llama `iasim_join(name)` con su token.
2. En cada tick, llama `iasim_observe()` o `iasim_wait_for_tick(since_tick)`.
3. Puede llamar información libre: `iasim_get_recipes`, `iasim_get_inventory`, `iasim_inspect`.
4. Puede llamar `iasim_report_mind` una vez.
5. Puede llamar `iasim_say` una vez.
6. Envía una acción principal con `tick` y `request_id`.
7. La acción queda `queued`; el resultado se entrega en la observación del tick siguiente.
8. Si el agente duerme o está ausente, el servidor no espera su acción.

- Un agente puede consultar su última observación sin avanzar el tick.
- `iasim_join` se acepta entre ticks; si el tick actual tiene acciones pendientes, devuelve `TICK_IN_PROGRESS` y el cliente debe reintentar en el siguiente tick.
- Si intenta actuar con un tick viejo, recibe `STALE_TICK`.
- Si intenta actuar dos veces en el mismo tick, recibe `ALREADY_ACTED`.
- Si el deadline vence, el servidor resuelve con las acciones recibidas y marca `skip`.
- La observación incluye `deadline_ms` y `server_time_ms` para que el cliente gestione su presupuesto.
- El servidor expone la versión `iasim-mcp/1.0` y un `schema_version` en la observación.

### 6.3 Catálogo de tools

#### 6.3.1 Información y ciclo de vida

| Tool | Argumentos | Costo | Descripción |
|---|---|---|---|
| `iasim_join` | `name` | — | Registra al agente del token en el mundo abierto. Devuelve `agent_id`, spawn y estado. |
| `iasim_observe` | — | Libre | Devuelve la observación del tick actual o la última disponible. |
| `iasim_wait_for_tick` | `since_tick`, `timeout_ms?` | Libre | Espera hasta que haya un tick nuevo; devuelve observación o `NO_NEW_TICK`. |
| `iasim_get_recipes` | — | Libre | Recetas conocidas, requisitos y estaciones. |
| `iasim_get_inventory` | — | Libre | Inventario, equipo, peso y slots. |
| `iasim_inspect` | `target_id` o `x,y` | Libre | Detalle de una entidad visible. |
| `iasim_get_session_info` | — | Libre | Día, tick, versión del protocolo, estado de pausa y agentes. Nunca la seed ni el RNG, que el agente no puede conocer (RF-1012). |
| `iasim_report_mind` | `tick`, `intent`, `thought`, `plan?`, `confidence?` | Libre, 1/tick | Reporta intención/pensamiento para el operador. |
| `iasim_report_usage` | `tick`, `input_tokens`, `output_tokens`, `model`, `reasoning_effort?`, `cost_usd?` | Libre, acumulativo | Reporta uso de IA para el operador; no consume acción ni altera la simulación. |
| `iasim_leave` | — | — | Cierra la sesión del agente; no lo mata. |

#### 6.3.2 Acciones principales (máximo una por tick)

Todas las acciones principales aceptan `tick`, `request_id?` y `reason?` (≤ 280 caracteres) además de los argumentos indicados.

| Tool | Argumentos | Descripción |
|---|---|---|
| `iasim_move` | `dx`, `dy` | Mueve una celda en 8 direcciones. |
| `iasim_move_to` | `x`, `y` | Calcula una ruta determinista con `tcod.path` y avanza un paso este tick. |
| `iasim_wait` | — | Espera sin moverse. |
| `iasim_gather` | `x`, `y` o `node_id` | Recolecta un recurso adyacente/visible. |
| `iasim_pickup` | `x`, `y`, `item_id?` | Recoge un ítem del suelo. |
| `iasim_drop` | `item_id`, `qty?` | Suelta un ítem. |
| `iasim_eat` | `item_id` | Consume un alimento. |
| `iasim_drink` | `x`, `y` o `item_id` | Bebe de una fuente o de un odre. |
| `iasim_fill` | `item_id` | Rellena un odre en agua dulce adyacente. |
| `iasim_rest` | — | Descansa un tick. |
| `iasim_sleep` | `until?` (`energy_full`, `dawn`, `hours:N`) | Duerme hasta condición; no bloquea el turno. |
| `iasim_equip` | `item_id` | Equipa herramienta/ropa/mochila. |
| `iasim_unequip` | `slot` | Desequipa. |
| `iasim_use` | `item_id` | Usa antorcha, venda u otro consumible. |
| `iasim_craft` | `recipe_id` | Craftea si cumple requisitos. |
| `iasim_build` | `structure_id`, `x`, `y` | Construye una estructura adyacente. |
| `iasim_attack` | `target_id` | Ataca cuerpo a cuerpo. |
| `iasim_throw` | `item_id`, `target_id` | Arroja una piedra. |
| `iasim_flee` | `target_id` | Huye del objetivo. |
| `iasim_loot` | `corpse_id` | Saca ítems de un cadáver. |
| `iasim_say` | `message`, `target_id?` | Habla; libre, 1/tick. |
| `iasim_offer_trade` | `target_id`, `offer`, `request` | Propone intercambio. |
| `iasim_accept_trade` | `trade_id` | Acepta y ejecuta intercambio. |
| `iasim_decline_trade` | `trade_id` | Rechaza intercambio. |
| `iasim_offer_alliance` | `target_id` | Propone alianza. |
| `iasim_accept_alliance` | `alliance_id` | Acepta alianza. |
| `iasim_break_alliance` | `target_id` | Rompe alianza. |

#### 6.3.3 Reglas de las tools

- Una acción principal por tick; `iasim_say` y `iasim_report_mind` son gratuitas.
- `iasim_report_mind` acepta un reporte por tick, lo sanea, lo escribe en `thoughts.jsonl` y solo lo expone al operador.
- Las tools de información no consumen acción, pero están limitadas por tasa.
- `iasim_report_usage` es gratuito y acumulativo por agente; agrupa por modelo y esfuerzo, y se descarta al desconectarse el agente.
- El `tick` de uso puede ser el actual o uno anterior, para tolerar latencia del modelo; un tick futuro se rechaza.
- El costo reportado por el agente tiene prioridad; si falta, se estima con `[usage.pricing]`; si tampoco hay precio, queda como desconocido.
- Toda acción devuelve `queued`; el resultado final aparece en la observación siguiente como `action_result`.
- Las acciones se validan al encolar y se revalidan al resolver; una acción puede fallar si el mundo cambió.
- `request_id` es idempotente durante la sesión: repetir la misma llamada no duplica la acción.
- Los `offer`/`request` de intercambio son listas de `{item_id, qty}`.
- `sleep` suspende la obligación de actuar; el agente recibe observaciones y puede ser despertado por daño o peligro.
- No hay tools de administración, teletransporte, edición de mapa ni lectura del mapa completo.

### 6.4 Observación

La observación es el contrato principal entre el juego y el agente. Ejemplo abreviado:

```json
{
  "schema_version": "1.0",
  "tick": 142,
  "session": {
    "phase": "running",
    "max_agents": 8,
    "joined_agents": 2,
    "alive_agents": 2
  },
  "server_time_ms": 1750000000123,
  "deadline_ms": 60000,
  "time": {
    "day": 1,
    "hour": 17,
    "minute": 50,
    "phase": "day",
    "light": 0.9
  },
  "agent": {
    "id": "ag_01",
    "name": "Nia",
    "pos": [32, 14],
    "health": 92.0,
    "hunger": 23.4,
    "thirst": 41.2,
    "energy": 77.0,
    "body_temp_c": 36.8,
    "wetness": 34.0,
    "status": ["thirsty"],
    "strength": 5,
    "dexterity": 5,
    "endurance": 5,
    "effective_vision": 7,
    "carry_kg": 7.4,
    "carry_capacity_kg": 20.0,
    "equipment": {
      "tool": "stone_spear",
      "body": "fiber_clothes",
      "back": null,
      "light": "torch"
    }
  },
  "environment": {
    "weather": "rain",
    "temperature_c": 16.0,
    "wind": 4,
    "visibility_factor": 0.8
  },
  "perception": {
    "visible": [
      {"x": 31, "y": 14, "tile": "river", "glyph": "~", "resource": "fresh_water", "entities": []},
      {"x": 32, "y": 15, "tile": "bush", "glyph": "♠", "resource": "berries", "entities": []}
    ],
    "memory_updates": [
      {"x": 30, "y": 14, "tile": "tree", "last_seen_tick": 140, "stale": false}
    ],
    "agents": [
      {"id": "ag_02", "name": "Kai", "pos": [29, 15], "health_band": "herido", "equipment_visible": ["stone_axe"], "relation": "neutral"}
    ],
    "messages": [
      {"from": "ag_02", "tick": 141, "text": "¿Intercambias bayas por piedra?"}
    ]
  },
  "inventory": {
    "weight_kg": 7.4,
    "slots_used": 6,
    "slots_total": 10,
    "items": [
      {"item_id": "inv_01", "type": "berry", "qty": 3, "weight_kg": 0.15},
      {"item_id": "inv_02", "type": "waterskin", "qty": 1, "charges": 2}
    ]
  },
  "available_actions": [
    {"action": "drink", "target": {"x": 31, "y": 14}, "available": true},
    {"action": "gather", "target": {"x": 32, "y": 15}, "available": true},
    {"action": "craft", "recipe": "stone_spear", "available": false, "reason": "MISSING_INGREDIENTS"}
  ],
  "last_action_result": {
    "tick": 141,
    "action": "move",
    "status": "success",
    "events": ["Entraste en un arbusto"]
  }
}
```

Campos obligatorios:

- `schema_version`, `tick`, `session`, `server_time_ms`, `deadline_ms`.
- `session.phase` es `waiting`, `running` o `finished`; incluye `max_agents`, `joined_agents` y `alive_agents`, `waiting_reason` si está esperando (`no_agents`, `no_active_agents` o `last_death`) y `end_reason` si terminó.
- `time`, `agent`, `environment`.
- `perception.visible`, `perception.memory_updates`, `perception.agents`, `perception.messages`.
- `inventory` y `available_actions`.
- `social` con las alianzas activas del agente y las ofertas pendientes que lo involucran (`alliance_id`, `from`, `to`, `tick`, `mine`); la relación de un agente visible es `ally` solo si la alianza está aceptada.
- `last_action_result` si existe.

El uso de IA reportado no forma parte de la observación del agente ni del estado canónico de la simulación; se acumula para el operador y se descarta al desconectarse el agente.

En fase 2, `environment` incluye además `forecast` cuando el pronóstico está habilitado:

```json
"forecast": {
  "horizon_ticks": 6,
  "precipitation_prob": 0.35,
  "storm_prob": 0.10,
  "confidence": 0.72
}
```

El pronóstico es probabilístico y puede fallar; no revela el estado futuro exacto. La observación no incluye el mapa completo, ni el RNG, ni el estado de otros agentes fuera de percepción.

### 6.5 Errores

Las tools devuelven un resultado estructurado. Los errores de validación se devuelven como datos, no como fallos de transporte, para que el agente pueda corregir:

```json
{
  "ok": false,
  "tick": 142,
  "error": {
    "code": "OUT_OF_RANGE",
    "message": "El arbusto está a 4 celdas; el alcance es 1.",
    "details": {"distance": 4, "max_range": 1}
  }
}
```

| Código | Significado |
|---|---|
| `STALE_TICK` | La acción corresponde a un tick ya resuelto. |
| `ALREADY_ACTED` | Ya se envió una acción principal en este tick. |
| `INVALID_TICK` | Tick inexistente o futuro. |
| `AGENT_DEAD` | El agente está muerto. |
| `AGENT_ABSENT` | El agente conectado está ausente por timeouts; no puede actuar hasta volver a responder. |
| `TICK_IN_PROGRESS` | El tick actual ya tiene acciones pendientes; el agente debe reintentar la conexión en el siguiente tick. |
| `SESSION_FINISHED` | El operador finalizó la sesión; no se aceptan más conexiones ni acciones. |
| `NOT_YOUR_TURN` | La acción no corresponde al agente autenticado. |
| `INVALID_TARGET` | Objetivo inexistente o no visible. |
| `OUT_OF_RANGE` | Objetivo fuera de alcance. |
| `BLOCKED` | Camino o celda bloqueada. |
| `MISSING_REQUIREMENT` | Falta herramienta, estación o requisito. |
| `MISSING_INGREDIENTS` | Faltan ingredientes. |
| `INVENTORY_FULL` | Sin slots o capacidad. |
| `INVALID_TRADE` | Oferta inválida, vencida o sin ítems. |
| `NOT_IN_RANGE` | Interlocutor fuera del rango social. |
| `RATE_LIMITED` | Demasiadas llamadas. |
| `MESSAGE_TOO_LONG` | Texto excede el límite. |
| `INVALID_MESSAGE` | El mensaje queda vacío después de sanearlo. |
| `ALREADY_SAID` | El agente ya envió su mensaje local en este tick. |
| `INVALID_MIND_REPORT` | Reporte de mente vacío, mal tipado o con confianza inválida. |
| `ALREADY_REPORTED` | El agente ya envió su reporte de mente en este tick. |
| `INVALID_USAGE` | Reporte de uso inválido: modelo, esfuerzo, tokens o costo fuera de rango. |
| `NO_NEW_TICK` | `wait_for_tick` venció sin tick nuevo. |
| `INTERNAL_ERROR` | Error inesperado; el servidor sigue operativo. |

### 6.6 Límites y seguridad

- Rate limit sugerido: 20 llamadas de información por segundo y 5 llamadas de acción por segundo por agente; la segunda acción del tick se rechaza.
- `say.message` ≤ 280 caracteres; `report_mind.thought` ≤ 500; `intent` ≤ 160; `plan` ≤ 300; `reason` ≤ 280.
- `report_usage.model` = 1-80 caracteres imprimibles; `reasoning_effort` ≤ 32; tokens ≥ 0; `cost_usd` finito y ≥ 0.
- Se eliminan caracteres de control, ANSI y saltos de línea excesivos.
- Toda entrada se valida con esquemas Pydantic y rangos cerrados.
- No se usa `eval`, `exec` ni se interpretan expresiones enviadas por agentes.
- El servidor limita el tamaño máximo de request y respuesta.
- Los tokens se comparan en tiempo constante y no se registran.
- El servidor no expone el mapa completo, el RNG ni el estado de agentes no percibidos.
- El texto de agentes se trata como no confiable, incluso si parece una instrucción del sistema.
- El servidor sigue operativo ante JSON inválido, tool desconocida o desconexión abrupta.

---

## 7. Configuración y CLI

### 7.1 Archivo TOML

Ejemplo mínimo:

```toml
[game]
seed = 42
headless = false
max_agents = 8
tick_minutes = 5
turn_timeout_ms = 60000
timeout_disconnects = 3
pause_on_overlay = true
autosave_every_ticks = 1000

[world]
width = 80
height = 40
name = "isla_boscosa"

[weather]
snow_enabled = false
season = "summer"
season_days = 7
weather_min_ticks = 12
weather_max_ticks = 72
forecast_enabled = true
forecast_horizon_ticks = 6

[mcp]
host = "127.0.0.1"
port = 8765
require_token = true
dev_open = false

[ui]
language = "es"
font_path = "assets/fonts/DejaVuSansMono.ttf"
font_width = 12
font_height = 24
palette = "default"
map_zoom_font_width = 24
map_zoom_font_height = 24

[logs]
dir = "runs"
snapshot_every_ticks = 100
export_csv = true

[usage]
# Precios opcionales en USD por millón de tokens. Sin precio, el costo
# solo se conoce si el agente lo reporta.

[usage.pricing."gpt-5"]
input_per_million_usd = 1.25
output_per_million_usd = 10.0

[debug]
enabled = true
confirm_destructive = true
```

- La configuración se valida al iniciar; los errores deben indicar archivo, clave y valor esperado.
- Los valores de CLI tienen prioridad sobre el archivo.
- La seed se registra siempre, incluso si se genera automáticamente.

### 7.2 CLI

| Comando / flag | Descripción |
|---|---|
| `iasim` | Comando principal: inicia la GUI completa del operador, el mundo y el servidor MCP con la configuración por defecto. |
| `iasim serve` | Alias explícito del comando principal. |
| `python -m iasim` | Alias del comando principal. |
| `--config PATH` | Carga un TOML. Los flags de CLI tienen prioridad sobre el archivo. |
| `--seed N` | Fija la seed. |
| `--headless` | Ejecuta el servidor sin GUI. |
| `--host H` | Host de escucha; por defecto `127.0.0.1`. La LAN se habilita explícitamente con `0.0.0.0` o la IP local. |
| `--max-agents N` | Máximo de agentes concurrentes (1–8). |
| `--port N` | Puerto MCP. |
| `--tick-minutes N` | Minutos de juego por tick. |
| `--turn-timeout-ms N` | Plazo de acción por tick. |
| `--timeout-disconnects N` | Timeouts consecutivos antes de marcar ausente. |
| `--snapshot-every N` | Cadencia de snapshots. |
| `--autosave-every N` | Cadencia de autoguardado. |
| `--no-autosave` | Desactiva autoguardado. |
| `--log-dir PATH` | Directorio de logs. |
| `--dev-open` | Desactiva auth solo en loopback. |
| `--load PATH` | Carga una sesión guardada. |
| `--replay PATH` | Reproduce una corrida. |
| `--version` | Versión de IASim y del esquema MCP. |
| `python -m iasim.reference_agent` | Lanza el agente de referencia. |

La GUI que abre el comando principal es la vista completa definida en §5.3 y §5.5, no una versión reducida. `--headless` es la única variante sin ventana y conserva la misma simulación y contrato MCP. Cualquier valor de `[game]`, `[world]`, `[weather]`, `[mcp]`, `[ui]`, `[logs]` y `[debug]` puede fijarse en TOML; para opciones no listadas en la tabla se usa `--config`.

```bash
iasim --config config/iasim.toml --host 0.0.0.0 --port 8765 --max-agents 8 --seed 42
```

Códigos de salida:

- `0`: servidor cerrado correctamente.
- `1`: error de configuración.
- `2`: error de generación de mundo.
- `3`: error de MCP o puerto ocupado.
- `4`: error de guardado/carga.
- `5`: error interno.

### 7.3 Consola de debug del operador

La consola de debug se abre con `F12` y es exclusiva del operador humano. No se expone por MCP ni los agentes pueden invocarla. Sirve para experimentos controlados y para reproducir condiciones.

| Comando | Efecto |
|---|---|
| `/spawn <item_id> <qty> [x y]` | Crea ítems en el suelo, cerca del agente seleccionado o en las coordenadas indicadas. |
| `/resource <resource_id> <x> <y> [qty]` | Crea o repone un nodo de recurso. |
| `/weather <estado> [ticks]` | Fuerza el clima (despejado, nublado, lluvia, tormenta, niebla o nieve). |
| `/time <día> <HH:MM>` | Ajusta el reloj de la sesión. |
| `/tp <agent_id> <x> <y>` | Teletransporta un agente a una celda válida. |
| `/note <texto>` | Añade una nota de experimento al log. |
| `/help` | Lista los comandos disponibles. |

- Los comandos se validan contra el estado del mundo y no pueden crear celdas inválidas.
- Toda inyección se registra en `debug.jsonl` y en el flujo de replay como una acción de origen `operator_debug`; sin ese registro el replay no sería determinista.
- La sesión se marca con `debug_used: true`; los resúmenes y comparaciones deben mostrar esta marca.
- La consola está deshabilitada en modo replay y en sesiones cargadas como solo lectura.
- `confirm_destructive = true` exige confirmación para teletransportes y cambios de tiempo.
- Las inyecciones no se anuncian a los agentes como eventos del mundo salvo que correspondan a un cambio perceptible (por ejemplo, un recurso nuevo visible).

---

## 8. Persistencia, replay y métricas

### 8.1 Archivos de una sesión

Cada sesión escribe en `runs/<timestamp>-seed<seed>/`:

| Archivo | Contenido |
|---|---|
| `session.json` | Configuración efectiva, seed, versiones, hora de inicio, agentes, `debug_used` y resultado final. |
| `events.jsonl` | Eventos del mundo y de conexión: join, disconnect, espera, movimiento, recolección, crafteo, clima, combate, muerte, timeouts, etc. |
| `actions.jsonl` | Llamadas MCP de acción, argumentos, `request_id`, resultado y tick. |
| `thoughts.jsonl` | Reportes de mente con tick, agente, intención, pensamiento, plan y confianza. |
| `debug.jsonl` | Inyecciones de la consola de debug del operador. |
| `replay.json` | Referencia a seed/configuración y offset de acciones reproducible. |
| `snapshots/` | Snapshots cada `snapshot_every_ticks` (por defecto 100). |
| `summary.json` | Métricas finales y hash de estado. |
| `metrics.csv` | Métricas tabulares por agente y por sesión. |
| `agents.json` | Tokens estables por slot y estado de ocupación; permisos restringidos, nunca en logs ni en la GUI. |

- La GUI puede mostrar la actividad en vivo; los archivos JSONL permiten revisar la sesión después.
- El guardado manual (`F9`) escribe un snapshot completo y actualiza `session.json`.
- La carga (`F10` o `--load`) restaura seed, RNG, tick, agentes, mundo, estructuras, inventarios, memoria y cola de turno.
- El guardado debe ser atómico: escribir archivo temporal y renombrar.
- El formato incluye `schema_version`; una versión incompatible debe rechazarse con mensaje claro.

### 8.2 Replay

- Un replay se define por: seed, configuración efectiva, secuencia de acciones, inyecciones de debug y tick final.
- La simulación debe ser determinista: mismo replay ⇒ mismo hash de estado en cada tick.
- El replay no depende de la latencia ni del orden de llegada de las acciones; el orden de resolución está definido por iniciativa y seed.
- `F5` reproduce la sesión actual desde el inicio; `--replay` reproduce una corrida guardada.
- Los snapshots permiten saltar a un tick sin recalcular desde cero (fase 2 para búsqueda arbitraria; el MVP puede recalcular).
- El replay debe mostrar el mismo panel de observabilidad, incluyendo pensamientos y acciones registrados.
- Los reportes de mente se reproducen como datos históricos; no se vuelve a consultar a ningún agente.

### 8.3 Métricas

Las métricas se calculan por agente y por sesión. Se guardan en `summary.json` y `metrics.csv`, y se muestran en `F7`.

| Métrica | Definición |
|---|---|
| `survival_ticks` | Ticks vividos hasta muerte o fin de sesión. |
| `days_survived` | `survival_ticks / 288`. |
| `cause_of_death` | Causa registrada (inanición, deshidratación, hipotermia, combate, etc.). |
| `killed_by` | Agente o evento responsable, si aplica. |
| `avg_hunger` | Promedio de hambre sobre ticks vivos. |
| `avg_thirst` | Promedio de sed sobre ticks vivos. |
| `avg_energy` | Promedio de energía sobre ticks vivos. |
| `critical_need_ratio` | Ticks con al menos una necesidad en umbral crítico / ticks vivos. |
| `exploration_pct` | Celdas transitables vistas / total de celdas transitables. |
| `distance_traveled` | Suma de movimientos exitosos. |
| `resources_gathered` | Unidades recolectadas por tipo. |
| `items_crafted` | Ítems crafteados por receta. |
| `structures_built` | Estructuras construidas por tipo. |
| `actions_total` | Acciones principales enviadas. |
| `actions_failed` | Acciones rechazadas o fallidas. |
| `invalid_action_rate` | `actions_failed / actions_total`. |
| `timeouts` | Ticks sin respuesta. |
| `messages_sent` | Mensajes `say` enviados. |
| `trades_offered` | Ofertas de intercambio. |
| `trades_completed` | Intercambios ejecutados. |
| `alliances_formed` | Alianzas aceptadas. |
| `betrayals` | Ataques a aliados. |
| `attacks_made` | Ataques y arrojamientos. |
| `damage_dealt` | Daño total infligido. |
| `damage_taken` | Daño total recibido. |
| `kills` | Agentes eliminados. |
| `mind_reports` | Reportes de mente enviados. |
| `mind_report_rate` | `mind_reports / ticks vivos`. |
| `decision_latency_p50_ms` | Mediana del tiempo entre observación y acción. |
| `decision_latency_p95_ms` | Percentil 95 de la latencia de decisión. |
| `final_state_hash` | Hash canónico del estado final. |

- Las métricas de necesidades se calculan solo sobre ticks con el agente vivo.
- Las tasas se acompañan del numerador y denominador para evitar ambigüedad.
- No se impone un “puntaje único” en el MVP: se comparan vectores de métricas. Un score compuesto configurable queda para fase 2.
- El reporte final incluye una tabla por agente y una fila de agregados de sesión.
- La ausencia de reportes de mente se mide; no se penaliza automáticamente.
- Las sesiones con inyecciones de debug se marcan con `debug_used: true` y se excluyen de comparaciones oficiales salvo que se indique lo contrario.

---

## 9. Requerimientos no funcionales

| ID | Requerimiento | Criterio verificable |
|---|---|---|
| RNF-01 | Determinismo | Misma seed, configuración y acciones ⇒ mismo `final_state_hash` en ejecuciones repetidas. |
| RNF-02 | Rendimiento del núcleo | Tick con 8 agentes en 80 × 40: p95 < 50 ms sin contar latencia de agentes. |
| RNF-03 | Rendimiento de UI | Render estable a 30 FPS en la vista base con 8 agentes. |
| RNF-04 | Latencia MCP | Overhead local de una tool < 20 ms p95, sin contar la lógica de turno. |
| RNF-05 | Arranque | Inicio de simulación y servidor MCP en < 2 s en hardware de referencia. |
| RNF-06 | Memoria | Uso < 300 MB con 8 agentes y 10 000 ticks. |
| RNF-07 | Robustez | Entradas inválidas, desconexiones y timeouts no derriban el proceso. |
| RNF-08 | Persistencia | Guardado/carga restaura el mismo hash de estado. |
| RNF-09 | Portabilidad | Windows 10+, Linux y macOS con Python 3.12. |
| RNF-10 | Seguridad | Bind loopback por defecto; LAN solo opt-in con tokens y advertencia; validación de esquemas y límites de entrada. |
| RNF-11 | Mantenibilidad | Módulos desacoplados, type hints y cobertura de tests del núcleo ≥ 80 %. |
| RNF-12 | Observabilidad | Logs estructurados con tick, tipo, actor, objetivo y resultado. |
| RNF-13 | Usabilidad | Todos los atajos críticos documentados en `F1`; UI legible a 160 × 45. |
| RNF-14 | Accesibilidad | Información no dependiente solo del color; paleta alternativa; fuente escalable. |
| RNF-15 | Internacionalización | UI en español y MCP en inglés en el MVP; cadenas de UI externalizadas. |
| RNF-16 | Recuperación | El servidor MCP puede reiniciarse sin perder un snapshot guardado. |
| RNF-17 | Soak test | 24 h de simulación headless sin fugas de memoria ni crecimiento anómalo de logs. |
| RNF-18 | Compatibilidad de replay | Un replay del mismo `schema_version` produce el mismo resultado. |

---

## 10. Criterios de aceptación

| ID | Criterio | Verificación |
|---|---|---|
| AC-01 | La vista base ocupa 160 × 45, con mapa 80 × 40 a la izquierda, panel 80 × 44 a la derecha y barra inferior de una línea. | Captura/checklist visual y test de layout. |
| AC-02 | Todos los glifos del mapa se renderizan sin “tofu” con la fuente incluida. | Test visual sobre la paleta completa. |
| AC-03 | Dos corridas headless con misma seed y mismas acciones producen el mismo hash al tick 500. | Test de determinismo. |
| AC-04 | Un agente con hambre/sed crecientes alcanza umbrales y muere por la causa correcta. | Test de necesidades. |
| AC-05 | Un agente puede recolectar, craftear una lanza, equiparla y atacar. | Test de integración con agente de referencia. |
| AC-06 | La lluvia aumenta mojadura y reduce temperatura corporal; fuego y refugio la mitigan. | Test de clima. |
| AC-07 | Un agente MCP se une, observa, se mueve y recibe el resultado en el tick siguiente. | Test de integración MCP. |
| AC-08 | Una acción con tick viejo se rechaza con `STALE_TICK`; una segunda acción se rechaza con `ALREADY_ACTED`. | Test de errores. |
| AC-09 | Un timeout pierde el turno; tres consecutivos marcan al agente como ausente. | Test de timeouts. |
| AC-10 | Dos agentes en rango completan un intercambio atómico; si falta un ítem, falla sin efectos parciales. | Test de comercio. |
| AC-11 | Un agente puede matar a otro; se genera cadáver, se registra causa y se puede saquear. | Test de combate/muerte. |
| AC-12 | La muerte del último agente no cierra el servidor: deja cadáver, la simulación se pausa y la GUI queda esperando; una nueva conexión puede entrar si hay un slot libre. | Test de fin de sesión y espera. |
| AC-13 | Un árbol o peñasco bloquea la visión; el tile no aparece en la observación del agente. | Test de FOV. |
| AC-14 | La memoria del agente persiste entre ticks y marca recursos desactualizados. | Test de memoria. |
| AC-15 | Guardar y cargar restaura el mismo hash de estado. | Test de persistencia. |
| AC-16 | Un replay produce las mismas métricas y el mismo hash final. | Test de replay. |
| AC-17 | El modo headless ejecuta 1000 ticks con 8 agentes sin abrir ventana y sin errores. | Test headless/rendimiento. |
| AC-18 | Acciones inválidas, JSON malformado y desconexiones no derriban el servidor. | Test de robustez. |
| AC-19 | La barra inferior y todas las vistas `F1`–`F10` son accesibles solo con teclado. | Checklist manual. |
| AC-20 | La UI muestra intención, pensamiento, plan y última acción reportados por el agente. | Test de integración + checklist visual. |
| AC-21 | Los pensamientos y mensajes se sanean y truncan; no se interpretan como código. | Test de seguridad. |
| AC-22 | El servidor MCP está bindeado a loopback por defecto y exige token. | Test de configuración/seguridad. |
| AC-23 | La fuente de 24 × 24 y la vista `F6` muestran el mapa completo con leyenda. | Checklist visual. |
| AC-24 | El agente de referencia sobrevive al menos 500 ticks en la seed de prueba sin errores de protocolo. | Test de humo. |
| AC-25 | Al finalizar una sesión se generan `summary.json` y `metrics.csv` con las métricas por agente. | Test de métricas. |
| AC-26 | Una inyección de debug queda registrada y un replay reproduce el mismo estado; los agentes no pueden invocarla. | Test de debug/replay y seguridad. |
| AC-27 | En F2, la nieve se acumula por tile y el pronóstico es probabilístico, no exacto. | Test de clima estacional. |
| AC-28 | El servidor arranca en loopback por defecto; `--host` habilita LAN, exige token y muestra la URL y una advertencia; un agente autenticado puede unirse desde otro host de la misma red. | Test de configuración/seguridad y checklist LAN. |
| AC-29 | Un agente desconectado desaparece del mundo, libera su slot y deja su inventario en el suelo; no quedan agentes fantasma. | Test de desconexión. |
| AC-30 | `iasim serve` abre la GUI del operador y muestra en vivo a los agentes conectados, su estado y su actividad; `--headless` no abre ventana. | Checklist visual y test headless. |
| AC-31 | `events.jsonl`, `actions.jsonl` y `thoughts.jsonl` registran join, disconnect, acciones y reportes de mente sin tokens; la GUI permite revisar la actividad. | Test de logs y checklist visual. |

---

## 11. Fases

### 11.1 Fase 0 — Fundaciones

Objetivo: esqueleto ejecutable y determinista.

- Estructura del proyecto, configuración TOML, CLI y logging.
- Núcleo de simulación con reloj, tick y RNG determinista.
- Generación de isla 80 × 40 con validaciones.
- Render base 160 × 45 con mapa, panel derecho mínimo y barra inferior.
- Servidor MCP local con `join`, `observe`, `move`, `wait`.
- Un agente de prueba conectado.
- Tests de seed, generación y layout.
- Criterio de salida: un agente se mueve por el mapa y la UI lo muestra.

### 11.2 Fase 1 — MVP

Objetivo: sandbox de supervivencia observable y testeable.

- Atributos, necesidades, estados y muerte.
- Inventario, equipo, recolección, crafteo nivel 1/2 y construcción.
- Día/noche, lluvia, tormenta, niebla, viento, temperatura y mojadura.
- FOV, memoria, percepción limitada y observación MCP completa.
- Comunicación local, alianzas, comercio, combate, huida, cadáveres y saqueo.
- MCP con todas las tools, auth, timeouts e idempotencia.
- Servidor LAN permanente con GUI de operador, agentes efímeros por conexión, máximo concurrente configurable, monitoreo en vivo y logs.
- Panel derecho completo: agentes, ficha, mente, entorno, relaciones y eventos.
- Uso de IA reportado por agente: modelo, esfuerzo, tokens y costo aproximado.
- Pensamientos reportados y timeline.
- Vistas `F1`–`F8` y atajos.
- Guardado/carga, logs JSONL, métricas y replay.
- Agente de referencia y tests de integración.
- Criterio de salida: sesión LAN supervisada con al menos 2 agentes concurrentes que se conectan y desconectan, interactúan con el entorno y entre ellos, con GUI en vivo, logs y replay reproducible.

### 11.3 Fase 2 — Contenido y análisis

- Nieve con acumulación por tile y estaciones de 7 días (configurables).
- Cocina, secado y conservación.
- Fauna pasiva y pesca como alimento; sin depredadores complejos.
- Arcos/flechas, heridas avanzadas e infección.
- Durabilidad simple de herramientas por usos, sin reparación en la primera iteración.
- Pronóstico probabilístico de 3–6 ticks y eventos extremos.
- Comparación de corridas, benchmarks multi-seed y escenarios con aserciones.
- Búsqueda de ticks en replay.
- Emociones/estrés/moral como atributos derivados (evaluar).
- Mouse opcional y mejoras de accesibilidad.
- Consola de debug del operador con inyecciones reproducibles.
- Criterio de salida: experimentos comparables entre agentes y estaciones.

### 11.4 Fase 3 — Investigación avanzada

- Panel de comparación de agentes y torneos.
- Métricas compuestas configurables.
- Cliente LLM de ejemplo con API compatible OpenAI (el usuario aporta la clave; fuera del núcleo).
- Escenarios sintéticos y currículo de pruebas.
- Modos de cámara/zoom adicionales y temas visuales.
- No comprometido para el MVP.

### 11.5 Resumen de alcance

| Capacidad | Fase |
|---|---|
| Isla procedural, mapa 80 × 40, UI 160 × 45 | F0/F1 |
| Supervivencia, necesidades, clima base, crafteo, combate, social | F1 |
| Pensamientos reportados y observabilidad completa | F1 |
| Guardado, replay, métricas, headless, agente de referencia | F1 |
| Nieve por tile, estaciones de 7 días, fauna pasiva, cocina, durabilidad simple, pronóstico probabilístico, mouse opcional, debug | F2 |
| Agente LLM con API compatible OpenAI y comparación avanzada | F3 |

---

## 12. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Fuente Unicode incompleta o “tofu” | Alto | Incluir fuente con licencia, test de glifos y fallback ASCII. |
| Agentes LLM lentos, desconectados o con timeouts | Alto | Deadline configurable, skip, estado ausente solo si sigue conectado, desconexión que retira al agente y modo headless rápido. |
| Pérdida de determinismo por floats | Alto | Enteros escalados, RNG con seed explícita, orden de resolución fijo y tests de hash. |
| Exploits de percepción (leer mapa completo) | Alto | Observación limitada, tools sin admin, validación de rangos y tests de fuga de información. |
| Exposición LAN con tokens por HTTP | Alto | LAN opt-in, token por slot, advertencia visible, red de confianza/VPN; TLS queda fuera del MVP. |
| Balance demasiado duro o trivial | Medio | Constantes configurables, agente de referencia, telemetría y ajuste por seeds. |
| Complejidad de UI en 80 columnas | Medio | Resumen en panel + vistas a pantalla completa + fuentes escalables. |
| Latencia de IA y experiencia de observación | Medio | Pausa automática al abrir overlays, indicadores de “esperando agentes” y timeline. |
| Scope creep en combate/social/clima | Alto | Fases explícitas; MVP con combate táctico simple y clima base. |
| Cambios incompatibles del SDK MCP | Medio | Versión fijada, adaptador aislado y tests de contrato. |
| Pérdida de datos de sesión | Medio | Guardado atómico, autoguardado y snapshots periódicos. |
| Prompt injection en chat/pensamientos | Medio | Texto no confiable, saneado, sin ejecución y sin LLM en el servidor. |
| Muchos agentes degradan rendimiento | Medio | Límite por defecto de 8, test de 8 agentes y métricas de tick. |
| Sobreajuste del agente de referencia al mapa | Bajo | Múltiples seeds y benchmarks en fase 2. |
| Dificultad para comparar agentes | Medio | Métricas vectoriales, logs JSONL y replay; comparación avanzada en F2. |

---

## 13. Decisiones y preguntas abiertas

### 13.1 Decisiones tomadas

| Tema | Decisión |
|---|---|
| Documento | Markdown en español, SRS completo por fases. |
| Arquitectura de agentes | Un servidor MCP HTTP central; agentes externos. |
| Turnos | Tick global; una acción principal y un `say` gratuito por tick; timeout configurable. |
| Ventana y mapa | 160 × 45; mapa 80 × 40; isla completa sin scroll. |
| Bioma | Isla boscosa con río y costa. |
| Agentes | Servidor abierto con hasta 8 agentes concurrentes; cada agente existe solo mientras su conexión MCP está abierta. |
| Atributos | Necesidades + capacidades + clima. |
| Crafteo | Dos niveles, con mesa de trabajo. |
| Clima | MVP: día/noche, lluvia, tormenta, niebla, viento y temperatura; nieve por tile y estaciones de 7 días en F2. |
| Percepción | Limitada por FOV + memoria; el operador puede alternar mapa completo y foco del agente. |
| Acciones MCP | Atómicas + `move_to`; una acción principal por tick. |
| Agente de prueba | Agente scripted de referencia incluido. |
| Interacción | Cooperación, competencia, comercio, alianzas y eliminación; los agentes deciden. |
| Evaluación | Logs JSONL + métricas + replay determinista. |
| Fin de partida | Muerte permanente, sin respawn; cadáver saqueable; el servidor sigue abierto cuando no quedan agentes y el operador decide cuándo terminar. |
| Mapa | Procedural con seed reproducible. |
| Ejecución | GUI del operador + servidor MCP; headless para tests y automatización. |
| Red | Loopback por defecto; LAN opt-in con token y advertencia; sin TLS en el MVP. |
| Conexión | Agente efímero por conexión MCP; desconexión lo retira, libera el slot y deja el inventario en el suelo. |
| Comunicación | Mensajes locales, alianzas y comercio. |
| Combate | Táctico simple: melee, piedra arrojada, huida y sangrado. |
| Inventario | Peso + slots + equipo. |
| Tiempo | Día comprimido configurable: 1 tick = 5 min; 288 ticks/día. |
| Timeout | Skip; desconexión tras 3 timeouts consecutivos. |
| Persistencia | Guardado + replay en el MVP. |
| UI | Dos columnas, pensamientos reportados, atajos y vistas a pantalla completa. |
| Fauna | Pasiva y pesca en F2; sin depredadores complejos. |
| Durabilidad | Simple por usos en F2; sin reparación en la primera iteración. |
| Reputación | Sin puntuación numérica; alianzas declarativas y traiciones solo para métricas. |
| Nieve | Acumulación por tile en F2, con coste de movimiento y visión reducida. |
| Estaciones | 7 días de juego por defecto, configurable. |
| Pronóstico | Probabilístico, horizonte de 3–6 ticks, sin revelar el futuro exacto. |
| LLM de ejemplo | Cliente con API compatible OpenAI en F3; el usuario aporta la clave. |
| Mouse | Opcional en F2; toda función crítica sigue disponible por teclado. |
| Métricas | JSON + CSV en el MVP. |
| Debug | Consola `F12` para el operador, con inyecciones reproducibles y sin exposición por MCP. |

### 13.2 Preguntas abiertas restantes (no bloqueantes)

1. ¿Cuántos usos debe durar cada herramienta y cómo se comunica el desgaste en la UI?
2. ¿Qué parámetros exactos de pronóstico (probabilidades base, horizonte y error) se usan por clima y estación?
3. ¿La consola de debug debe requerir un flag adicional además de `debug.enabled`?
4. ¿Qué proveedores compatibles con OpenAI se documentan como ejemplos y cómo se configura la clave sin exponerla?
5. ¿Qué umbrales de mejora justifican declarar que un agente es “mejor” en los benchmarks multi-seed?

### 13.3 Próximos pasos sugeridos

1. Validar esta especificación y priorizar los requisitos `M` del MVP.
2. Convertir las tablas de atributos, recetas y clima en archivos de configuración.
3. Implementar la Fase 0: mundo determinista + UI base + MCP mínimo.
4. Implementar el agente de referencia y usarlo para calibrar el balance.
5. Congelar el esquema MCP 1.0 antes de conectar agentes LLM.

---

## Anexo A — Glifos y fallback ASCII

| Uso | Unicode | Fallback ASCII |
|---|---|---|
| Agua profunda | `≈` | `~` |
| Agua/río | `~` | `~` |
| Arena | `·` | `.` |
| Pasto | `,` | `,` |
| Pasto alto/juncos | `"` | `"` |
| Árbol/palmera | `♣` | `T` |
| Arbusto | `♠` | `b` |
| Roca/peñasco | `▲` | `^` |
| Suelo rocoso | `▒` | `%` |
| Arcilla | `▓` | `c` |
| Mesa | `≡` | `=` |
| Refugio | `∩` | `n` |
| Fuego | `*` | `*` |
| Cadáver | `☠` | `x` |
| Objeto | `!` | `!` |
| Agente | `@` | `@` |
| Barra llena | `█` | `#` |
| Barra vacía | `░` | `-` |
| Separador | `│` | `|` |

La UI debe detectar glifos faltantes al iniciar y activar el fallback global o por glifo.

---

## Anexo B — Ejemplos JSONL

### B.1 Evento

```json
{"seq":1234,"tick":142,"time":"Día 1 17:50","type":"gather","actor":"ag_01","target":{"x":32,"y":15,"kind":"bush"},"data":{"item":"berry","qty":2},"result":"ok"}
```

### B.2 Acción MCP

```json
{"tick":142,"agent_id":"ag_01","tool":"iasim_gather","args":{"x":32,"y":15},"request_id":"req-8f2a","reason":"Necesito comida antes de la noche","status":"queued","received_at_ms":1750000000456}
```

### B.3 Resultado de acción

```json
{"tick":143,"agent_id":"ag_01","request_id":"req-8f2a","tool":"iasim_gather","status":"success","events":[{"type":"gather","item":"berry","qty":2}],"message":"Recolectaste 2 bayas."}
```

### B.4 Pensamiento reportado

```json
{"tick":142,"agent_id":"ag_01","intent":"Conseguir comida antes del anochecer","thought":"La sed sube; buscaré el río y luego bayas.","plan":["río","arbusto","refugio"],"confidence":72,"received_at_ms":1750000000500}
```

### B.5 Error

```json
{"tick":142,"agent_id":"ag_01","tool":"iasim_craft","request_id":"req-91bc","status":"rejected","error":{"code":"MISSING_INGREDIENTS","message":"Falta 1 piedra afilada."}}
```

---

## Anexo C — Checklist de MVP

- [ ] Mundo 80 × 40 reproducible por seed y validado.
- [ ] UI 160 × 45 con mapa, panel derecho, ticker y barra inferior.
- [ ] Panel con todos los agentes, ficha, mente, entorno, relaciones y eventos.
- [ ] `F1`–`F8` funcionales y navegables solo con teclado.
- [ ] Pensamientos reportados visibles y registrados.
- [ ] Necesidades, estados, clima, inventario, crafteo, combate y muerte.
- [ ] MCP completo con auth, observación, acciones, timeout y errores.
- [ ] Agente de referencia conectado y reportando intención.
- [ ] Guardado/carga, logs JSONL, métricas JSON + CSV y replay.
- [ ] Consola de debug `F12`, registro en `debug.jsonl` y replay de inyecciones.
- [ ] Modo headless con 8 agentes.
- [ ] Tests de determinismo, MCP, persistencia y UI.
- [ ] Documentación de configuración y atajos.

---

*Fin del documento.*
