import html
import json
import os
import re
import unicodedata
from typing import Any

import boto3
import streamlit as st
import streamlit.components.v1 as components
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    ProfileNotFound,
)
from dotenv import load_dotenv


load_dotenv()

REGION = os.getenv("AWS_REGION", "eu-west-1")
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID", "")
MODEL_ARN = os.getenv("MODEL_ARN", "")
AWS_PROFILE = os.getenv("AWS_PROFILE") or None


COURSE_LEVELS = {
    "Programación I": 0,
    "Matemática": 0,
    "Fundamentos de Cloud": 0,
    "Algoritmos": 1,
    "Estadística": 1,
    "Bases de Datos": 1,
    "Machine Learning": 2,
    "Inteligencia Artificial Generativa": 3,
    "MLOps": 4,
}

PREREQUISITES = {
    "Algoritmos": ["Programación I"],
    "Estadística": ["Matemática"],
    "Bases de Datos": ["Programación I"],
    "Machine Learning": ["Algoritmos", "Estadística"],
    "Inteligencia Artificial Generativa": ["Machine Learning", "Bases de Datos"],
    "MLOps": ["Inteligencia Artificial Generativa", "Fundamentos de Cloud"],
}

COURSE_DESCRIPTIONS = {
    "Programación I": (
        "En ella se estudian variables, control de flujo, funciones, estructuras "
        "de datos básicas y pruebas de programas."
    ),
    "Matemática": (
        "En ella se estudian álgebra lineal, funciones, vectores, matrices y "
        "cálculo elemental."
    ),
    "Fundamentos de Cloud": (
        "En ella se estudian modelos de servicio, regiones, disponibilidad, "
        "seguridad, elasticidad y precios basados en consumo."
    ),
    "Algoritmos": (
        "En ella se estudian complejidad, búsqueda, ordenamiento, grafos y "
        "resolución sistemática de problemas."
    ),
    "Estadística": (
        "En ella se estudian probabilidad, distribuciones, estimación, intervalos "
        "de confianza y evaluación de experimentos."
    ),
    "Bases de Datos": (
        "En ella se estudian modelado relacional, SQL, normalización, "
        "transacciones y preparación de datos."
    ),
    "Machine Learning": (
        "En ella se estudian aprendizaje supervisado y no supervisado, "
        "preparación de características, entrenamiento y evaluación de modelos."
    ),
    "Inteligencia Artificial Generativa": (
        "En ella se estudian modelos fundacionales, prompting, embeddings, RAG, "
        "bases vectoriales, grafos de conocimiento, agentes y evaluación."
    ),
    "MLOps": (
        "En ella se estudian empaquetado, despliegue, observabilidad, versionado, "
        "seguridad, automatización y control de costos de soluciones de IA."
    ),
}

EXAMPLE_QUESTIONS = [
    "¿Qué materias puedo hacer con Cloud?",
    "Aprobé Estadística, mostrame sus correlativas.",
    "¿Qué materias me traba Programación I?",
    "Dame un roadmap para Machine Learning.",
    "Mostrame las correlativas de Bases de Datos.",
]



@st.cache_resource
def bedrock_client():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    return session.client("bedrock-agent-runtime")


@st.cache_resource
def interpretation_client():
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    return session.client("bedrock-runtime")


