# Verificación de consultas — 11 de octubre de 2026

## Alcance y resultado

- Pruebas locales: nueve materias × cuatro alcances de mapa (36 combinaciones),
  nueve materias × seis formas simples de pregunta (54), todas las parejas de
  materias × tres alcances directos (108), más regresiones de alias, errores,
  ausencia de aprobaciones acumuladas y dos mensajes consecutivos en Streamlit.
- Bedrock real: 38 preguntas, 38 correctas tras los ajustes. Se verifica intención
  y materias objetivo; los mapas se comprueban por separado en las pruebas locales.
- La app respondió `ok` en su endpoint de salud del puerto 8501.
- La ronda final consumió 28.447 tokens de entrada y 1.734 de salida en Converse.
  Hubo además una ronda diagnóstica inicial de 20 preguntas, sin medición de tokens.
  No se sincronizó Neptune ni se modificaron recursos AWS. En esta revisión no se
  probó la explicación original de RetrieveAndGenerate ni la interacción visual de
  los tooltips; no confundir estas pruebas con una evaluación integral de GraphRAG.

Ningún conjunto finito garantiza todas las formulaciones posibles. Una consulta
ambigua debe pedir aclaración, no inventar una materia o mostrar todo el mapa.

## Correcciones

- IA Generativa, ML, BD y Programación 1 se reconocen como nombres del catálogo.
- «Anteriores» y «posteriores» conservan la dirección explícita.
- Una materia inexistente genera aclaración, no un error técnico.
- «No Cloud, mostrame Estadística» consulta sólo Estadística.
- «Desde Programación I, roadmap para Machine Learning» toma Machine Learning
  como destino único. El roadmap sigue mostrando todos sus antecedentes; no
  supone aprobada la materia de partida.
- El modelo elige el objetivo de preguntas compuestas; el catálogo valida los
  nombres y recupera consultas simples cuando el modelo rechaza un nombre válido.

## Preguntas para la demo

| Pregunta | Resultado esperado |
| --- | --- |
| Aprobé Cloud, ¿qué materias puedo hacer? | Cloud → MLOps, sin otras ramas |
| Aprobé Estadística | Matemática → Estadística → Machine Learning |
| Correlativas de IA Generativa | ML y Bases de Datos → IA Generativa → MLOps |
| Correlativas de Bases de Datos | Programación I → Bases de Datos → IA Generativa |
| Qué correlativa me traba progra 1 | Programación I → Algoritmos y Bases de Datos |
| Qué me traba Machine Learning | Algoritmos y Estadística → Machine Learning |
| Dame un roadmap para Machine Learning | Programación I, Algoritmos, Matemática y Estadística; destino en el título |
| Correlativas anteriores de MLOps | IA Generativa y Cloud → MLOps |
| Qué sigue después de MLOps | No hay posteriores en este plan |
| Mostrame todo el mapa | Las nueve materias y las nueve relaciones |
| Correlativas de Física | Pide una materia del plan |
| ¿Y esa? | Pide el nombre; no usa el mensaje anterior |

Cada mensaje es independiente. «Aprobé» no evalúa elegibilidad real ni acumula
aprobaciones. «Qué materias me traba X» consulta posteriores bloqueadas por X;
«qué me traba X» consulta los requisitos anteriores de X.

## Repetir las pruebas

Desde la carpeta del proyecto:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Para repetir las 38 preguntas contra AWS (facturable; requiere credenciales):

```sh
.venv/bin/python tests/verify_live_questions.py --live --limit 40
```

El segundo comando imprime resultados y tokens, no llama a GraphRAG y tiene
un límite máximo de 50 consultas por ejecución. La temperatura cero reduce la
variación, pero no garantiza respuestas idénticas del modelo en futuras pruebas.
