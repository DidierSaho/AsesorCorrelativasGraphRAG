"""Pruebas sin llamadas a AWS ni ejecución de la interfaz de Streamlit."""
import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from typing import Any
import unicodedata


SOURCE = Path(__file__).resolve().parents[1] / "app.py"
FUNCTIONS = {
    "academic_context", "graph_for_answer", "immediate_summary",
    "interpret_question", "ask_knowledge_base", "ground_interpretation",
}
CONSTANTS = {"COURSE_LEVELS", "PREREQUISITES"}
tree = ast.parse(SOURCE.read_text())
selected = [
    node for node in tree.body
    if (isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS)
    or (isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in CONSTANTS for target in node.targets
    ))
]
namespace = {"Any": Any, "json": json, "re": re, "unicodedata": unicodedata, "MODEL_ARN": "test", "KNOWLEDGE_BASE_ID": "test"}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)


class AtomicRelationsTests(unittest.TestCase):
    def context(self, intent, *subjects):
        return namespace["academic_context"]({"intent": intent, "subjects": list(subjects)})

    def test_every_course_every_scope_against_independent_plan(self):
        # Oráculo independiente: no derivar lo esperado de PREREQUISITES.
        edges = {
            ("Programación I", "Algoritmos"), ("Programación I", "Bases de Datos"),
            ("Matemática", "Estadística"), ("Algoritmos", "Machine Learning"),
            ("Estadística", "Machine Learning"),
            ("Machine Learning", "Inteligencia Artificial Generativa"),
            ("Bases de Datos", "Inteligencia Artificial Generativa"),
            ("Inteligencia Artificial Generativa", "MLOps"), ("Fundamentos de Cloud", "MLOps"),
        }
        courses = {course for edge in edges for course in edge}
        self.assertEqual(set(namespace['COURSE_LEVELS']), courses)
        for course in courses:
            for intent in ['neighbors', 'requirements', 'downstream', 'route']:
                with self.subTest(course=course, intent=intent):
                    if intent == 'route':
                        nodes = set()
                        pending = [course]
                        while pending:
                            for source, target in edges:
                                if target == pending[-1] and source not in nodes:
                                    nodes.add(source)
                            current = pending.pop()
                            pending.extend(source for source, target in edges
                                           if target == current and source not in pending)
                        expected = {(a, b) for a, b in edges if a in nodes and b in nodes}
                    else:
                        expected = {(a, b) for a, b in edges
                                    if (intent != 'requirements' and a == course)
                                    or (intent != 'downstream' and b == course)}
                        nodes = {course} | {node for edge in expected for node in edge}
                    context = self.context(intent, course)
                    self.assertEqual(set(context['nodes']), nodes)
                    self.assertEqual(set(context['edges']), expected)
                    summary = namespace['immediate_summary'](context).lower()
                    for forbidden in ['te falta', 'habilitada', 'aprobadas', 'podés cursar']:
                        self.assertNotIn(forbidden, summary)

    def test_aliases_and_direction_recover_wrong_model(self):
        rejected = {'intent': 'unknown', 'subjects': [], 'focus': None}
        cases = [
            ('ML', 'neighbors', 'Machine Learning'),
            ('Correlativas de BD', 'neighbors', 'Bases de Datos'),
            ('Programacion 1', 'neighbors', 'Programación I'),
            ('progra I', 'neighbors', 'Programación I'),
            ('Correlativas anteriores de Estadística', 'requirements', 'Estadística'),
            ('Correlativas posteriores de Estadística', 'downstream', 'Estadística'),
            ('Qué correlativa me traba progra 1', 'downstream', 'Programación I'),
        ]
        for question, intent, course in cases:
            with self.subTest(question=question):
                c = namespace['academic_context'](namespace['ground_interpretation'](question, rejected))
                self.assertEqual((c['intent'], c['subjects']), (intent, [course]))

    def test_target_selection_and_negation(self):
        for question, interpretation, expected in [
            ('Desde Programación I, dame un roadmap para Machine Learning',
             {'intent': 'route', 'subjects': ['Programación I', 'Machine Learning']}, ['Machine Learning']),
            ('No Cloud, mostrame Estadística',
             {'intent': 'neighbors', 'subjects': ['Estadística']}, ['Estadística']),
            ('No aprobé Cloud, qué sigue',
             {'intent': 'downstream', 'subjects': ['Fundamentos de Cloud']}, ['Fundamentos de Cloud']),
        ]:
            with self.subTest(question=question):
                c = namespace['academic_context'](namespace['ground_interpretation'](question, interpretation))
                self.assertEqual(c['subjects'], expected)
                self.assertNotEqual(c['intent'], 'unknown')

    def test_unknown_course_is_clarification_not_exception(self):
        c = namespace['academic_context'](namespace['ground_interpretation']('Correlativas de Física', {
            'intent': 'unknown', 'subjects': ['Física'], 'focus': 'Física',
        }))
        self.assertEqual(c['intent'], 'unknown')
        self.assertEqual(c['nodes'], [])

    def test_six_question_shapes_for_all_nine_courses(self):
        rejected = {'intent': 'unknown', 'subjects': [], 'focus': None}
        templates = [
            ('Correlativas de {}', 'neighbors'), ('Aprobé {}', 'neighbors'),
            ('Roadmap para {}', 'route'), ('Aprobé {} que sigue', 'downstream'),
            ('Correlativas anteriores de {}', 'requirements'),
            ('Correlativas posteriores de {}', 'downstream'),
        ]
        for course in namespace['COURSE_LEVELS']:
            for template, intent in templates:
                question = template.format(course)
                with self.subTest(question=question):
                    actual = namespace['academic_context'](namespace['ground_interpretation'](question, rejected))
                    self.assertEqual((actual['intent'], actual['subjects']), (intent, [course]))

    def test_every_pair_has_only_union_of_requested_direct_edges(self):
        import itertools
        for first, second in itertools.combinations(namespace['COURSE_LEVELS'], 2):
            for intent in ['neighbors', 'requirements', 'downstream']:
                with self.subTest(subjects=[first, second], intent=intent):
                    first_context = self.context(intent, first)
                    second_context = self.context(intent, second)
                    combined = self.context(intent, first, second)
                    self.assertEqual(set(combined['edges']),
                                     set(first_context['edges']) | set(second_context['edges']))
                    self.assertEqual(set(combined['nodes']),
                                     set(first_context['nodes']) | set(second_context['nodes']))

    def test_bad_model_payloads_fail_with_controlled_error(self):
        for payload in [None, [], {'intent': 'other'}, {'intent': 'neighbors', 'subjects': 'ML'},
                        {'intent': 'neighbors', 'subjects': [None]},
                        {'intent': 'neighbors', 'subjects': ['Machine Learning'], 'focus': 2}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                namespace['academic_context'](payload)

    def test_cloud_only_shows_cloud_and_mlops(self):
        context = self.context("downstream", "Fundamentos de Cloud")
        self.assertEqual(set(context["nodes"]), {"Fundamentos de Cloud", "MLOps"})
        self.assertEqual(context["edges"], [("Fundamentos de Cloud", "MLOps")])
        self.assertNotIn("te falta", namespace["immediate_summary"](context).lower())

    def test_valid_generative_course_cannot_be_rejected(self):
        rejected = {"intent": "unknown", "subjects": [], "focus": None,
                    "clarification": "La materia no está en el plan. ¿Referencia a Machine Learning?"}
        for question in ["Inteligencia Artificial Generativa", "Correlativas de Inteligencia Artificial Generativa",
                         "IA generativa", "Mostrame las correlativas de IA Generativa"]:
            with self.subTest(question=question):
                context = namespace["academic_context"](namespace["ground_interpretation"](question, rejected))
                self.assertEqual(context["intent"], "neighbors")
                self.assertEqual(context["focus"], "Inteligencia Artificial Generativa")
                self.assertEqual(set(context["nodes"]), {
                    "Inteligencia Artificial Generativa", "Machine Learning", "Bases de Datos", "MLOps",
                })

    def test_grounding_keeps_unknown_for_real_ambiguity(self):
        rejected = {"intent": "unknown", "subjects": [], "focus": None}
        for question in ["Física", "¿Y esa?", "IA generativa o Física, ¿cuál es mejor?"]:
            self.assertEqual(namespace["ground_interpretation"](question, rejected)["intent"], "unknown")

    def test_wrong_model_subject_is_corrected(self):
        result = namespace["ground_interpretation"](
            "Correlativas de Inteligencia Artificial Generativa",
            {"intent": "neighbors", "subjects": ["Machine Learning"], "focus": "Machine Learning"},
        )
        self.assertEqual(result["subjects"], ["Inteligencia Artificial Generativa"])

    def test_statistics_only_its_previous_and_next(self):
        context = self.context("neighbors", "Estadística")
        self.assertEqual(set(context["nodes"]), {"Matemática", "Estadística", "Machine Learning"})
        self.assertEqual(set(context["edges"]), {
            ("Matemática", "Estadística"), ("Estadística", "Machine Learning"),
        })

    def test_programming_direct_successors(self):
        context = self.context("downstream", "Programación I")
        self.assertEqual(set(context["nodes"]), {"Programación I", "Algoritmos", "Bases de Datos"})

    def test_machine_learning_roadmap_only_previous_courses(self):
        context = self.context("route", "Machine Learning")
        self.assertEqual(set(context["nodes"]), {
            "Programación I", "Algoritmos", "Matemática", "Estadística",
        })
        self.assertEqual(set(context["edges"]), {
            ("Programación I", "Algoritmos"), ("Matemática", "Estadística"),
        })
        self.assertIn("Machine Learning", context["title"])

    def test_database_neighbors(self):
        context = self.context("neighbors", "Bases de Datos")
        self.assertEqual(set(context["nodes"]), {
            "Programación I", "Bases de Datos", "Inteligencia Artificial Generativa",
        })

    def test_requirements_do_not_check_approval(self):
        context = namespace["academic_context"]({
            "intent": "requirements", "subjects": ["Machine Learning"],
            "approved": ["Algoritmos", "Estadística"],
        })
        self.assertEqual(set(context["nodes"]), {"Machine Learning", "Algoritmos", "Estadística"})
        text = namespace["immediate_summary"](context)
        self.assertIn("Algoritmos", text)
        self.assertIn("Estadística", text)
        self.assertNotIn("Podés cursar", text)
        self.assertNotIn("approved", context)

    def test_edges_are_not_expanded_by_renderer(self):
        context = self.context("downstream", "Fundamentos de Cloud")
        self.assertEqual(namespace["graph_for_answer"]("", "", context)[1], context["edges"])

    def test_full_plan_and_empty_roadmap(self):
        self.assertEqual(len(self.context("full")["edges"]), 9)
        context = self.context("route", "Programación I")
        self.assertEqual(context["nodes"], [])
        self.assertIn("no tiene", namespace["immediate_summary"](context))

    def test_multiple_subjects_only_direct_links(self):
        context = self.context("downstream", "Programación I", "Matemática")
        self.assertEqual(set(context["nodes"]), {
            "Programación I", "Matemática", "Algoritmos", "Bases de Datos", "Estadística",
        })

    def test_invalid_course_and_ambiguous_roadmap(self):
        with self.assertRaises(ValueError):
            self.context("neighbors", "Otra materia")
        self.assertEqual(self.context("neighbors")["intent"], "unknown")
        self.assertEqual(self.context("route", "Matemática", "MLOps")["intent"], "unknown")

    def test_interpreter_does_not_send_previous_context(self):
        captured = {}
        class Runtime:
            def converse(self, **request):
                captured.update(request)
                return {"output": {"message": {"content": [{"text": json.dumps({
                    "intent": "neighbors", "subjects": ["Estadística"],
                })}]}}}
        namespace["interpretation_client"] = lambda: Runtime()
        context = namespace["interpret_question"]("Aprobé Estadística")
        payload = json.loads(captured["messages"][0]["content"][0]["text"])
        self.assertEqual(set(payload), {"materias_del_plan", "mensaje_actual"})
        self.assertNotIn("MLOps", context["nodes"])

    def test_kb_does_not_reuse_session(self):
        captured = {}
        class Runtime:
            def retrieve_and_generate(self, **request):
                captured.update(request)
                return {"output": {"text": "test"}}
        namespace["bedrock_client"] = lambda: Runtime()
        namespace["ask_knowledge_base"](
            "Cloud qué sigue", self.context("downstream", "Fundamentos de Cloud"),
        )
        self.assertNotIn("sessionId", captured)

    def test_streamlit_two_independent_messages(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        requests = []
        class Runtime:
            def converse(self, **request):
                payload = json.loads(request["messages"][0]["content"][0]["text"])
                requests.append(payload)
                question = payload["mensaje_actual"]
                interpretation = (
                    {"intent": "downstream", "subjects": ["Fundamentos de Cloud"]}
                    if "Cloud" in question else
                    {"intent": "neighbors", "subjects": ["Estadística"]}
                )
                return {"output": {"message": {"content": [{"text": json.dumps(interpretation)}]}}}

            def retrieve_and_generate(self, **request):
                self_assert = "sessionId" not in request
                if not self_assert:
                    raise AssertionError("La KB recibió una sesión anterior")
                return {"output": {"text": "Explicación de prueba"}, "citations": [], "sessionId": "unused"}

        class Session:
            def __init__(self, **kwargs):
                pass
            def client(self, name):
                return Runtime()

        st.cache_resource.clear()
        try:
            with patch.dict("os.environ", {
                "MODEL_ARN": "test", "KNOWLEDGE_BASE_ID": "test", "AWS_REGION": "eu-west-1",
            }), patch("boto3.Session", Session):
                app = AppTest.from_file(str(SOURCE)).run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.chat_input), 1)
                app.chat_input[0].set_value("Aprobé Cloud, qué puedo hacer").run()
                self.assertFalse(app.exception)
                self.assertEqual(set(app.session_state.messages[-1]["context"]["nodes"]), {
                    "Fundamentos de Cloud", "MLOps",
                })
                app.chat_input[0].set_value("Aprobé Estadística").run()
                self.assertFalse(app.exception)
                context = app.session_state.messages[-1]["context"]
                self.assertEqual(set(context["nodes"]), {"Matemática", "Estadística", "Machine Learning"})
                self.assertNotIn("approved", context)
                self.assertEqual(len(requests), 2)
                for payload in requests:
                    self.assertEqual(set(payload), {"materias_del_plan", "mensaje_actual"})
        finally:
            st.cache_resource.clear()


if __name__ == "__main__":
    unittest.main()