def ground_interpretation(question: str, interpretation: dict[str, Any]) -> dict[str, Any]:
    """El catálogo local manda sobre nombres explícitos, no la memoria del modelo."""
    if not isinstance(interpretation, dict):
        raise ValueError("No pude interpretar ese mensaje. Probá reformularlo.")

    def normalize(text: str) -> str:
        text = "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))
        return " ".join(re.sub(r"[^\w\s]", " ", text).split())

    aliases = {normalize(course): course for course in COURSE_LEVELS}
    aliases.update({
        "ia generativa": "Inteligencia Artificial Generativa",
        "inteligencia artificial": "Inteligencia Artificial Generativa",
        "generativa": "Inteligencia Artificial Generativa",
        "cloud": "Fundamentos de Cloud", "progra 1": "Programación I",
        "progra i": "Programación I", "programacion 1": "Programación I",
        "programacion": "Programación I", "mate": "Matemática",
        "ml": "Machine Learning", "bd": "Bases de Datos",
    })
    text = normalize(question)
    matches: list[tuple[int, int, str]] = []
    for alias in sorted(aliases, key=len, reverse=True):
        for match in re.finditer(r"\b" + re.escape(alias) + r"\b", text):
            if not any(match.start() < end and match.end() > start for start, end, _ in matches):
                matches.append((match.start(), match.end(), aliases[alias]))
    matches.sort()
    # «No Cloud, mostrame Estadística» excluye Cloud; «no aprobé Cloud» no.
    matches = [match for match in matches if not re.search(r"\bno\s*$", text[:match[0]])]
    subjects = list(dict.fromkeys(course for _, _, course in matches))
    if interpretation.get("intent") == "full":
        return interpretation

    corrected = dict(interpretation)
    if not subjects:
        if interpretation.get("intent") == "unknown":
            # Un nombre inexistente del modelo no debe causar un error técnico.
            corrected.update(subjects=[], focus=None,
                             clarification="¿Sobre qué materia del plan querés consultar? Escribí su nombre.")
        return corrected

    # Recuperación acotada: una consulta simple de una materia válida no puede
    # terminar en «esa materia no está en el plan». Preguntas ambiguas siguen unknown.
    stub = text
    for start, end, _ in reversed(matches):
        stub = stub[:start] + "#" + stub[end:]
    patterns = {
        "neighbors": r"(?:(?:mostrame|muestrame|mostrar|las|los|sus|que|cuales|son|correlativas|correlatividades|de|del|la|materia|aprobe|no|estoy|cursando)\s+)*#(?:\s+(?:mostrame|muestrame|sus|las|correlativas|correlatividades))*",
        "route": r"(?:dame |mostrame |muestrame )?(?:un |el )?(?:roadmap|recorrido)(?: completo)? (?:para |hasta |de )?#",
        "downstream": r"(?:aprobe )?# (?:que sigue|que puedo hacer|que materias puedo cursar)",
        "requirements": r"que (?:necesito|requisitos tiene) (?:para )?#",
        "downstream_explicit": r"que (?:correlativa|materias|materias posteriores) me traba #",
        "requirements_explicit": r"(?:mostrame |muestrame )?(?:las )?correlativas anteriores (?:de )?#",
        "downstream_direction": r"(?:mostrame |muestrame )?(?:las )?correlativas posteriores (?:de )?#",
    }
    for intent, pattern in patterns.items():
        if len(subjects) == 1 and re.fullmatch(pattern, stub):
            intent = intent.split("_")[0]
            corrected.update(intent=intent, subjects=subjects, focus=subjects[0], clarification=None)
            return corrected

    if interpretation.get("intent") != "unknown":
        # El modelo decide qué nombres son objetivos y cuáles sólo contexto.
        # No convertir «desde X, roadmap para Y» en dos destinos.
        model_subjects = interpretation.get("subjects", [])
        selected = [course for course in model_subjects if course in subjects] if isinstance(model_subjects, list) else []
        selected = list(dict.fromkeys(selected)) or subjects
        if interpretation.get("intent") == "route":
            destinations = [course for start, _, course in matches
                            if re.search(r"\b(?:para|hasta)\s*$", text[:start])]
            if len(destinations) == 1:
                selected = destinations
        corrected.update(subjects=selected, focus=selected[0], clarification=None)
        return corrected
    corrected.update(subjects=subjects, focus=subjects[0],
                     clarification="¿Querés ver las anteriores, las posteriores o el roadmap de " + ", ".join(subjects) + "?")
    return corrected


