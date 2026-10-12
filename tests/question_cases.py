"""Preguntas de regresión; expectativas revisadas, sin depender del modelo."""
COURSES = ['Programación I', 'Matemática', 'Fundamentos de Cloud', 'Algoritmos',
           'Estadística', 'Bases de Datos', 'Machine Learning',
           'Inteligencia Artificial Generativa', 'MLOps']
CASES = [(course, 'neighbors', [course]) for course in COURSES]
CASES += [(f'Qué necesito para {course}', 'requirements', [course]) for course in COURSES]
CASES += [
    ('Aprobé Cloud, ¿qué materias puedo hacer?', 'downstream', ['Fundamentos de Cloud']),
    ('Aprobé Estadística', 'neighbors', ['Estadística']),
    ('Qué correlativa me traba progra 1', 'downstream', ['Programación I']),
    ('Qué me traba Machine Learning', 'requirements', ['Machine Learning']),
    ('Roadmap para Machine Learning', 'route', ['Machine Learning']),
    ('Correlativas de IA generativa', 'neighbors', ['Inteligencia Artificial Generativa']),
    ('Programacion 1', 'neighbors', ['Programación I']),
    ('Correlativas de ML', 'neighbors', ['Machine Learning']),
    ('Correlativas de BD', 'neighbors', ['Bases de Datos']),
    ('Qué sigue después de MLOps', 'downstream', ['MLOps']),
    ('Mostrame todo el mapa', 'full', []),
    ('¿Y esa?', 'unknown', []),
    ('Correlativas de Física', 'unknown', []),
    ('No Cloud, mostrame Estadística', 'neighbors', ['Estadística']),
    ('Desde Programación I, dame un roadmap para Machine Learning', 'route', ['Machine Learning']),
    ('Aprobé Programación I y Matemática, qué sigue', 'downstream', ['Programación I', 'Matemática']),
    ('Correlativas anteriores de Estadística', 'requirements', ['Estadística']),
    ('Correlativas posteriores de Estadística', 'downstream', ['Estadística']),
    ('Roadmap para IA generativa', 'route', ['Inteligencia Artificial Generativa']),
    ('Correlativas de estadistca', 'neighbors', ['Estadística']),
]