def interpret_question(question: str) -> dict[str, Any]:
    # Cada consulta es atómica: no enviamos historial ni acumulamos aprobaciones.
    response = interpretation_client().converse(
        modelId=MODEL_ARN,
        system=[{"text": (
            "Interpretá UNA consulta independiente de correlativas. Devolvé sólo JSON válido "
            "con intent, subjects, focus, clarification. subjects lista las materias OBJETIVO "
            "de ESTA pregunta, con nombres canónicos; focus es la primera o null. "
            "Excluí materias negadas ('No Cloud, mostrame Estadística' → sólo Estadística). "
            "En 'desde X, roadmap para Y', Y es el único objetivo; X es contexto. "
            "No mantenés un registro de aprobadas. 'Aprobé', 'no aprobé' y 'estoy cursando' "
            "sólo señalan materias de interés, sin evaluar elegibilidad. "
            "Intenciones: neighbors (anteriores y posteriores DIRECTAS, también al nombrar "
            "una materia o decir 'aprobé X' sin otra dirección); downstream (posteriores "
            "DIRECTAS: qué sigue, qué puedo hacer con X, qué materias me traba X); "
            "requirements (anteriores DIRECTAS: requisitos de X, qué necesito para X, qué traba a X); "
            "route (roadmap o recorrido de TODOS los requisitos previos de una materia); "
            "full (mapa completo solicitado explícitamente); unknown (materia ausente o ambigua). "
            "Roadmap explícito → route; qué sigue/puedo hacer → downstream; "
            "qué necesito para → requirements; correlativas sin dirección → neighbors. "
            "Correlativas ANTERIORES → requirements; POSTERIORES → downstream. "
            "'Qué correlativa me traba X' significa qué posteriores bloquea X: downstream. "
            "'Qué me traba X' significa qué anteriores necesita X: requirements. "
            "Cloud = Fundamentos de Cloud; progra 1/programación = Programación I; mate = Matemática; "
            "IA generativa = Inteligencia Artificial Generativa; ML = Machine Learning; "
            "BD = Bases de Datos; Programación 1/progra I = Programación I. Interpretá errores de escritura. "
            "materias_del_plan es el catálogo AUTORITATIVO y contiene Inteligencia Artificial Generativa. "
            "Nunca declares inexistente una materia incluida allí ni la reemplaces por Machine Learning. "
            "Una materia escrita sola significa neighbors, no unknown. "
            "No uses conversaciones previas. 'Esa' sin materia explícita y materias fuera del plan "
            "→ unknown y UNA pregunta breve en clarification; en otros casos clarification=null. "
            "Ejemplos: 'Aprobé Cloud, qué puedo hacer' → downstream, subjects=[Fundamentos de Cloud]. "
            "'Aprobé Estadística' → neighbors, subjects=[Estadística]. "
            "'Qué correlativa me traba progra 1' → downstream, subjects=[Programación I]. "
            "'Qué me traba Machine Learning' → requirements, subjects=[Machine Learning]. "
            "'Bases de datos' → neighbors, subjects=[Bases de Datos]. "
            "'Inteligencia Artificial Generativa' y 'Correlativas de Inteligencia Artificial Generativa' "
            "→ {\"intent\":\"neighbors\",\"subjects\":[\"Inteligencia Artificial Generativa\"],"
            "\"focus\":\"Inteligencia Artificial Generativa\",\"clarification\":null}. "
            "'Dame un roadmap para Machine Learning' → route, subjects=[Machine Learning]. "
            "'Aprobé Programación I y Matemática, qué sigue' → downstream, "
            "subjects=[Programación I, Matemática]."
        )}],
        messages=[{"role": "user", "content": [{"text": json.dumps({
            "materias_del_plan": list(COURSE_LEVELS), "mensaje_actual": question,
        }, ensure_ascii=False)}]}],
        inferenceConfig={"maxTokens": 350, "temperature": 0},
    )
    raw = "".join(block.get("text", "") for block in response["output"]["message"]["content"])
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("El modelo no devolvió una interpretación válida. Reformulá tu mensaje.")
    return academic_context(ground_interpretation(question, json.loads(match.group())))

def source_name(reference: dict[str, Any]) -> str:
    location = reference.get("location", {})
    location_type = location.get("type", "")

    if location_type == "S3":
        return location.get("s3Location", {}).get("uri", "Documento en S3")
    if location_type == "WEB":
        return location.get("webLocation", {}).get("url", "Documento web")
    return "Fuente recuperada por la Knowledge Base"


def academic_context(interpretation: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(interpretation, dict):
        raise ValueError("No pude interpretar ese mensaje. Probá reformularlo.")
    intent = interpretation.get("intent")
    focus = interpretation.get("focus")
    subjects = interpretation.get("subjects", [focus] if focus else [])
    if intent not in {"neighbors", "downstream", "requirements", "route", "full", "unknown"}:
        raise ValueError("No pude identificar qué necesitás. Probá reformular tu pregunta.")
    if not isinstance(subjects, list) or any(
        not isinstance(course, str) or course not in COURSE_LEVELS for course in subjects
    ):
        raise ValueError("No pude reconocer las materias dentro de este plan.")
    subjects = list(dict.fromkeys(subjects))
    if focus is not None and (not isinstance(focus, str) or focus not in COURSE_LEVELS):
        raise ValueError("No pude reconocer la materia objetivo dentro de este plan.")
    focus = subjects[0] if subjects else None
    clarification = interpretation.get("clarification")
    if intent not in {"full", "unknown"} and not subjects:
        intent = "unknown"
    if intent == "route" and len(subjects) != 1:
        intent = "unknown"
        clarification = "¿Para qué materia querés ver el roadmap?"
    nodes: set[str] = set()
    edges: list[tuple[str, str]] = []
    statuses: dict[str, str] = {}
    title = "Aclaremos tu consulta"
    all_edges = [
        (requirement, target)
        for target, requirements in PREREQUISITES.items()
        for requirement in requirements
    ]
    if intent == "full":
        focus, subjects = None, []
        nodes = set(COURSE_LEVELS)
        edges = all_edges
        title = "Mapa completo de correlatividades"
    elif intent == "route":
        # Sólo los requisitos previos; el destino aparece en el título del mapa.
        pending = [focus]
        while pending:
            for requirement in PREREQUISITES.get(pending.pop(), []):
                if requirement not in nodes:
                    nodes.add(requirement)
                    pending.append(requirement)
        edges = [(source, target) for source, target in all_edges if source in nodes and target in nodes]
        statuses = {node: "Materia previa del recorrido" for node in nodes}
        title = f"Roadmap previo a {focus}"
    elif intent in {"neighbors", "downstream", "requirements"}:
        selected = set(subjects)
        edges = [
            (source, target) for source, target in all_edges
            if (intent in {"neighbors", "downstream"} and source in selected)
            or (intent in {"neighbors", "requirements"} and target in selected)
        ]
        nodes = selected | {node for edge in edges for node in edge}
        statuses = {subject: "Materia consultada" for subject in subjects}
        for source, target in edges:
            if source not in selected:
                statuses[source] = "Correlativa anterior"
            if target not in selected:
                statuses[target] = "Posterior directa"
        prefix = {
            "neighbors": "Correlativas directas de",
            "downstream": "Posteriores directas de",
            "requirements": "Requisitos directos de",
        }[intent]
        title = f"{prefix} {', '.join(subjects)}"
    return {
        "focus": focus, "subjects": subjects, "intent": intent,
        "nodes": sorted(nodes), "edges": edges, "title": title, "statuses": statuses,
        "clarification": clarification if isinstance(clarification, str) else "¿Sobre qué materia querés consultar?",
    }

def graph_for_answer(question: str, answer: str, context: dict[str, Any] | None = None) -> tuple[set[str], list[tuple[str, str]], str | None, str]:
    context = context or academic_context({"intent": "unknown", "focus": None})
    nodes = set(context["nodes"])
    edges = list(context["edges"])
    return nodes, edges, context["focus"], context["title"]


def label_lines(label: str) -> list[str]:
    if len(label) <= 22:
        return [label]
    words = label.split()
    midpoint = max(1, len(words) // 2)
    return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]


def render_relationship_graph(question: str, answer: str, *, full_map: bool = False, context: dict[str, Any] | None = None) -> None:
    if full_map:
        nodes = set(COURSE_LEVELS)
        edges = [
            (requirement, target)
            for target, requirements in PREREQUISITES.items()
            for requirement in requirements
        ]
        focus = None
        title = "Mapa completo del plan y sus correlativas"
    else:
        context = context or academic_context({"intent": "unknown", "focus": None})
        nodes, edges, focus, title = graph_for_answer(question, answer, context)
        if not nodes:
            st.info(f"{focus} no tiene correlativas previas en este plan." if context["intent"] == "route" else title)
            return
    direct_requirements = set(PREREQUISITES.get(focus or "", []))
    is_direct_graph = bool(focus and nodes == direct_requirements | {focus})
    if is_direct_graph:
        display_levels = {
            node: 1 if node == focus else 0
            for node in nodes
        }
    else:
        minimum_level = min((COURSE_LEVELS[node] for node in nodes), default=0)
        display_levels = {
            node: COURSE_LEVELS[node] - minimum_level
            for node in nodes
        }

    levels = sorted(set(display_levels.values()))
    width = 940
    node_width = 225
    node_height = 76
    top = 70
    level_gap = 135
    height = top + (max(len(levels), 1) - 1) * level_gap + node_height + 35

    positions: dict[str, tuple[float, float]] = {}
    plan_order = {
        "Programación I": 0, "Matemática": 1, "Fundamentos de Cloud": 2,
        "Algoritmos": 0, "Estadística": 1, "Bases de Datos": 2,
    }
    for row, level in enumerate(levels):
        row_nodes = sorted(
            (node for node in nodes if display_levels[node] == level),
            key=lambda node: (plan_order.get(node, 0), node),
        )
        spacing = width / (len(row_nodes) + 1)
        for column, node in enumerate(row_nodes, start=1):
            positions[node] = (spacing * column - node_width / 2, top + row * level_gap)

    edge_svg: list[str] = []
    long_edges = [
        (source, target) for source, target in edges
        if display_levels[target] - display_levels[source] > 1
    ]
    for source, target in edges:
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        x1 = source_x + node_width / 2
        y1 = source_y + node_height
        x2 = target_x + node_width / 2
        y2 = target_y
        outgoing = [end for start, end in edges if start == source]
        incoming = [start for start, end in edges if end == target]
        x1 += (outgoing.index(target) - (len(outgoing) - 1) / 2) * 30
        x2 += (incoming.index(source) - (len(incoming) - 1) / 2) * 30
        middle_y = y1 + (y2 - y1) / 2
        if display_levels[target] - display_levels[source] > 1:
            # Las relaciones que saltan niveles rodean las materias intermedias.
            rail_offset = 28 + long_edges.index((source, target)) * 22
            rail_x = width - rail_offset if source_x > width / 2 else rail_offset
            route = (
                f"M {x1:.1f} {y1:.1f} V {y1 + 22:.1f} H {rail_x} "
                f"V {y2 - 28:.1f} H {x2:.1f} V {y2 - 9:.1f}"
            )
        else:
            route = (
                f"M {x1:.1f} {y1:.1f} C {x1:.1f} {middle_y:.1f}, "
                f"{x2:.1f} {middle_y:.1f}, {x2:.1f} {y2 - 9:.1f}"
            )
        edge_svg.append(
            f'<path d="{route}" '
            'class="edge" marker-end="url(#arrow)" />'
        )

    node_svg: list[str] = []
    for node, (x, y) in positions.items():
        css_class = "node focus" if node == focus else "node"
        status = (context or {}).get("statuses", {}).get(node, "")
        description = f"{status}. {COURSE_DESCRIPTIONS[node]}" if status else COURSE_DESCRIPTIONS[node]
        if status == "Correlativa anterior" or status == "Materia previa del recorrido":
            css_class += " approved"
        elif status == "Posterior directa":
            css_class += " available"
        lines = label_lines(node)
        first_y = y + node_height / 2 - (9 if len(lines) == 2 else 0)
        text = "".join(
            f'<tspan x="{x + node_width / 2:.1f}" y="{first_y + index * 22:.1f}">'
            f'{html.escape(line)}</tspan>'
            for index, line in enumerate(lines)
        )
        node_svg.append(
            f'<g class="course-group" tabindex="0" role="button" '
            f'data-course="{html.escape(node, quote=True)}" '
            f'data-description="{html.escape(description, quote=True)}" '
            f'data-focus="{str(node == focus).lower()}" '
            f'aria-label="Ver información de {html.escape(node, quote=True)}">'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_width}" height="{node_height}" '
            f'rx="18" class="{css_class}"/><text class="node-label">{text}</text></g>'
        )

    graph_html = f"""
    <html>
      <head>
        <style>
          * {{ box-sizing: border-box; }}
          body {{ margin: 0; background: transparent; color: #e7ecf2; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
          .graph-card {{
            position: relative;
            max-width: 1100px;
            margin: 0 auto;
            background: linear-gradient(145deg, #111827, #162033);
            border: 1px solid #2d394a;
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 16px 42px rgba(0, 0, 0, .18);
          }}
          .eyebrow {{ color: #a9b6c7; font-size: 12px; font-weight: 800; letter-spacing: .13em; text-transform: uppercase; }}
          h3 {{ margin: 6px 0 2px; font-size: 21px; color: #f2f4f7; }}
          .hint {{ margin: 0; color: #98a5b5; font-size: 13px; }}
          svg {{ display: block; width: 100%; height: auto; min-height: 150px; }}
          .edge {{ fill: none; stroke: #66778c; stroke-width: 3; stroke-linejoin: round; }}
          .course-group {{ cursor: pointer; outline: none; }}
          .node {{ fill: #1d2938; stroke: #758da3; stroke-width: 2; transition: .18s ease; }}
          .node.approved {{ fill: #253b35; stroke: #8ba99a; }}
          .node.available {{ fill: #39342e; stroke: #b79b78; }}
          .node.pending {{ fill: #3b2c2c; stroke: #b58c83; }}
          .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; color: #b7c1cd; font-size: 12px; }}
          .legend span::before {{ content: ''; display: inline-block; width: 9px; height: 9px; margin-right: 6px; border-radius: 50%; background: var(--dot); }}
          .course-group:hover .node,
          .course-group:focus .node,
          .course-group.active .node {{ fill: #263648; stroke: #b79b78; stroke-width: 3; }}
          .node.focus {{ fill: #b96f5d; stroke: #d9a08f; stroke-width: 3; filter: drop-shadow(0 8px 12px rgba(185,111,93,.22)); }}
          .course-group:hover .node.focus,
          .course-group:focus .node.focus,
          .course-group.active .node.focus {{ fill: #c67a66; stroke: #e0b09f; }}
          .node-label {{ fill: #f6f8fb; font-size: 21px; font-weight: 750; text-anchor: middle; dominant-baseline: middle; }}
          .course-tooltip {{
            position: fixed;
            z-index: 10;
            display: none;
            width: min(330px, calc(100vw - 24px));
            padding: 12px 14px;
            background: #111b29;
            border: 1px solid #344154;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,.25);
            pointer-events: none;
            color: #bcc6d2;
            font-size: 13px;
            line-height: 1.45;
          }}
        </style>
      </head>
      <body>
        <div class="graph-card">
          <div class="eyebrow">Mapa académico</div>
          <h3>{html.escape(title)}</h3>
          <p class="hint">Las flechas apuntan hacia la materia que exige la correlativa. Pasá el cursor o tocá un nodo para ver sus contenidos.</p>
          {'<div class="legend"><span style="--dot:#8ba99a">Anterior</span><span style="--dot:#b79b78">Posterior directa</span></div>' if not full_map and (context or {}).get('intent') == 'neighbors' else ''}
          <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
            <defs>
              <marker id="arrow" markerWidth="10" markerHeight="10" refX="5" refY="3" orient="auto">
                <path d="M0,0 L0,6 L7,3 z" fill="#66778c" />
              </marker>
            </defs>
            {''.join(edge_svg)}
            {''.join(node_svg)}
          </svg>
          <div class="course-tooltip" id="course-tooltip" role="tooltip" aria-live="polite"></div>
        </div>
        <script>
          const courseNodes = [...document.querySelectorAll('.course-group')];
          const tooltip = document.getElementById('course-tooltip');

          function showCourse(node) {{
            courseNodes.forEach(item => item.classList.remove('active'));
            node.classList.add('active');
            tooltip.textContent = node.dataset.course + ': ' + node.dataset.description;
            tooltip.style.display = 'block';
            const rect = node.getBoundingClientRect();
            const left = Math.max(12, Math.min(rect.left, window.innerWidth - tooltip.offsetWidth - 12));
            const top = rect.bottom + tooltip.offsetHeight + 18 < window.innerHeight
              ? rect.bottom + 8 : Math.max(12, rect.top - tooltip.offsetHeight - 8);
            tooltip.style.left = left + 'px';
            tooltip.style.top = top + 'px';
          }}

          function hideCourse(node) {{
            node.classList.remove('active');
            tooltip.style.display = 'none';
          }}

          courseNodes.forEach(node => {{
            node.addEventListener('mouseenter', () => showCourse(node));
            node.addEventListener('click', () => showCourse(node));
            node.addEventListener('focus', () => showCourse(node));
            node.addEventListener('mouseleave', () => hideCourse(node));
            node.addEventListener('blur', () => hideCourse(node));
            node.addEventListener('keydown', event => {{
              if (event.key === 'Enter' || event.key === ' ') {{
                event.preventDefault();
                showCourse(node);
              }}
              if (event.key === 'Escape') hideCourse(node);
            }});
          }});

        </script>
      </body>
    </html>
    """
    # Ajustar el iframe al mapa sin reservar un cajón permanente de detalles.
    component_height = min(height + 145, 960)
    components.html(graph_html, height=component_height, scrolling=False)


def immediate_summary(context: dict[str, Any]) -> str | None:
    def course_list(courses: list[str]) -> str:
        labels = [f"**{course}**" for course in courses]
        return ", ".join(labels[:-1]) + " y " + labels[-1] if len(labels) > 1 else (labels[0] if labels else "")

    intent = context["intent"]
    if intent == "route":
        courses = sorted(context["nodes"], key=lambda course: (COURSE_LEVELS[course], course))
        return (
            f"El roadmap previo a **{context['focus']}** incluye {course_list(courses)}. "
            "Las flechas muestran el orden de las correlativas."
            if courses else f"**{context['focus']}** no tiene correlativas previas en este plan."
        )
    if intent not in {"neighbors", "downstream", "requirements"}:
        return None
    paragraphs = []
    for subject in context["subjects"]:
        previous = PREREQUISITES.get(subject, [])
        following = [target for target, requirements in PREREQUISITES.items() if subject in requirements]
        if intent == "downstream":
            paragraphs.append(
                f"Desde **{subject}**, las posteriores directas son {course_list(following)}."
                if following else f"**{subject}** no tiene posteriores directas en este plan."
            )
        elif intent == "requirements":
            paragraphs.append(
                f"Las correlativas anteriores de **{subject}** son {course_list(previous)}."
                if previous else f"**{subject}** no tiene correlativas anteriores en este plan."
            )
        else:
            before = course_list(previous) or "ninguna"
            after = course_list(following) or "ninguna"
            paragraphs.append(f"**{subject}**\n\nAnterior: {before}.\n\nPosterior directa: {after}.")
    return "\n\n".join(paragraphs)

def render_full_answer(answer: str, sources: list[str], context: dict[str, Any] | None = None, *, question: str | None = None) -> None:
    # La relación consultada se calcula con el mismo plan que dibuja el mapa.
    # No se evalúa habilitación: Bedrock conserva su explicación y evidencia.
    summary = immediate_summary(context) if context else None
    st.markdown(summary or answer)
    if context and len(context.get("subjects", [])) == 1:
        subject = context["subjects"][0]
        st.caption(f"{subject}: {COURSE_DESCRIPTIONS[subject]}")
    if summary:
        st.caption("Relaciones del plan: cada consulta es independiente; no se evalúa habilitación para cursar.")
    if question is not None:
        render_relationship_graph(question, answer, context=context)
    with st.expander("Respuesta original de Bedrock y fuentes" if summary else "Fuentes de la respuesta"):
        if summary:
            st.markdown(answer)
        for source in sources:
            st.caption(f"Fuente: {source}")


def ask_knowledge_base(question: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    if context is None:
        raise ValueError("Primero es necesario interpretar la consulta.")
    scope = {
        "neighbors": "Sólo anteriores y posteriores DIRECTAS de las materias consultadas.",
        "downstream": "Sólo posteriores DIRECTAS. No agregues sus otros requisitos ni ramas.",
        "requirements": "Sólo correlativas anteriores DIRECTAS de la materia consultada.",
        "route": "Sólo todos los requisitos previos de la materia objetivo; sin posteriores ni otras ramas.",
        "full": "Plan completo, porque el usuario lo pidió expresamente.",
        "unknown": "Pedí una aclaración breve.",
    }[context["intent"]]
    request: dict[str, Any] = {
        "input": {"text": question + "\nMaterias relacionadas a verificar: " + ", ".join(context["nodes"])},
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                "modelArn": MODEL_ARN,
                "generationConfiguration": {
                    "inferenceConfig": {"textInferenceConfig": {"maxTokens": 350, "temperature": 0.1, "topP": 0.9}},
                    "promptTemplate": {"textPromptTemplate": (
                        "Sos un asesor de correlativas. Cada pregunta es independiente. "
                        "Respondé en español, en hasta 80 palabras, con relaciones respaldadas por las fuentes. "
                        "NO llevás un registro de aprobaciones ni evaluás habilitación académica. "
                        "Si dice 'aprobé X', interpretalo sólo como interés en las relaciones de X. "
                        "No digas 'te falta', 'todavía no podés', 'materias habilitadas' ni supongas "
                        "aprobadas anteriores. Decí 'posteriores directas' o 'desde X el siguiente vínculo es Y', "
                        "sin prometer habilitación formal para cursar. "
                        f"Alcance: {scope}\n"
                        f"Materias consultadas: {', '.join(context['subjects']) or 'plan completo'}.\n"
                        "Contexto recuperado:\n$search_results$\n\n"
                        "Pregunta:\n$query$\n\nRespuesta:\n$output_format_instructions$"
                    )},
                },
                "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 8}},
            },
        },
    }
    # No reutilizamos sessionId: la KB también responde de manera atómica.
    return bedrock_client().retrieve_and_generate(**request)

st.set_page_config(page_title="Asesor académico GraphRAG", page_icon="🕸️", layout="wide")
st.title("🕸️ Asesor académico GraphRAG")
st.caption("Amazon Bedrock Knowledge Bases + Amazon Neptune Analytics")
st.markdown("""
<style>
[data-testid="stChatInput"] {
    background: linear-gradient(135deg, #19212d, #202a35);
    border: 1px solid #46505d; border-radius: 20px; padding: 22px;
    box-shadow: 0 8px 28px rgba(0,0,0,.12);
}
[data-testid="stChatInput"] textarea { color: #e9edf1; }
[data-testid="stChatInput"]:focus-within { border-color: #b79b78; }
[data-testid="stChatInputSubmitButton"] { color: #b79b78; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    if st.button("Ver mapa completo", use_container_width=True):
        st.session_state.app_view = "Mapa del plan"
    app_view = st.radio("Vista", ["Consultas", "Mapa del plan"], key="app_view")
    suggested_question = None
    if app_view == "Consultas":
        st.subheader("Probá estas preguntas")
        for index, example in enumerate(EXAMPLE_QUESTIONS):
            if st.button(example, key=f"example_{index}", use_container_width=True):
                suggested_question = example
        if st.button("Nueva conversación"):
            st.session_state.messages = []

if app_view == "Mapa del plan":
    st.caption(
        f"{len(COURSE_LEVELS)} materias · "
        f"{sum(len(requirements) for requirements in PREREQUISITES.values())} relaciones de correlatividad · "
        "Plan completo, sin filtros."
    )
    render_relationship_graph("", "", full_map=True)
    st.stop()

if not KNOWLEDGE_BASE_ID or not MODEL_ARN:
    st.error(
        "Faltan KNOWLEDGE_BASE_ID o MODEL_ARN. Copiá .env.example como .env "
        "y completá los valores de tu cuenta AWS."
    )
    st.stop()

# Una sesión abierta con el comportamiento anterior no debe conservar sus respuestas.
if st.session_state.get("query_behavior_version") != "atomic_relations_v1":
    st.session_state.messages = []
    st.session_state.pop("bedrock_session_id", None)
    st.session_state.pop("academic_context", None)
    st.session_state.query_behavior_version = "atomic_relations_v1"

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant" and message.get("question") and not message.get("clarification"):
            render_full_answer(message["content"], message.get("sources", []), message.get("context"), question=message["question"])
        else:
            st.markdown(message["content"])

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("Consultá una materia o pedí un recorrido. Por ejemplo: **‘Aprobé Estadística, mostrame sus correlativas’**.")
        st.caption("Cada pregunta es independiente: nombrá la materia. Mostramos relaciones del plan, sin acumular aprobadas.")
typed_question = st.chat_input("Escribí tu mensaje…", key="conversation_input")
typed_question = typed_question.strip() if typed_question else None
question = suggested_question or typed_question
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Interpretando tu mensaje..."):
                context = interpret_question(question)
            if context["intent"] == "unknown":
                answer = context["clarification"]
                st.markdown(answer)
                st.session_state.messages.append({
                    "role": "assistant", "content": answer, "question": question,
                    "context": context, "clarification": True,
                })
                st.stop()
            with st.spinner("Consultando las correlativas..."):
                response = ask_knowledge_base(question, context)

            answer = response["output"]["text"]

            sources: list[str] = []
            for citation in response.get("citations", []):
                for reference in citation.get("retrievedReferences", []):
                    name = source_name(reference)
                    if name not in sources:
                        sources.append(name)

            render_full_answer(answer, sources, context, question=question)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "question": question,
                    "context": context,
                }
            )
        except (NoCredentialsError, ProfileNotFound):
            st.error(
                "Falta iniciar sesión en AWS con tu perfil. Revisá AWS_PROFILE en .env "
                "y autenticá ese perfil mediante AWS CLI; consultá el README."
            )
        except (ClientError, BotoCoreError) as error:
            st.error(f"AWS devolvió un error: {error}")
        except (ValueError, KeyError, TypeError) as error:
            st.error(f"No pude interpretar la consulta: {error}")
